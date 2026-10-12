"""AG-UI 1.0 makes `protocolVersion` a producer's MUST on `RunAgentInput` and
`RUN_STARTED`, and the SDK does not fill it in (#290). funduq produces the
input every agent receives — from either door — and the `RUN_STARTED` of a
run nobody is serving, so those carry it. Events an agent writes are the
agent's to version.
"""

from __future__ import annotations

from a2a.server.context import ServerCallContext
from a2a.types import a2a_pb2 as pb
from ag_ui.core import PROTOCOL_VERSION, RunAgentInput, UserMessage

from funduq.doors import offline_events
from funduq.protocols.a2a import A2ARequestHandler
from funduq.protocols.agui import AGUIAdapter


class Receives:
    def __init__(self) -> None:
        self.rounds: list[dict] = []

    async def run_stream(self, agent_name: str, run_input):
        self.rounds.append(run_input.model_dump(mode="json", by_alias=True))
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        yield {"type": "RUN_FINISHED", **ids}


async def test_the_agui_door_delivers_a_versioned_input(funduq, serve):
    # No `tools`, no `context`: both are optional in 1.0, and the door used to iterate them unguarded.
    provider = Receives()
    served = await serve(provider, "a")

    result = await AGUIAdapter(funduq).run(
        served.agents["a"],
        RunAgentInput(
            thread_id="t-v", run_id="r", messages=[UserMessage(id="m1", role="user", content="hi")]
        ),
    )
    [_ async for _ in result.events]

    assert provider.rounds[0]["protocolVersion"] == PROTOCOL_VERSION
    assert (await funduq.run_input(result.run_id))["protocolVersion"] == PROTOCOL_VERSION


async def test_the_a2a_door_delivers_a_versioned_input(funduq, serve):
    provider = Receives()
    served = await serve(provider, "b")

    await A2ARequestHandler(funduq, served.agents["b"]).on_message_send(
        pb.SendMessageRequest(
            message=pb.Message(message_id="m-in", role=pb.Role.ROLE_USER, parts=[pb.Part(text="hi")])
        ),
        ServerCallContext(),
    )

    assert provider.rounds[0]["protocolVersion"] == PROTOCOL_VERSION


async def test_the_run_funduq_starts_for_an_offline_agent_is_versioned():
    started = [event async for event in offline_events("t", "r")][0]

    assert started["type"] == "RUN_STARTED"
    assert started["protocolVersion"] == PROTOCOL_VERSION
