from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from funduq import repo
from funduq.core import Funduq
from funduq.schema import runs
from funduq_contract import Registration


async def _make_paused_run(session, agent, thread_id, seconds_stale: int) -> str:
    created = await repo.create_run(session, thread_id, agent, "ag-ui", {"messages": []})
    await session.commit()
    run_id = created["run_id"]
    # The legal road to a pause: a run is claimed (running) before it can ask.
    await repo.mark_run_status(session, run_id, "running")
    await repo.mark_run_status(session, run_id, "input-required", metadata={"interrupts": []})
    await session.execute(
        update(runs)
        .where(runs.c.run_id == run_id)
        .values(last_activity_at=datetime.now(timezone.utc) - timedelta(seconds=seconds_stale))
    )
    await session.commit()
    return run_id


async def test_a_pause_has_no_deadline_of_funduqs(session, funduq, new_identity):
    """A question funduq did not ask is not funduq's to time out.

    There used to be a `paused_timeout_seconds` sweep that failed an
    `input-required` run once it had waited long enough, and it was off by
    default — so the shipped behaviour was already this, reached by leaving a
    setting unset rather than by deciding anything. The deadline on an ask
    belongs to the two parties who have one: the provider that asked (AG-UI
    lets it declare `Interrupt.expires_at`) and the caller that owes the
    answer. funduq holds the record open for them and reads no clock.

    So a pause stale by any amount is still a pause, and still resumable. It
    is not a leak into the thread's buffer either: `count_queued_runs_for_thread`
    counts only runs no provider has accepted, and this one was accepted and
    handed back.
    """
    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="translator")])
    agent = registered["translator"]
    thread_id = await repo.create_thread(session, agent)

    run_id = await _make_paused_run(session, agent, thread_id, seconds_stale=10**6)

    assert (await repo.get_run(session, run_id)).status == "input-required"
    assert await repo.count_queued_runs_for_thread(session, thread_id) == 0

    # And nothing funduq starts changes that: `start()` reaps orphans, and a
    # pause is deliberately not one — it survives the restart it is waiting
    # across.
    reborn = Funduq(funduq.settings)
    try:
        assert run_id not in await reborn.start()
    finally:
        await reborn.aclose()

    assert (await repo.get_run(session, run_id)).status == "input-required"
    assert await repo.claim_ask(session, run_id)


async def test_a_run_the_broker_has_forgotten_still_gets_its_terminal_event(
    session, funduq, new_identity
):
    """The broker forgets a run when its stream ends, so a run failed after
    that has no lane and no subscriber left — but the record still owes the
    verdict, and the event stream has to end the way the database says the run
    did. Reached today by `start()` reaping orphans; it used to be reached by
    the pause sweep as well, which is gone."""
    from funduq.handlers import close_with_terminal_event

    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="reaped")])
    agent = registered["reaped"]
    thread_id = await repo.create_thread(session, agent)
    run_id = await _make_paused_run(session, agent, thread_id, seconds_stale=120)
    await repo.append_run_event(
        session, run_id, 1, {"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id}
    )

    await repo.mark_run_status(session, run_id, "failed", metadata={"failureReason": "x"})
    await close_with_terminal_event(funduq, run_id, "x")

    events = await repo.get_run_events(session, run_id)
    assert events[-1] == {"type": "RUN_ERROR", "message": "x"}, (
        "the event stream must end the way the database says the run did"
    )


async def test_a_run_that_reported_its_own_error_is_left_alone(session, funduq, new_identity):
    from funduq.handlers import close_with_terminal_event

    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="spoke")])
    agent = registered["spoke"]
    thread_id = await repo.create_thread(session, agent)
    created = await repo.create_run(session, thread_id, agent, "ag-ui", {})
    await session.commit()
    run_id = created["run_id"]
    await repo.append_run_event(session, run_id, 1, {"type": "RUN_ERROR", "message": "my own"})
    await repo.mark_run_status(session, run_id, "failed", metadata={"failureReason": "x"})

    await close_with_terminal_event(funduq, run_id, "x")

    events = await repo.get_run_events(session, run_id)
    assert [e["message"] for e in events if e["type"] == "RUN_ERROR"] == ["my own"]


async def test_orphans_reaped_at_start_get_terminal_events(settings, session, new_identity):
    from funduq.core import Funduq

    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="orphan")])
    agent = registered["orphan"]
    thread_id = await repo.create_thread(session, agent)
    created = await repo.create_run(session, thread_id, agent, "ag-ui", {})
    await session.commit()
    run_id = created["run_id"]
    # Held by the previous process: only a run somebody had in hand is an orphan.
    await repo.mark_run_status(session, run_id, "running")

    reborn = Funduq(settings)
    try:
        orphaned = await reborn.start()
        assert run_id in orphaned
        async with reborn.session() as s:
            events = await repo.get_run_events(s, run_id)
            stored = await repo.get_run(s, run_id)
        assert stored.status == "failed"
        assert events[-1] == {"type": "RUN_ERROR", "message": "orphaned_by_funduq_restart"}
    finally:
        await reborn.aclose()
