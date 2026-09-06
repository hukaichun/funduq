from __future__ import annotations

import json

from funduq import repo
from funduq.pause import interrupts_of, open_asks, unanswered_tool_calls
from funduq.broker import FinishStream, RelayEvent, Run
from funduq.handlers import _handle_finish, _handle_relay
from funduq_contract import Registration


async def test_native_ag_ui_interrupt_outcome_pauses_a_run(session, funduq, new_identity):
    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="b")])
    agent_b = registered["b"]
    thread_b = await repo.create_thread(session, agent_b)
    created = await repo.create_run(session, thread_b, agent_b, {})
    await session.commit()
    await repo.mark_run_status(session, created["run_id"], "running")
    run_id = created["run_id"]
    await session.commit()

    # These exercise the handlers directly, not dispatch: a bare `Run` is
    # what they need, and going through the broker would give the run a lane
    # that races them for its own queue.
    run = Run(
        run_id=run_id, agent=agent_b, thread_id=thread_b, input_json={}
    )
    interrupt = {"id": "int_1", "reason": "tool_call", "message": "Approve foo(1)?"}
    finished_event = {
        "type": "RUN_FINISHED",
        "threadId": thread_b,
        "runId": run_id,
        "outcome": {"type": "interrupt", "interrupts": [interrupt]},
    }
    await _handle_relay(funduq, run, RelayEvent(finished_event))
    await _handle_finish(funduq, run, FinishStream())

    reread = await repo.get_run(session, run_id)
    events = await repo.get_run_events(session, run_id)
    assert reread.status == "completed", "finished asking is finished — AG-UI's own reading"
    assert interrupts_of(events) == [interrupt]
    assert open_asks(events) == {"int_1"}, "and the thread is waiting on it, read from the events"


async def test_native_ag_ui_success_outcome_completes_a_run_normally(session, funduq, new_identity):
    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="b")])
    agent_b = registered["b"]
    thread_b = await repo.create_thread(session, agent_b)
    created = await repo.create_run(session, thread_b, agent_b, {})
    await session.commit()
    await repo.mark_run_status(session, created["run_id"], "running")
    run_id = created["run_id"]
    await session.commit()

    # These exercise the handlers directly, not dispatch: a bare `Run` is
    # what they need, and going through the broker would give the run a lane
    # that races them for its own queue.
    run = Run(
        run_id=run_id, agent=agent_b, thread_id=thread_b, input_json={}
    )
    finished_event = {"type": "RUN_FINISHED", "threadId": thread_b, "runId": run_id}
    await _handle_relay(funduq, run, RelayEvent(finished_event))
    await _handle_finish(funduq, run, FinishStream())

    reread = await repo.get_run(session, run_id)
    assert reread.status == "completed"


async def test_a_run_that_finished_asking_is_not_active_on_its_thread(session, new_identity):
    """Nobody is working on it — the provider ended its stream — so it is not the thread's active run. That the thread is waiting is a fact about the latest run's events, not a status that keeps it in flight."""
    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="c")])
    agent_c = registered["c"]
    thread_c = await repo.create_thread(session, agent_c)
    run_c = await repo.create_run(session, thread_c, agent_c, {})
    await session.commit()
    await repo.mark_run_status(session, run_c["run_id"], "running")
    await repo.append_run_event(session, run_c["run_id"], 1, {"type": "RUN_STARTED"})
    await repo.append_run_event(
        session, run_c["run_id"], 2,
        {"type": "RUN_FINISHED", "outcome": {"type": "interrupt", "interrupts": [{"id": "int_1", "reason": "hitl_approval"}]}},
    )
    await repo.mark_run_status(session, run_c["run_id"], "completed")

    assert await repo.get_active_run_for_thread(session, thread_c) is None
    latest = await repo.latest_run_for_thread(session, thread_c)
    assert latest.run_id == run_c["run_id"]
    assert open_asks(await repo.get_run_events(session, latest.run_id)) == {"int_1"}


async def test_a_result_with_no_pending_ask_is_refused_not_smuggled(funduq, serve):
    """The door has two entrances: an utterance, or a deferred call's result.
    A resume payload is a result; with nothing paused on the thread there is
    no ask for it to land on, and it must be refused with the thread's state
    — never quietly repackaged as a fresh run carrying an answer the agent
    never asked for."""
    from ag_ui.core import RunAgentInput, UserMessage
    from ag_ui.core.types import ResumeEntry

    from funduq.protocols.agui import AGUIAdapter, ThreadSnapshot
    from tests.conftest import EchoAgent

    served = await serve(EchoAgent(), "grounded")
    agent = served.agents["grounded"]
    adapter = AGUIAdapter(funduq)

    first = await adapter.run(
        agent,
        RunAgentInput(
            thread_id="t-fresh", run_id="ignored", state={},
            messages=[UserMessage(id="m1", role="user", content="hi")],
            tools=[], context=[], forwarded_props={},
        ),
    )
    [event async for event in first.events]

    ghost = await adapter.run(
        agent,
        RunAgentInput(
            thread_id=first.thread_id, run_id="ignored", state={},
            messages=[UserMessage(id="m2", role="user", content="the answer")],
            tools=[], context=[], forwarded_props={},
            resume=[ResumeEntry.model_validate(
                {"interruptId": "int_ghost", "status": "resolved", "payload": {"answer": 42}}
            )],
        ),
    )
    assert isinstance(ghost, ThreadSnapshot), "a result with no ask gets the thread's state back"


