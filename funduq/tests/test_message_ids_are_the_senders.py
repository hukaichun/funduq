from __future__ import annotations

import pytest
from ag_ui.core import RunAgentInput, UserMessage

from funduq import repo
from funduq.errors import InvalidRunInput
from funduq.protocols.agui import AGUIAdapter
from funduq_contract import Registration


class RecordingProvider:

    def __init__(self) -> None:
        self.inputs: list = []

    async def run_stream(self, agent_id: str, run_input):
        self.inputs.append(run_input)
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        yield {"type": "TEXT_MESSAGE_START", "messageId": "agent-1", "role": "assistant"}
        yield {"type": "TEXT_MESSAGE_CONTENT", "messageId": "agent-1", "delta": "ok"}
        yield {"type": "TEXT_MESSAGE_END", "messageId": "agent-1"}
        yield {"type": "RUN_FINISHED", **ids}


async def _attached(funduq, new_identity, attach):
    identity = new_identity()
    async with funduq.session() as session:
        agent_id = (await repo.register_agents(session, identity.public_key, [Registration(name="a")]))["a"]
    provider = RecordingProvider()
    await attach(identity, provider, [agent_id.name])
    return agent_id, provider


async def test_the_agent_receives_the_callers_message_ids(funduq, new_identity, attach):
    agent_id, provider = await _attached(funduq, new_identity, attach)

    handle = await funduq.start_run(agent_id, {"messages": [{"id": "client-1", "role": "user", "content": "hi"}]})
    [_ async for _ in handle.events()]

    assert [m.id for m in provider.inputs[0].messages] == ["client-1"]


async def test_the_agui_stream_carries_the_agents_message_ids(funduq, serve):
    served = await serve(RecordingProvider(), "a")
    body = RunAgentInput(
        thread_id="t-1", run_id="r", state={}, tools=[], context=[], forwarded_props={},
        messages=[UserMessage(id="client-1", role="user", content="hi")],
    )

    result = await AGUIAdapter(funduq).run(served.agents["a"], body)

    assert {e["messageId"] async for e in result.events if "messageId" in e} == {"agent-1"}


async def test_a_resent_message_id_opens_the_next_run_on_the_same_thread(funduq, new_identity, attach):
    agent_id, provider = await _attached(funduq, new_identity, attach)
    first = await funduq.start_run(agent_id, {"messages": [{"id": "client-1", "role": "user", "content": "hi"}]})
    [_ async for _ in first.events()]

    second = await funduq.start_run(
        agent_id,
        {"messages": [
            {"id": "client-1", "role": "user", "content": "hi"},
            {"id": "client-2", "role": "user", "content": "again"},
        ]},
        thread_id=first.thread_id,
    )
    [_ async for _ in second.events()]

    assert [m.id for m in provider.inputs[1].messages] == ["client-1", "client-2"]


async def test_one_input_may_not_carry_the_same_message_id_twice(funduq, new_identity, attach):
    agent_id, _ = await _attached(funduq, new_identity, attach)

    with pytest.raises(InvalidRunInput):
        await funduq.start_run(
            agent_id,
            {"messages": [
                {"id": "client-1", "role": "user", "content": "hi"},
                {"id": "client-1", "role": "user", "content": "hi again"},
            ]},
        )
