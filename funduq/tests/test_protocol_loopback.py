"""The two machines, wired to each other through the codec, with a real funduq
at one end and a real `ProviderRuntime` at the other.

No socket and no sleep: frames cross as dicts through the same
`encode`/`decode` a wire would use, so what is exercised is the protocol
rather than a Python call. This is the harness the orderings in
`docs/link-protocol-machine.md` are meant to be driven by, and it lives here
because the SDK may not import core — and because a machine only downstream
exercises rots the way the prose it replaces did.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from funduq.core import Funduq
from funduq.models import AgentRef
from funduq_provider_sdk import DeliveredRun, ProviderIdentity, ProviderRuntime, Refusal
from funduq_provider_sdk.protocol import (
    Answered,
    Asking,
    Cancelled,
    ConnectRequested,
    Deleting,
    Failed,
    Finished,
    Gone,
    LinkFailed,
    Offered,
    Opened,
    ProviderSide,
    Refused,
    Registering,
    Replied,
    Reported,
    FunduqSide,
    decode,
    encode,
)


class _Identity(ProviderIdentity):

    def __init__(self) -> None:
        super().__init__(Ed25519PrivateKey.generate())


class EchoAgent:

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def run_stream(self, agent_name: str, run_input: Any):
        self.seen.append(run_input.run_id)
        yield {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "hi"}


class Loopback:
    """A driver on each end and a pair of dict queues between them.

    The drivers are the part a transport author writes, and they are this
    short on purpose: pump frames, and turn each event into the one `Funduq`
    call it names. Every ordering rule lives in the machines.
    """

    def __init__(
        self,
        funduq: Funduq,
        identity: ProviderIdentity,
        provider: Any,
        *,
        max_concurrent_runs: int | None = None,
    ) -> None:
        self.funduq = funduq
        self.identity = identity
        self.runtime = ProviderRuntime(
            identity, provider, max_concurrent_runs=max_concurrent_runs
        )
        self.max_concurrent_runs = max_concurrent_runs
        self.funduq_side = FunduqSide(deliver_timeout=funduq.broker.deliver_timeout_seconds)
        self.provider_side = ProviderSide(
            identity, funduq_public_key=funduq.identity_public_key
        )
        self.to_provider: asyncio.Queue = asyncio.Queue()
        self.to_funduq: asyncio.Queue = asyncio.Queue()
        self.answers: dict[str, asyncio.Future] = {}
        self.replies: dict[str, asyncio.Future] = {}
        self.public_key = identity.public_key
        self.opened = asyncio.get_event_loop().create_future()
        self.link_failures: list[str] = []
        self._tasks: list[asyncio.Task] = []

    # -- what core sees ------------------------------------------------

    async def deliver(self, run: Any) -> bool | Refusal:
        """The `ConnectedProvider` contract, answered off the link.

        The correlation table is the machine's, so the one thing four
        implementations each had to get right — that an answer counts only on
        the connection that made the offer — is not a rule here, it is that
        the table belongs to this instance.
        """
        delivered = DeliveredRun.from_claimed(run)
        offer_id, turn = self.funduq_side.offer(delivered, now=0.0)
        answer: asyncio.Future = asyncio.get_running_loop().create_future()
        self.answers[offer_id] = answer
        self._send(turn, self.to_provider)
        return await answer

    def cancel(self, run_id: str) -> None:
        self._send(self.funduq_side.cancel(run_id), self.to_provider)

    # -- the handshake, over the link ----------------------------------

    async def open(self) -> None:
        self.runtime.start()
        self._tasks = [
            asyncio.create_task(self._pump_funduq()),
            asyncio.create_task(self._pump_provider()),
        ]
        ticket = self.funduq.issue_ticket(self.identity.public_key)
        self._send(
            self.provider_side.connect(
                ticket=ticket, nonce="n-1", max_concurrent_runs=self.max_concurrent_runs
            ),
            self.to_funduq,
        )
        await asyncio.wait_for(self.opened, 2)

    async def register(self, names: list[str]) -> Any:
        request_id, turn = self.provider_side.register([{"name": n} for n in names])
        reply: asyncio.Future = asyncio.get_running_loop().create_future()
        self.replies[request_id] = reply
        self._send(turn, self.to_funduq)
        return await asyncio.wait_for(reply, 2)

    async def ask_thread_messages(self, thread_id: str) -> Any:
        request_id, turn = self.provider_side.ask("thread_messages", {"thread_id": thread_id})
        reply: asyncio.Future = asyncio.get_running_loop().create_future()
        self.replies[request_id] = reply
        self._send(turn, self.to_funduq)
        return await asyncio.wait_for(reply, 2)

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        self.funduq.detach_provider(self.public_key, self)
        self.funduq_side.connection_lost()
        self.provider_side.connection_lost()
        # `cancel_in_flight` because a teardown must never wait on agent code:
        # an agent still holding a run would hang the suite rather than fail it.
        await self.runtime.aclose(cancel_in_flight=True)

    async def drop(self) -> None:
        """Lose the connection without a polite goodbye — what a wifi blip
        looks like from funduq's side."""
        for task in self._tasks:
            task.cancel()
        turn = self.funduq_side.connection_lost()
        assert isinstance(turn.events[0], Gone)
        self.funduq.detach_provider(self.public_key, self)

    # -- the drivers ---------------------------------------------------

    async def _pump_funduq(self) -> None:
        while True:
            frame = decode(await self.to_funduq.get())
            turn = self.funduq_side.feed(frame, now=0.0)
            self._send(turn, self.to_provider)
            for event in turn.events:
                await self._on_funduq_event(event)

    async def _on_funduq_event(self, event: Any) -> None:
        if isinstance(event, ConnectRequested):
            self.max_concurrent_runs = event.max_concurrent_runs
            answer = await self.funduq.attach_provider(
                self,
                ticket=event.ticket,
                provider_nonce=event.nonce,
                proof=event.proof,
            )
            self._send(self.funduq_side.accept_connect(answer), self.to_provider)
        elif isinstance(event, Registering):
            registered = await self.funduq.register_agents(self, event.agents)
            self._send(self.funduq_side.reply_ok(event.id, registered), self.to_provider)
        elif isinstance(event, Deleting):
            await self.funduq.delete_agent(self, event.name)
            self._send(self.funduq_side.reply_ok(event.id), self.to_provider)
        elif isinstance(event, Asking):
            messages = await self.funduq.get_thread_messages(event.args["thread_id"])
            self._send(self.funduq_side.reply_ok(event.id, messages), self.to_provider)
        elif isinstance(event, Answered):
            future = self.answers.pop(event.id, None)
            if future is not None and not future.done():
                future.set_result(event.verdict)
        elif isinstance(event, Reported):
            self.funduq.report_event(event.run_id, event.event, claimed_by=self.public_key)
        elif isinstance(event, Finished):
            self.funduq.finish_run(event.run_id, claimed_by=self.public_key)
        elif isinstance(event, LinkFailed):
            self.link_failures.append(event.reason)

    async def _pump_provider(self) -> None:
        while True:
            frame = decode(await self.to_provider.get())
            turn = self.provider_side.feed(frame)
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
        elif isinstance(event, Offered):
            accepted = await self.runtime.deliver(event.run)
            self._send(self.provider_side.answer(event.id, accepted), self.to_funduq)
        elif isinstance(event, Cancelled):
            self.runtime.cancel(event.run_id)
        elif isinstance(event, (Replied, Failed)):
            future = self.replies.pop(event.id, None)
            if future is not None and not future.done():
                if isinstance(event, Failed):
                    future.set_exception(RuntimeError(event.reason))
                else:
                    future.set_result(event.payload)

    def _send(self, turn: Any, queue: asyncio.Queue) -> None:
        for frame in turn.frames:
            queue.put_nowait(encode(frame))


