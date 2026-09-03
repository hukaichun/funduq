from __future__ import annotations

import asyncio

import pytest

from tests.conftest import publish_agents, publish_offline

from funduq import repo
from funduq.core import Funduq
from funduq.errors import NoPendingAsk, RunNotCancellable
from funduq.models import AgentRef
from funduq_contract import Registration


class EchoProvider:

    async def run_stream(self, agent_id: str, run_input):
        text = run_input.messages[-1].content if run_input.messages else ""
        yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "TEXT_MESSAGE_START", "messageId": "m1", "role": "assistant"}
        yield {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": f"echo: {text}"}
        yield {"type": "TEXT_MESSAGE_END", "messageId": "m1"}
        yield {"type": "RUN_FINISHED", "threadId": run_input.thread_id, "runId": run_input.run_id}


class PausingProvider:
    """Pauses its first round on a deferred call; any later round runs to its natural exit."""

    def __init__(self) -> None:
        self.rounds: list = []

    async def run_stream(self, agent_id: str, run_input):
        self.rounds.append(run_input)
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        if len(self.rounds) == 1:
            yield {
                "type": "RUN_FINISHED",
                **ids,
                "outcome": {
                    "type": "interrupt",
                    "interrupts": [{"id": "int_1", "reason": "question", "message": "which?"}],
                },
            }
        else:
            yield {"type": "RUN_FINISHED", **ids}


class NeverFinishesProvider:

    async def run_stream(self, agent_id: str, run_input):
        yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_input.run_id}
        await asyncio.Event().wait()


async def _register(funduq, name: str, identity) -> str:
    async with funduq.session() as session:
        registered = await repo.register_agents(session, identity.public_key, [Registration(name=name)])
    return registered[name]


async def _register_with_token(funduq, name: str, identity):
    return await publish_offline(funduq, identity, [Registration(name=name)])


