"""One form in the database: `runs.input_json` is the `RunAgentInput` the
provider was handed — from either door, on a fresh run and on a reopened
ask. The record then keeps exactly what the agent received, and a restart
has a row it can hand straight back (#254, #122).
"""

from __future__ import annotations

from a2a.server.context import ServerCallContext
from a2a.types import a2a_pb2 as pb
from ag_ui.core import RunAgentInput, ToolMessage, UserMessage

from funduq import repo
from funduq.pause import open_asks
from funduq.protocols.a2a import A2ARequestHandler
from funduq.protocols.agui import AGUIAdapter, EventStream


class Receives:
    """Answers immediately; keeps every input it was handed, as the wire dict."""

    def __init__(self) -> None:
        self.rounds: list[dict] = []

    async def run_stream(self, agent_name: str, run_input):
        self.rounds.append(run_input.model_dump(mode="json", by_alias=True))
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        yield {"type": "RUN_FINISHED", **ids}


class AsksOnce(Receives):
    """Round one leaves a tool call unanswered, which pauses the run; round two finishes."""

    async def run_stream(self, agent_name: str, run_input):
        self.rounds.append(run_input.model_dump(mode="json", by_alias=True))
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        if len(self.rounds) == 1:
            yield {"type": "TOOL_CALL_START", "toolCallId": "call-1", "toolCallName": "lookup"}
            yield {"type": "TOOL_CALL_ARGS", "toolCallId": "call-1", "delta": "{}"}
            yield {"type": "TOOL_CALL_END", "toolCallId": "call-1"}
        yield {"type": "RUN_FINISHED", **ids}


def _utterance(thread_id: str) -> RunAgentInput:
    return RunAgentInput(
        thread_id=thread_id, run_id="the-caller-picked-this", state={"n": 1},
        messages=[UserMessage(id="m1", role="user", content="hi")],
        tools=[], context=[], forwarded_props={"theirs": True},
    )


async def _stored(funduq, run_id: str) -> dict:
    """The row's projection — the `RunAgentInput` the run is."""
    return await funduq.run_input(run_id)


async def test_the_agui_door_stores_what_it_delivers(funduq, serve):
    provider = Receives()
    served = await serve(provider, "a")

    result = await AGUIAdapter(funduq).run(served.agents["a"], _utterance("t-agui"))
    assert isinstance(result, EventStream)
    [_ async for _ in result.events]

    assert provider.rounds == [await _stored(funduq, result.run_id)]
    assert provider.rounds[0]["runId"] == result.run_id
    assert provider.rounds[0]["forwardedProps"]["theirs"] is True


async def test_the_a2a_door_stores_what_it_delivers(funduq, serve):
    provider = Receives()
    served = await serve(provider, "b")
    handler = A2ARequestHandler(funduq, served.agents["b"])

    task = await handler.on_message_send(
        pb.SendMessageRequest(
            message=pb.Message(message_id="m-in", role=pb.Role.ROLE_USER, parts=[pb.Part(text="hi")])
        ),
        ServerCallContext(),
    )

    assert provider.rounds == [await _stored(funduq, task.id)]
    assert RunAgentInput.model_validate(provider.rounds[0]).thread_id == task.context_id


async def test_the_answer_to_an_ask_is_a_run_whose_row_is_what_it_delivered(funduq, serve):
    provider = AsksOnce()
    served = await serve(provider, "c")
    agent = served.agents["c"]

    first = await AGUIAdapter(funduq).run(agent, _utterance("t-ask"))
    [_ async for _ in first.events]
    assert (await funduq.get_run(first.run_id)).status == "completed"
    assert open_asks(await funduq.get_run_events(first.run_id)) == {"call-1"}
    assert provider.rounds == [await _stored(funduq, first.run_id)]

    second = await AGUIAdapter(funduq).run(
        agent,
        RunAgentInput(
            thread_id=first.thread_id, run_id="ignored", state={},
            messages=[ToolMessage(id="r1", role="tool", tool_call_id="call-1", content="found")],
            tools=[], context=[], forwarded_props=None,
        ),
    )
    assert isinstance(second, EventStream) and second.run_id != first.run_id, "every input is a run"
    [_ async for _ in second.events]

    assert (await funduq.get_run(second.run_id)).parent_run_id == first.run_id, "the answer names the run that asked"
    assert len(provider.rounds) == 2
    assert provider.rounds[1] == await _stored(funduq, second.run_id), "its own row, its own input"
    assert provider.rounds[0] == await _stored(funduq, first.run_id), "and the asking run's row is untouched"