async def test_an_unanswered_tool_call_pauses_a_run_that_reported_success(
    session, funduq, new_identity
):
    """AG-UI's `outcome` names an approval and nothing else. A call the provider
    deferred for someone else to run ends the stream as `success`, so this is
    the shape of a paused run that never says it paused."""
    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="b")])
    agent_b = registered["b"]
    thread_b = await repo.create_thread(session, agent_b)
    created = await repo.create_run(session, thread_b, agent_b, {})
    await session.commit()
    await repo.mark_run_status(session, created["run_id"], "running")
    run_id = created["run_id"]
    await session.commit()

    run = Run(
        run_id=run_id, agent=agent_b, thread_id=thread_b, input_json={}
    )
    for event in (
        {"type": "TOOL_CALL_START", "toolCallId": "c1", "toolCallName": "get_weather"},
        {"type": "TOOL_CALL_ARGS", "toolCallId": "c1", "delta": '{"city": "Taipei"}'},
        {"type": "TOOL_CALL_END", "toolCallId": "c1"},
        {"type": "TOOL_CALL_START", "toolCallId": "c2", "toolCallName": "book_flight"},
        {"type": "TOOL_CALL_ARGS", "toolCallId": "c2", "delta": '{"to": "Tokyo"}'},
        {"type": "TOOL_CALL_END", "toolCallId": "c2"},
        {"type": "TOOL_CALL_RESULT", "messageId": "m1", "toolCallId": "c1",
         "content": "Taipei: 28C", "role": "tool"},
        {"type": "RUN_FINISHED", "threadId": thread_b, "runId": run_id,
         "outcome": {"type": "success"}},
    ):
        await _handle_relay(funduq, run, RelayEvent(event))
    await _handle_finish(funduq, run, FinishStream())

    reread = await repo.get_run(session, run_id)
    events = await repo.get_run_events(session, run_id)
    assert reread.status == "completed"
    assert unanswered_tool_calls(events) == ["c2"]
    assert interrupts_of(events) == []
    assert open_asks(events) == {"c2"}


async def test_a_run_whose_every_tool_call_was_answered_still_completes(
    session, funduq, new_identity
):
    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="b")])
    agent_b = registered["b"]
    thread_b = await repo.create_thread(session, agent_b)
    created = await repo.create_run(session, thread_b, agent_b, {})
    await session.commit()
    await repo.mark_run_status(session, created["run_id"], "running")
    run_id = created["run_id"]
    await session.commit()

    run = Run(
        run_id=run_id, agent=agent_b, thread_id=thread_b, input_json={}
    )
    for event in (
        {"type": "TOOL_CALL_START", "toolCallId": "c1", "toolCallName": "get_weather"},
        {"type": "TOOL_CALL_END", "toolCallId": "c1"},
        {"type": "TOOL_CALL_RESULT", "messageId": "m1", "toolCallId": "c1",
         "content": "Taipei: 28C", "role": "tool"},
        {"type": "RUN_FINISHED", "threadId": thread_b, "runId": run_id,
         "outcome": {"type": "success"}},
    ):
        await _handle_relay(funduq, run, RelayEvent(event))
    await _handle_finish(funduq, run, FinishStream())

    reread = await repo.get_run(session, run_id)
    assert reread.status == "completed"


async def test_an_interrupt_and_an_unanswered_call_are_recorded_in_one_pause(
    session, funduq, new_identity
):
    """One turn can ask both ways at once — pydantic-ai returns `approvals` and
    `calls` as separate lists of the same `DeferredToolRequests`."""
    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="b")])
    agent_b = registered["b"]
    thread_b = await repo.create_thread(session, agent_b)
    created = await repo.create_run(session, thread_b, agent_b, {})
    await session.commit()
    await repo.mark_run_status(session, created["run_id"], "running")
    run_id = created["run_id"]
    await session.commit()

    run = Run(
        run_id=run_id, agent=agent_b, thread_id=thread_b, input_json={}
    )
    interrupt = {"id": "int-c3", "reason": "tool_call", "toolCallId": "c3",
                 "message": "Approve send_money(500)?"}
    for event in (
        {"type": "TOOL_CALL_START", "toolCallId": "c2", "toolCallName": "book_flight"},
        {"type": "TOOL_CALL_END", "toolCallId": "c2"},
        {"type": "TOOL_CALL_START", "toolCallId": "c3", "toolCallName": "send_money"},
        {"type": "TOOL_CALL_END", "toolCallId": "c3"},
        {"type": "RUN_FINISHED", "threadId": thread_b, "runId": run_id,
         "outcome": {"type": "interrupt", "interrupts": [interrupt]}},
    ):
        await _handle_relay(funduq, run, RelayEvent(event))
    await _handle_finish(funduq, run, FinishStream())

    reread = await repo.get_run(session, run_id)
    events = await repo.get_run_events(session, run_id)
    assert reread.status == "completed", "finished asking is finished — AG-UI's own reading"
    assert interrupts_of(events) == [interrupt]
    assert unanswered_tool_calls(events) == ["c2", "c3"]
    assert open_asks(events) == {"c2", "c3"}, "one pause, everything it left open — the interrupt by the tool call it is about"