class _ReportingRuntimeLink:
    """What the runtime reports through: it speaks to the provider machine."""

    def __init__(self, loopback: Loopback) -> None:
        self._loopback = loopback

    @property
    def public_key(self) -> str:
        return self._loopback.public_key

    async def report_event(self, run_id: str, event: Any) -> None:
        self._loopback._send(
            self._loopback.provider_side.report(run_id, event), self._loopback.to_funduq
        )

    async def finish_run(self, run_id: str) -> None:
        self._loopback._send(
            self._loopback.provider_side.finish(run_id), self._loopback.to_funduq
        )


@pytest.fixture
async def link(funduq: Funduq):
    made: list[Loopback] = []

    async def make(provider=None, **kwargs) -> Loopback:
        loopback = Loopback(funduq, _Identity(), provider or EchoAgent(), **kwargs)
        loopback.runtime.link = _ReportingRuntimeLink(loopback)
        await loopback.open()
        made.append(loopback)
        return loopback

    yield make
    for loopback in made:
        await loopback.close()


async def test_a_run_reaches_the_agent_and_its_events_reach_the_caller(funduq, link) -> None:
    """End to end over frames: nothing in this path is a Python call between
    the two sides."""
    agent = EchoAgent()
    loopback = await link(agent)
    await loopback.register(["translator"])

    handle = await funduq.start_run(
        AgentRef(provider_key=loopback.public_key, name="translator"), {"messages": []}
    )
    seen = [event async for event in handle.events()]

    assert agent.seen == [handle.run_id]
    assert any(getattr(e, "delta", None) == "hi" or e.get("delta") == "hi" for e in _dicts(seen))


