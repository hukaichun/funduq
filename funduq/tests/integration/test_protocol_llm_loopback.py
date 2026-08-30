"""The completion half of the link, machine to machine through its own codec,
with a real funduq at one end.

The agent loopback's peer. What it proves that the unit tests cannot is that
`FunduqLlmSide` satisfies the thing core actually reaches for —
`ConnectedLLMProvider.complete(request)` returning an async iterator that
raises what the relay knows how to read.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from openai.types.chat import ChatCompletionChunk

from funduq.core import Funduq
from funduq.kyok import CompletionRequest
from funduq.models import LlmRef
from funduq.protocols.kyok import CompletionRelay
from funduq_provider_sdk.llm import (
    Chunked,
    CompletionBroke,
    CompletionEnded,
    CompletionRequested,
    DeliveredCompletion,
    FunduqLlmSide,
    ProviderLlmSide,
    RegisteringLlm,
    decode,
)
from funduq_provider_sdk.protocol import (
    AskingThreadMessages,
    ConnectRequested,
    Deleting,
    Failed,
    LinkFailed,
    Opened,
    Refused,
    Replied,
    encode,
)
from funduq_provider_sdk.llm import ProviderIdentity


class _Identity(ProviderIdentity):

    def __init__(self) -> None:
        super().__init__(Ed25519PrivateKey.generate())


def _chunk(text: str, *, finish: str | None = None) -> ChatCompletionChunk:
    delta: dict = {} if finish else {"content": text}
    return ChatCompletionChunk.model_validate(
        {
            "id": "chatcmpl-stub",
            "object": "chat.completion.chunk",
            "created": 1755300000,
            "model": "stub-model",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
    )


class Refuses(Exception):

    def __init__(self, refusal: dict[str, Any]) -> None:
        super().__init__(str(refusal))
        self.refusal = refusal


class LlmLoopback:
    """Two machines and a pair of dict queues, with the drivers a transport
    author would write."""

    def __init__(self, funduq: Funduq, identity: ProviderIdentity, handler) -> None:
        self.funduq = funduq
        self.identity = identity
        self.handler = handler
        self.public_key = identity.public_key
        self.funduq_side = FunduqLlmSide()
        self.provider_side = ProviderLlmSide(
            identity, funduq_public_key=funduq.identity_public_key
        )
        self.to_provider: asyncio.Queue = asyncio.Queue()
        self.to_funduq: asyncio.Queue = asyncio.Queue()
        self.streams: dict[str, asyncio.Queue] = {}
        self.replies: dict[str, asyncio.Future] = {}
        self.opened: asyncio.Future = asyncio.get_event_loop().create_future()
        self._tasks: list[asyncio.Task] = []

    # -- what core sees ------------------------------------------------

    async def complete(self, request: CompletionRequest):
        """`ConnectedLLMProvider.complete`, over frames.

        A caller that stops consuming reaches nobody: in-process the handler
        hears `GeneratorExit`, and over a wire nothing reaches the provider at
        all, so it goes on producing into a consumer that has gone. Recorded
        rather than closed — see funduq#220.
        """
        delivered = DeliveredCompletion.from_request(request)
        request_id, turn = self.funduq_side.complete(delivered)
        inbox: asyncio.Queue = asyncio.Queue()
        self.streams[request_id] = inbox
        self._send(turn, self.to_provider)
        try:
            while True:
                item = await inbox.get()
                if item is None:
                    return
                if isinstance(item, Exception):
                    raise item
                yield ChatCompletionChunk.model_validate(item)
        finally:
            self.streams.pop(request_id, None)

    # -- the handshake -------------------------------------------------

    async def open(self) -> None:
        self._tasks = [
            asyncio.create_task(self._pump_funduq()),
            asyncio.create_task(self._pump_provider()),
        ]
        ticket = self.funduq.issue_ticket(self.public_key)
        self._send(self.provider_side.connect(ticket=ticket, nonce="n-1"), self.to_funduq)
        await asyncio.wait_for(self.opened, 2)

    async def register(self, names: list[str], metadata=None) -> Any:
        request_id, turn = self.provider_side.register(names, metadata)
        reply: asyncio.Future = asyncio.get_running_loop().create_future()
        self.replies[request_id] = reply
        self._send(turn, self.to_funduq)
        return await asyncio.wait_for(reply, 2)

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        self.funduq.detach_llm_provider(self.public_key, self)

    # -- the drivers ---------------------------------------------------

    async def _pump_funduq(self) -> None:
        while True:
            turn = self.funduq_side.feed(decode(await self.to_funduq.get()))
            self._send(turn, self.to_provider)
            for event in turn.events:
                await self._on_funduq_event(event)

    async def _on_funduq_event(self, event: Any) -> None:
        if isinstance(event, ConnectRequested):
            answer = await self.funduq.attach_llm_provider(
                self, ticket=event.ticket, provider_nonce=event.nonce, proof=event.proof
            )
            self._send(self.funduq_side.accept_connect(answer), self.to_provider)
        elif isinstance(event, RegisteringLlm):
            registered = await self.funduq.register_llm_providers(
                self, event.names, event.metadata
            )
            self._send(self.funduq_side.reply_ok(event.id, registered), self.to_provider)
        elif isinstance(event, Deleting):
            await self.funduq.delete_llm_offering(self, event.name)
            self._send(self.funduq_side.reply_ok(event.id), self.to_provider)
        elif isinstance(event, Chunked):
            inbox = self.streams.get(event.id)
            if inbox is not None:
                inbox.put_nowait(event.chunk)
        elif isinstance(event, CompletionEnded):
            inbox = self.streams.pop(event.id, None)
            if inbox is not None:
                inbox.put_nowait(None)
        elif isinstance(event, CompletionBroke):
            inbox = self.streams.pop(event.id, None)
            if inbox is not None:
                inbox.put_nowait(
                    Refuses(event.refusal) if event.refusal else RuntimeError(event.reason)
                )

    async def _pump_provider(self) -> None:
        while True:
            turn = self.provider_side.feed(decode(await self.to_provider.get()))
            self._send(turn, self.to_funduq)
            for event in turn.events:
                await self._on_provider_event(event)

    async def _on_provider_event(self, event: Any) -> None:
        if isinstance(event, Opened):
            if not self.opened.done():
                self.opened.set_result(True)
        elif isinstance(event, Refused):
            if not self.opened.done():
                self.opened.set_exception(RuntimeError(event.reason))
        elif isinstance(event, CompletionRequested):
            asyncio.create_task(self._serve(event))
        elif isinstance(event, Replied):
            future = self.replies.pop(event.id, None)
            if future is not None and not future.done():
                future.set_result(event.payload)
        elif isinstance(event, Failed):
            future = self.replies.pop(event.id, None)
            if future is not None and not future.done():
                future.set_exception(RuntimeError(event.reason))

    async def _serve(self, event: CompletionRequested) -> None:
        try:
            async for chunk in self.handler(event.completion):
                self._send(self.provider_side.chunk(event.id, chunk), self.to_funduq)
        except Exception as exc:
            refusal = getattr(exc, "refusal", None)
            self._send(
                self.provider_side.fail(event.id, str(exc), refusal), self.to_funduq
            )
            return
        self._send(self.provider_side.end(event.id), self.to_funduq)

    def _send(self, turn: Any, queue: asyncio.Queue) -> None:
        for frame in turn.frames:
            queue.put_nowait(encode(frame))


@pytest.fixture
async def llm_link(funduq: Funduq):
    made: list[LlmLoopback] = []

    async def make(handler) -> LlmLoopback:
        loopback = LlmLoopback(funduq, _Identity(), handler)
        await loopback.open()
        made.append(loopback)
        return loopback

    yield make
    for loopback in made:
        await loopback.close()


def _request(ref: LlmRef) -> CompletionRequest:
    return CompletionRequest(
        run_id="r-1",
        agent=ref,
        body={"model": "stub-model", "messages": [{"role": "user", "content": "hi"}]},
        llm_name=ref.name,
    )


async def test_a_completion_streams_back_and_collapses_for_the_caller(funduq, llm_link) -> None:
    async def handler(delivered: DeliveredCompletion):
        yield _chunk("hello ")
        yield _chunk("world")
        yield _chunk("", finish="stop")

    link = await llm_link(handler)
    await link.register(["gpt4"])
    ref = LlmRef(provider_key=link.public_key, name="gpt4")

    serving = funduq.kyok_relay.serving(ref)
    completion = await CompletionRelay(
        stream_requested=False, chunks=serving.complete(_request(ref))
    ).collapsed()

    assert completion.choices[0].message.content == "hello world"


async def test_a_structured_refusal_reaches_the_relay_as_a_refusal(funduq, llm_link) -> None:
    """Its vocabulary is the provider's, relayed intact — funduq never
    interprets it, and `refused` is what separates a policy working from a
    failure funduq observed."""

    async def handler(delivered: DeliveredCompletion):
        raise Refuses({"code": "over_budget", "spent": 12})
        yield  # pragma: no cover - makes this an async generator

    link = await llm_link(handler)
    await link.register(["gpt4"])
    ref = LlmRef(provider_key=link.public_key, name="gpt4")

    serving = funduq.kyok_relay.serving(ref)
    relay = CompletionRelay(stream_requested=True, chunks=serving.complete(_request(ref)))
    drained = [item async for item in relay.stream()]

    failure = drained[-1]
    assert failure.refused is True
    assert failure.payload == {"code": "over_budget", "spent": 12}


async def test_the_offerings_register_on_the_link_with_their_metadata(funduq, llm_link) -> None:
    """The one roster verb whose shape differs between the two link kinds, and
    the reason it is not a shared frame."""

    async def handler(delivered: DeliveredCompletion):
        yield _chunk("", finish="stop")

    link = await llm_link(handler)

    registered = await link.register(["gpt4", "gpt4-mini"], {"terms": "internal only"})

    assert sorted(registered) == ["gpt4", "gpt4-mini"]
    assert funduq.kyok_relay.serving(LlmRef(provider_key=link.public_key, name="gpt4")) is link
