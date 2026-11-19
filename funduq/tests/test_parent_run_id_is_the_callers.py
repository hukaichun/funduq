"""Whether a run continues another is the caller's to say, with `parentRunId`.
funduq checks only that the run it names is on the same thread and has finished;
without one, the run starts a lineage of its own."""

from __future__ import annotations

import asyncio

import pytest
from ag_ui.core import ResumeEntry, RunAgentInput, UserMessage

from funduq.errors import InvalidRunInput
from funduq.protocols.agui import AGUIAdapter
from tests.conftest import EchoAgent


class _NeverFinishes:
    async def run_stream(self, agent_name: str, run_input):
        yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_input.run_id}
        await asyncio.Event().wait()


def _body(thread_id: str, message_id: str, *, parent_run_id=None, resume=None) -> RunAgentInput:
    return RunAgentInput(
        thread_id=thread_id, run_id="ignored", state={},
        messages=[UserMessage(id=message_id, role="user", content="hi")],
        tools=[], context=[], forwarded_props={},
        parent_run_id=parent_run_id, resume=resume,
    )


async def _until_running(funduq, run_id: str) -> None:
    for _ in range(200):
        if (await funduq.get_run(run_id)).status == "running":
            return
        await asyncio.sleep(0.01)
    raise AssertionError("never ran")


async def test_a_run_that_has_not_finished_cannot_be_continued(funduq, serve):
    agent = (await serve(_NeverFinishes(), "busy")).agents["busy"]
    adapter = AGUIAdapter(funduq)

    first = await adapter.run(agent, _body("t-busy", "m1"))
    await _until_running(funduq, first.run_id)

    with pytest.raises(InvalidRunInput):
        await adapter.run(agent, _body(first.thread_id, "m2", parent_run_id=first.run_id))


async def test_the_parent_must_be_a_run_on_this_thread(funduq, serve):
    agent = (await serve(EchoAgent(), "echo")).agents["echo"]
    adapter = AGUIAdapter(funduq)

    elsewhere = await adapter.run(agent, _body("t-elsewhere", "m1"))
    [_ async for _ in elsewhere.events]

    with pytest.raises(InvalidRunInput):
        await adapter.run(agent, _body("t-here", "m1", parent_run_id=elsewhere.run_id))
    with pytest.raises(InvalidRunInput):
        await adapter.run(agent, _body("t-here", "m1", parent_run_id="run_nobody"))


async def test_a_finished_run_is_continued(funduq, serve):
    agent = (await serve(EchoAgent(), "echo")).agents["echo"]
    adapter = AGUIAdapter(funduq)

    first = await adapter.run(agent, _body("t-on", "m1"))
    [_ async for _ in first.events]
    second = await adapter.run(agent, _body(first.thread_id, "m2", parent_run_id=first.run_id))
    [_ async for _ in second.events]

    assert (await funduq.get_run(second.run_id)).parent_run_id == first.run_id


async def test_without_a_parent_a_resume_starts_its_own_lineage(funduq, serve):
    """funduq does not read `resume` to decide what a run answers; matching it
    to an interrupt is the provider's job."""
    agent = (await serve(EchoAgent(), "echo")).agents["echo"]
    adapter = AGUIAdapter(funduq)

    resumed = await adapter.run(
        agent,
        _body("t-root", "m1", resume=[ResumeEntry.model_validate(
            {"interruptId": "int_1", "status": "resolved", "payload": {"answer": 42}}
        )]),
    )
    [_ async for _ in resumed.events]

    run = await funduq.get_run(resumed.run_id)
    assert run.parent_run_id is None
    assert run.resume == [{"interruptId": "int_1", "status": "resolved", "payload": {"answer": 42}}]