def _dicts(events: list[Any]) -> list[dict]:
    out = []
    for event in events:
        dump = getattr(event, "model_dump", None)
        out.append(dump(by_alias=True) if dump else event)
    return out


async def test_a_permanent_refusal_travels_with_the_providers_own_words(funduq, link) -> None:
    """The three-valued answer survives the wire. A transport that collapsed
    it into one bit would leave the run re-offered forever, reading `queued`
    from every vantage point."""

    class Retired:
        async def run_stream(self, agent_name, run_input):
            yield {"type": "RUN_STARTED"}

    loopback = await link(Retired())
    await loopback.register(["translator"])

    async def refuse(run: DeliveredRun) -> Refusal:
        return Refusal("this agent was retired")

    loopback.runtime.deliver = refuse

    handle = await funduq.start_run(
        AgentRef(provider_key=loopback.public_key, name="translator"), {"messages": []}
    )
    [event async for event in handle.events()]

    run = await funduq.get_run(handle.run_id)
    assert run.status == "failed"
    assert run.metadata["failureReason"] == "this agent was retired"


async def test_a_query_travels_out_and_its_answer_comes_back_by_id(funduq, link) -> None:
    loopback = await link()
    await loopback.register(["translator"])
    handle = await funduq.start_run(
        AgentRef(provider_key=loopback.public_key, name="translator"),
        {"messages": [{"role": "user", "content": "hello"}]},
    )
    [event async for event in handle.events()]

    messages = await loopback.ask_thread_messages(handle.thread_id)

    assert [m["content"] for m in messages if m.get("role") == "user"] == ["hello"]


async def test_registration_happens_on_the_link_and_nothing_about_it_is_signed(
    funduq, link
) -> None:
    """The key was proved once, when the link opened; a per-operation
    signature would only re-prove it."""
    loopback = await link()

    registered = await loopback.register(["translator", "summarizer"])

    assert sorted(registered["agents"]) == ["summarizer", "translator"]
    assert funduq.broker.serving(
        AgentRef(provider_key=loopback.public_key, name="translator")
    ) is loopback


async def test_a_dropped_connection_leaves_the_verdict_to_core(funduq, link) -> None:
    """The machine says what it observed and draws no conclusion; core decides
    what a claimed run becomes.

    That division is the point of `Gone`, and it is what #214 turns on: the
    grace this deployment might want is core's policy, and nothing in the
    protocol layer forecloses it.
    """
    started = asyncio.Event()
    release = asyncio.Event()  # never set: the agent is still holding the run when the link dies

    class Slow:
        async def run_stream(self, agent_name, run_input):
            started.set()
            await release.wait()
            yield {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "late"}

    loopback = await link(Slow())
    await loopback.register(["translator"])
    handle = await funduq.start_run(
        AgentRef(provider_key=loopback.public_key, name="translator"), {"messages": []}
    )
    await asyncio.wait_for(started.wait(), 2)

    await loopback.drop()
    [event async for event in handle.events()]

    run = await funduq.get_run(handle.run_id)
    assert run.status == "failed"
    assert run.metadata["failureReason"] == "provider_left_holding_it"
