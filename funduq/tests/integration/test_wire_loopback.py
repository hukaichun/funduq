"""The wire, simulated without a transport.

Every crossing in these tests is serialized to JSON bytes and rebuilt on
the far side from the published frame shapes — exactly what a real
transport carries — with no socket anywhere. This is the proof behind the
docs' claim that the SDKs let you exercise the wire without touching a
transport: if a frame shape drifts, this file fails the way a deployed
gateway would.
"""

from __future__ import annotations

from tests.conftest import publish_agents, publish_llm, publish_offline

import asyncio
import json

from ag_ui.core import RunAgentInput, UserMessage
from openai.types.chat import ChatCompletionChunk

from funduq_provider_sdk.llm import DeliveredCompletion
from funduq_provider_sdk import (
    AgentHandle,
    DeliveredRun,
    HandleProvider,
    ProviderIdentity,
    ProviderRuntime,
    Refusal,
)

from funduq.models import LlmRef
from funduq.protocols.agui import AGUIAdapter
from funduq_contract import Registration


class WireLink:
    """A ConnectedProvider whose every crossing is JSON bytes, not objects."""

    def __init__(self, funduq, runtime: ProviderRuntime) -> None:
        self._funduq = funduq
        self._runtime = runtime
        runtime.link = self
        self.public_key = runtime.public_key
        self.max_concurrent_runs = runtime.max_concurrent_runs

    def sign_connect(
        self, funduq_public_key: str, funduq_nonce: str, provider_nonce: str
    ) -> str:
        # the claimed funduq key, the challenge and the proof all cross as bytes too
        relayed_key = funduq_public_key.encode().decode()
        relayed = funduq_nonce.encode().decode()
        return self._runtime.identity.sign_connect(relayed_key, relayed, provider_nonce)

    async def deliver(self, run: DeliveredRun) -> None:
        frame = run.model_dump_json(by_alias=True).encode()
        delivered = DeliveredRun.model_validate_json(frame)
        accepted = await self._runtime.deliver(delivered)
        # The verdict crosses back as bytes too, and enters through the door —
        # the same road every later report takes, so it cannot be outrun.
        answer = json.dumps({"accepted": bool(accepted)}).encode()
        self._funduq.answer_offer(
            run.run_id, json.loads(answer)["accepted"], provider_key=self.public_key
        )

    async def cancel(self, run_id: str) -> bool:
        self._runtime.cancel(json.loads(json.dumps(run_id)))
        return True

    def takes_interjections(self, agent_name: str) -> bool:
        # A wire connection answers from what the remote link declared; this
        # loopback's remote is the runtime itself.
        return json.loads(json.dumps(self._runtime.takes_interjections(agent_name)))
    async def report_event(self, run_id: str, event) -> None:
        frame = json.dumps({"runId": run_id, "event": event}).encode()
        decoded = json.loads(frame)
        self._funduq.report_event(decoded["runId"], decoded["event"], claimed_by=self.public_key)

    async def finish_run(self, run_id: str) -> None:
        self._funduq.finish_run(json.loads(json.dumps(run_id)), claimed_by=self.public_key)

    async def thread_messages(self, thread_id: str, *, limit: int | None = None):
        raw = await self._funduq.get_thread_messages(thread_id)
        return json.loads(json.dumps(raw))


async def test_a_run_travels_as_byte_frames_end_to_end(funduq):
    async def agent(run_input: RunAgentInput):
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        yield {
            "type": "TEXT_MESSAGE_CONTENT",
            "messageId": "m-out",
            "delta": f"caller={((run_input.forwarded_props or {}).get('caller') or {}).get('subject')}",
        }
        yield {"type": "RUN_FINISHED", **ids}

    identity = ProviderIdentity.generate()
    registration = await publish_offline(funduq, identity, [Registration(name="wired")])
    runtime = ProviderRuntime(identity, HandleProvider([AgentHandle("wired", agent)]))
    runtime.start()
    link = WireLink(funduq, runtime)
    try:
        await publish_agents(funduq, link, ["wired"])

        stream = await AGUIAdapter(funduq).run(
            registration["wired"],
            RunAgentInput(
                thread_id="t-wire",
                run_id="ignored",
                state={},
                messages=[UserMessage(id="m1", role="user", content="hi")],
                tools=[],
                context=[],
                forwarded_props={},
            ),
        )
        async with asyncio.timeout(5):
            events = [e async for e in stream.events]
    finally:
        await runtime.aclose(cancel_in_flight=True)

    assert [e["type"] for e in events] == [
        "RUN_STARTED",
        "TEXT_MESSAGE_CONTENT",
        "RUN_FINISHED",
    ]


class WireLLMLink:
    """A ConnectedLLMProvider whose request and chunks cross as JSON bytes."""

    def __init__(self, identity: ProviderIdentity) -> None:
        self._identity = identity
        self.public_key = identity.public_key

    def sign_connect(
        self, funduq_public_key: str, funduq_nonce: str, provider_nonce: str
    ) -> str:
        return self._identity.sign_connect(funduq_public_key, funduq_nonce, provider_nonce)

    def complete(self, request: DeliveredCompletion):
        frame = request.model_dump_json(by_alias=True).encode()
        delivered = DeliveredCompletion.model_validate_json(frame)

        async def _chunks():
            chunk = ChatCompletionChunk.model_validate(
                {
                    "id": "chatcmpl-wire",
                    "object": "chat.completion.chunk",
                    "created": 1755300000,
                    "model": delivered.body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": f"for {delivered.agent_name}"},
                            "finish_reason": "stop",
                        }
                    ],
                }
            )
            wire = chunk.model_dump_json().encode()
            yield ChatCompletionChunk.model_validate_json(wire)

        return _chunks()


async def test_a_completion_travels_as_byte_frames(funduq):
    identity = ProviderIdentity.generate()
    link = WireLLMLink(identity)
    await publish_llm(funduq, link, ["wire-model"])

    ref = LlmRef(provider_key=identity.public_key, name="wire-model")
    serving = funduq.kyok_relay.serving(ref)
    agent_ref = registration_ref(identity)
    request = DeliveredCompletion(
        run_id="run-wire",
        provider_key=agent_ref.provider_key,
        agent_name=agent_ref.name,
        body={"model": "wire-model", "messages": [{"role": "user", "content": "hi"}]},
        llm_name="wire-model",
    )
    chunks = [chunk async for chunk in serving.complete(request)]

    funduq.detach_all_for(identity.public_key)
    assert chunks[0].choices[0].delta.content == "for wired-agent"


def registration_ref(identity: ProviderIdentity):
    from funduq.models import AgentRef

    return AgentRef(provider_key=identity.public_key, name="wired-agent")