async def _until(predicate, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


async def test_attach_start_and_read_back(funduq, new_identity, attach):
    identity = new_identity()
    agent_id = await _register(funduq, "echo", identity)
    await attach(identity, EchoProvider(), [agent_id.name])

    handle = await funduq.start_run(agent_id, {"messages": [{"role": "user", "content": "hi"}]})

    assert handle.run_id.startswith("run_")
    assert handle.thread_id.startswith("thread_")

    events = [event async for event in handle.events()]
    assert [e["type"] for e in events][0] == "RUN_STARTED"
    assert any(e.get("delta") == "echo: hi" for e in events)

    await _until(lambda: handle.run_id not in funduq.active_runs())

    run = await funduq.get_run(handle.run_id)
    assert run.status == "completed"

    messages = await funduq.get_thread_messages(handle.thread_id)
    assert messages[-1]["content"] == "echo: hi"

    assert len(await funduq.get_run_events(handle.run_id)) == len(events)


async def test_roster_and_agent_lookup(funduq, new_identity, attach):
    identity = new_identity()
    agent_id = await _register(funduq, "echo", identity)

    roster = await funduq.list_agents()
    assert [a.name for a in roster] == ["echo"]
    assert roster[0].online is False

    await attach(identity, EchoProvider(), ["echo"])
    assert (await funduq.list_agents())[0].online is True

    assert (await funduq.get_agent(agent_id)).name == "echo"
    assert await funduq.get_agent(AgentRef(provider_key=agent_id.provider_key, name="nope")) is None


async def test_cancel_a_running_agent(funduq, new_identity, attach):
    identity = new_identity()
    agent_id = await _register(funduq, "slow", identity)
    await attach(identity, NeverFinishesProvider(), [agent_id.name])

    handle = await funduq.start_run(agent_id, {"messages": []})
    stream = handle.events()
    assert (await anext(stream))["type"] == "RUN_STARTED"

    assert await funduq.cancel_run(handle.run_id) is True
    assert [e async for e in stream] == []
    await _until(lambda: handle.run_id not in funduq.active_runs())

    run = await funduq.get_run(handle.run_id)
    assert run.status == "cancelled"

    assert await funduq.cancel_run(handle.run_id) is False


class StubbornProvider:

    def __init__(self, identity) -> None:
        self.public_key = identity.public_key
        self.sign_connect = identity.sign_connect
        self.max_concurrent_runs = None
        self.taken: list[str] = []
        self.asked_to_stop: list[str] = []

    async def deliver(self, run) -> None:
        self.taken.append(run.run_id)
        self.funduq.answer_offer(run.run_id, True, provider_key=self.public_key)

    async def cancel(self, run_id: str) -> bool:
        self.asked_to_stop.append(run_id)
        return True

    def takes_interjections(self, agent_name: str) -> bool:
        return False
async def test_a_worker_that_ignores_the_cancel_still_completes(funduq, new_identity):
    identity = new_identity()
    registration = await _register_with_token(funduq, "stubborn", identity)
    agent_id = registration["stubborn"]
    provider = StubbornProvider(identity)
    provider.funduq = funduq
    await publish_agents(funduq, provider, ["stubborn"])

    handle = await funduq.start_run(agent_id, {"messages": []})
    await _until(lambda: provider.taken == [handle.run_id])

    await funduq.cancel_run(handle.run_id)
    assert funduq.broker.get(handle.run_id).cancel_requested is True
    await _until(lambda: provider.asked_to_stop == [handle.run_id])
    funduq.report_event(
        handle.run_id,
        {"type": "RUN_FINISHED", "threadId": handle.thread_id, "runId": handle.run_id},
        claimed_by=identity.public_key,
    )
    funduq.finish_run(handle.run_id, claimed_by=identity.public_key)

    events = [e async for e in handle.events()]
    await _until(lambda: handle.run_id not in funduq.active_runs())

    assert events[-1]["type"] == "RUN_FINISHED"
    assert (await funduq.get_run(handle.run_id)).status == "completed"


async def test_a_cancel_before_any_provider_takes_the_run(funduq, new_identity, attach):
    """A queued run nobody has claimed is cancelled outright: no provider holds it, so there is
    no outcome funduq could be pre-empting.

    Getting a run into that state means having a provider that declines —
    an agent nobody serves does not queue at any entrance, it fails at the
    door with `agent_offline`.
    """
    identity = new_identity()
    agent_id = await _register(funduq, "never-claimed", identity)
    await attach(
        identity, NeverFinishesProvider(), [agent_id.name],
        max_queued_runs=1, max_concurrent_runs=1,
    )

    busy = await funduq.start_run(agent_id, {"messages": []})
    await _until(lambda: busy.run_id in funduq.active_runs())
    handle = await funduq.start_run(agent_id, {"messages": []})
    assert (await funduq.get_run(handle.run_id)).status == "queued"

    assert await funduq.cancel_run(handle.run_id) is True
    await _until(lambda: handle.run_id not in funduq.active_runs())

    cancelled = await funduq.get_run(handle.run_id)
    assert cancelled.status == "cancelled"
    # What makes this the queued path rather than the claimed one: no
    # provider ever started it, so there was no outcome to pre-empt. Without
    # this the assertion above passes either way — a claimed run whose
    # stream is cancelled also settles `cancelled`.
    assert cancelled.started_at is None


async def test_thread_lineage(funduq, new_identity):
    identity = new_identity()
    parent_agent = await _register(funduq, "parent", identity)
    child_agent = await _register(funduq, "child", identity)

    root = await funduq.create_thread(parent_agent)
    async with funduq.session() as session:
        child = await repo.create_thread(session, child_agent, parent_thread_id=root)
        grandchild = await repo.create_thread(session, child_agent, parent_thread_id=child)
        await session.commit()

    tree = await funduq.get_thread_tree(root)
    assert tree["thread_id"] == root
    assert tree["children"][0]["thread_id"] == child
    assert tree["children"][0]["children"][0]["thread_id"] == grandchild

    assert await funduq.get_thread_tree("thread_nope") is None


async def test_start_run_reuses_an_existing_thread(funduq, new_identity, attach):
    identity = new_identity()
    agent_id = await _register(funduq, "echo", identity)
    await attach(identity, EchoProvider(), [agent_id.name])

    thread_id = await funduq.create_thread(agent_id)
    first = await funduq.start_run(agent_id, {"messages": []}, thread_id=thread_id)
    assert first.thread_id == thread_id
    [_ async for _ in first.events()]

    thread = await funduq.get_thread(thread_id)
    assert AgentRef(provider_key=thread["provider_key"], name=thread["agent_name"]) == agent_id


async def test_a_deferred_calls_result_returns_to_the_run_it_suspended(
    funduq, new_identity, attach
):
    """A deferred call pauses a run; it does not end one. The result goes back into that same
    run — same id, and the event log continues rather than starting over — because the run is
    the agent's loop up to its natural exit, and this loop has not reached it yet.

    The provider's own stream *did* end at the pause, which is the gap
    funduq holds the identity across: the agent is invoked again, told which
    run it is continuing.
    """
    identity = new_identity()
    agent_id = await _register(funduq, "asker", identity)
    provider = PausingProvider()
    await attach(identity, provider, [agent_id.name])

    handle = await funduq.start_run(agent_id, {"messages": [{"role": "user", "content": "one"}]})
    first_round = [e async for e in handle.events()]
    await _until(lambda: handle.run_id not in funduq.active_runs())
    assert (await funduq.get_run(handle.run_id)).status == "input-required"

    resumed = await funduq.resume_run(
        handle.run_id,
        {
            "messages": [{"role": "user", "content": "two"}],
            "resume": [{"interruptId": "int_1", "status": "resolved", "payload": {"answer": 42}}],
        },
    )
    assert resumed.run_id == handle.run_id
    second_round = [e async for e in resumed.events()]
    await _until(lambda: handle.run_id not in funduq.active_runs())

    assert len(await funduq.get_run_events(handle.run_id)) == len(first_round) + len(second_round)
    assert (await funduq.get_run(handle.run_id)).status == "completed"
    assert [r.run_id for r in provider.rounds] == [handle.run_id, handle.run_id]


async def test_a_result_offered_to_a_run_that_already_exited_is_refused(
    funduq, new_identity, attach
):
    """A run that reached its natural exit has no suspension to return to. Running it again
    would put a second loop under the first one's id — which is a new run, not a resume, and
    the caller is told so instead of getting the fork silently."""
    identity = new_identity()
    agent_id = await _register(funduq, "echo", identity)
    await attach(identity, EchoProvider(), [agent_id.name])

    handle = await funduq.start_run(agent_id, {"messages": [{"role": "user", "content": "one"}]})
    [_ async for _ in handle.events()]
    await _until(lambda: handle.run_id not in funduq.active_runs())
    assert (await funduq.get_run(handle.run_id)).status == "completed"
    settled = await funduq.get_run_events(handle.run_id)

    with pytest.raises(NoPendingAsk):
        await funduq.resume_run(
            handle.run_id, {"messages": [{"role": "user", "content": "two"}]}
        )

    assert await funduq.get_run_events(handle.run_id) == settled, "nothing was appended"
    assert (await funduq.get_run(handle.run_id)).status == "completed", "and it stays exited"


async def test_resume_an_unknown_run_is_an_error(funduq):
    with pytest.raises(LookupError):
        await funduq.resume_run("run_nope", {"messages": []})


@pytest.fixture
async def own_funduq(settings):
    instance = Funduq(settings)
    try:
        yield instance
    finally:
        await instance.aclose()


async def test_start_reconciles_what_the_last_process_left_behind(own_funduq, new_identity):
    agent_id = await _register(own_funduq, "echo", new_identity())
    async with own_funduq.session() as session:
        thread_id = await repo.create_thread(session, agent_id)
        stale = (await repo.create_run(session, thread_id, agent_id, "ag-ui", {"messages": []}))["run_id"]
        await session.commit()

    orphaned = await own_funduq.start()

    assert orphaned == [stale]
    assert (await own_funduq.get_run(stale)).status == "failed"


async def test_start_runs_once_so_a_second_call_cannot_reap_live_work(own_funduq, new_identity):
    agent_id = await _register(own_funduq, "echo", new_identity())
    await own_funduq.start()

    async with own_funduq.session() as session:
        thread_id = await repo.create_thread(session, agent_id)
        fresh = (await repo.create_run(session, thread_id, agent_id, "ag-ui", {"messages": []}))["run_id"]
        await session.commit()

    assert await own_funduq.start() == []
    assert (await own_funduq.get_run(fresh)).status == "queued"


async def test_start_runs_no_clock_of_its_own(own_funduq):
    """`start()` used to spawn a `health-sweeps` loop, and its only job was
    failing `input-required` runs past `paused_timeout_seconds`. That deadline
    was removed — a question funduq did not ask is not funduq's to time out —
    and the loop went with it, so funduq now starts dispatch and nothing else.

    The broker's own `broker-sweep` stays, and it is a different kind of
    thing: its two clocks watch *providers* (accepted-but-undelivered, agent
    gone unserved) and both only say what they observed into the run's own
    lane. Neither settles a run, and neither reads a clock on an answer a
    caller owes.

    Asserted rather than deleted: a loop that reads a clock and settles runs
    is exactly the kind of thing that comes back by accident, and it would
    come back invisible, because nothing else in the suite looks at `_tasks`.
    """
    await own_funduq.start()
    await own_funduq.start()

    assert [t.get_name() for t in own_funduq._tasks if not t.done()] == ["broker-sweep"]
    assert own_funduq.broker.is_running

    await own_funduq.aclose()
    assert not own_funduq.broker.is_running


async def test_aclose_without_start_is_fine(own_funduq):
    assert not [t for t in own_funduq._tasks if not t.done()]


async def test_an_exited_chained_run_is_told_it_exited_not_that_it_signed_wrong(
    funduq, new_identity, attach
):
    """The order of the two refusals matters. A run bound to a responsibility chain will only
    accept a result carrying a signature from one of its authorities — but that check belongs
    to a run that is *asking*. A run that already exited is not asking, and answering the
    wrong question first ("your signature is invalid") sends the caller to fix a signature
    when what happened is that there was nothing left to sign for.

    Both guards are real: this one is the ordinary case, and the
    status-guarded reopen behind it is the concurrent one, where two results
    race for the same pending ask and exactly one wins.
    """
    from sqlalchemy import update

    from funduq.identity import InvalidResolution
    from funduq.schema import runs

    identity = new_identity()
    agent_id = await _register(funduq, "chained", identity)
    await attach(identity, EchoProvider(), [agent_id.name])

    handle = await funduq.start_run(agent_id, {"messages": [{"role": "user", "content": "one"}]})
    [_ async for _ in handle.events()]
    await _until(lambda: handle.run_id not in funduq.active_runs())

    async with funduq.session() as session:
        await session.execute(
            update(runs).where(runs.c.run_id == handle.run_id).values(head_key="a" * 64)
        )
        await session.commit()

    with pytest.raises(NoPendingAsk):
        await funduq.resume_run(handle.run_id, {"messages": []})

    # ...and specifically not the signature complaint the chain check would
    # have made had it run first.
    assert not issubclass(NoPendingAsk, InvalidResolution)


async def test_cancelling_a_paused_run_is_refused_rather_than_answered_false(
    funduq, new_identity, attach
):
    """`cancel_run`'s False means "funduq is no longer tracking it — it has
    already ended, and there is nobody left to ask". A paused run is not
    that: it is still waiting, and it was answering False because the broker
    forgets a run at the end of its stream and a pause *is* the end of the
    provider's stream.

    So the caller asking to stop a run got back the word for "too late" about
    a run that had not finished, and no way to tell the two apart. Cancelling
    means relaying the request to whoever is working on the run, and here
    nobody is — that is the fact to state.

    Refusing settles nothing: the ask is still there afterwards and still
    resumable, because a cancel funduq could not relay must not become an
    outcome funduq never observed.
    """
    identity = new_identity()
    agent_id = await _register(funduq, "asker", identity)
    provider = PausingProvider()
    await attach(identity, provider, [agent_id.name])

    handle = await funduq.start_run(agent_id, {"messages": [{"role": "user", "content": "one"}]})
    [_ async for _ in handle.events()]
    await _until(lambda: handle.run_id not in funduq.active_runs())
    assert (await funduq.get_run(handle.run_id)).status == "input-required"
    settled = await funduq.get_run_events(handle.run_id)

    with pytest.raises(RunNotCancellable):
        await funduq.cancel_run(handle.run_id)

    assert (await funduq.get_run(handle.run_id)).status == "input-required"
    assert await funduq.get_run_events(handle.run_id) == settled, "nothing was appended"

    resumed = await funduq.resume_run(
        handle.run_id,
        {
            "messages": [{"role": "user", "content": "two"}],
            "resume": [{"interruptId": "int_1", "status": "resolved", "payload": {"answer": 42}}],
        },
    )
    [_ async for _ in resumed.events()]
    await _until(lambda: handle.run_id not in funduq.active_runs())
    assert (await funduq.get_run(handle.run_id)).status == "completed"


async def test_a_run_that_really_has_ended_still_answers_false(funduq, new_identity, attach):
    """The other side of the same line. A finished run has nobody to ask
    *because it is over*, and False is the honest answer there — the refusal
    above is for the state that is neither working nor over, not a general
    hardening of `cancel_run`."""
    identity = new_identity()
    agent_id = await _register(funduq, "echo", identity)
    await attach(identity, EchoProvider(), [agent_id.name])

    handle = await funduq.start_run(agent_id, {"messages": [{"role": "user", "content": "one"}]})
    [_ async for _ in handle.events()]
    await _until(lambda: handle.run_id not in funduq.active_runs())
    assert (await funduq.get_run(handle.run_id)).status == "completed"

    assert await funduq.cancel_run(handle.run_id) is False
