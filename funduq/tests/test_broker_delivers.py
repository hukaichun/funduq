from __future__ import annotations

import asyncio
import logging

import pytest

from funduq.broker import Claim, Fail, RequestCancel, RunBroker
from funduq.models import AgentRef

def _valid_input(run_id: str, thread_id: str) -> dict:
    """The smallest dict that validates as a `RunAgentInput`: the broker now
    builds the published `DeliveredRun` itself, so a test input must be one."""
    return {
        "threadId": thread_id,
        "runId": run_id,
        "state": None,
        "messages": [],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }


AGENT = AgentRef(provider_key="pk_provider", name="translator")
OTHER = AgentRef(provider_key="pk_provider", name="summarizer")


async def _until(predicate, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


class Recording:

    def __init__(
        self,
        key: str = "pk_provider",
        *,
        max_concurrent_runs: int | None = None,
        answers: list[bool] | None = None,
        default: bool = True,
        hang: bool = False,
        hold: asyncio.Event | None = None,
    ) -> None:
        self.public_key = key
        self.max_concurrent_runs = max_concurrent_runs
        self._answers = list(answers or [])
        self._default = default
        self._hang = hang
        # An offer this provider has in its hands and has not answered yet —
        # the window every in-process test provider otherwise closes instantly,
        # and the one a networked provider is always inside.
        self._hold = hold
        self.offered: list[str] = []
        self.cancelled: list[str] = []

    async def deliver(self, run) -> bool:
        self.offered.append(run.run_id)
        if self._hang:
            await asyncio.Event().wait()
        if self._hold is not None:
            await self._hold.wait()
        return self._answers.pop(0) if self._answers else self._default

    async def cancel(self, run_id: str) -> bool:
        self.cancelled.append(run_id)
        return True
@pytest.fixture
async def broker():
    b = RunBroker(deliver_timeout_seconds=0.05, unserved_timeout_seconds=30)
    b.start()
    try:
        yield b
    finally:
        b.stop()


@pytest.fixture
async def patient_broker():
    """A broker that will wait for an answer. The tests about the dispatch
    window hold an offer open on purpose, and the default fixture's 0.05s
    delivery timeout would call that silence a timeout instead."""
    b = RunBroker(deliver_timeout_seconds=5.0, unserved_timeout_seconds=30)
    b.start()
    try:
        yield b
    finally:
        b.stop()


def _enqueue(broker: RunBroker, run_id: str, agent: AgentRef = AGENT, thread_id: str | None = None):
    # Each run gets its own thread unless a test names one: a thread is the
    # unit funduq hands over serially, and most of these tests are about
    # delivery and capacity rather than about a conversation's order.
    return broker.enqueue_run(run_id, agent, thread_id or f"thread_{run_id}", _valid_input(run_id, thread_id or f"thread_{run_id}"), "ag-ui", {}
    )


async def test_an_ack_starts_the_run_and_takes_a_place(broker):
    provider = Recording()
    broker.register_provider({AGENT: provider})
    _enqueue(broker, "run_1")

    await _until(lambda: provider.offered == ["run_1"])
    await _until(lambda: broker.get("run_1").claimed_by == "pk_provider")

    assert broker.quality()["pk_provider"].in_flight == 1


async def test_the_provider_is_handed_a_value_not_funduqes_dispatch_state(broker):
    handed: list = []

    class Inspecting(Recording):
        async def deliver(self, run) -> bool:
            handed.append(run)
            return await super().deliver(run)

    broker.register_provider({AGENT: Inspecting()})
    _enqueue(broker, "run_1")
    await _until(lambda: bool(handed))

    run = handed[0]
    assert (run.run_id, run.agent_name) == ("run_1", AGENT.name)
    assert (run.run_input.run_id, run.run_input.thread_id) == ("run_1", run.thread_id)
    assert not hasattr(run, "in_queue") and not hasattr(run, "out_queue")


async def test_a_run_is_delivered_exactly_once(broker):
    provider = Recording()
    broker.register_provider({AGENT: provider})
    for i in range(5):
        _enqueue(broker, f"run_{i}")

    await _until(lambda: len(provider.offered) >= 5)
    await asyncio.sleep(0.05)

    assert sorted(provider.offered) == [f"run_{i}" for i in range(5)]


async def test_a_decline_leaves_the_run_queued(broker):
    provider = Recording(answers=[False, False], default=False)
    broker.register_provider({AGENT: provider})
    _enqueue(broker, "run_1")

    await _until(lambda: bool(provider.offered))
    await asyncio.sleep(0.05)

    assert broker.get("run_1").claimed_by is None
    assert broker.quality()["pk_provider"].in_flight == 0


async def test_a_provider_past_its_abnormality_allowance_is_withdrawn():
    """funduq#128 settled generally: the quality counters ARE the allowance —
    they say how much abnormality any provider is permitted, and one that
    reaches it is withdrawn from service, the same judgment for every event
    type and every provider. The way back is the front door."""
    b = RunBroker(deliver_timeout_seconds=0.05, unserved_timeout_seconds=0.1,
                  quality_tolerance=2)
    b.start()
    try:
        provider = Recording(answers=[False, False], default=True)
        b.register_provider({AGENT: provider})
        _enqueue(b, "run_1")

        # Each decline-with-room spends allowance; at 2 of 2 the provider is out.
        await _until(lambda: b.serving(AGENT) is None, timeout=3.0)
        assert b.quality()["pk_provider"].misdeclared == 2
        offered_when_withdrawn = list(provider.offered)

        assert _enqueue(b, "run_2") is None, "withdrawn means not serving"
        await asyncio.sleep(0.2)
        assert provider.offered == offered_when_withdrawn, (
            "withdrawn means withdrawn — no more offers"
        )

        # The front door works: re-registering restores service.
        b.register_provider({AGENT: provider})
        await _until(lambda: b.get("run_1") is None or b.get("run_1").is_claimed, timeout=3.0)
    finally:
        b.stop()


async def test_below_the_allowance_an_abnormal_event_is_tolerated():
    """One discourtesy is counted, not ejected: the tolerance exists so a
    provider may be somewhat abnormal before funduq stops serving it."""
    b = RunBroker(deliver_timeout_seconds=0.05, unserved_timeout_seconds=0.1,
                  quality_tolerance=2)
    b.start()
    try:
        provider = Recording(answers=[False], default=True)
        b.register_provider({AGENT: provider})
        _enqueue(b, "run_1")
        await _until(lambda: provider.offered == ["run_1"])

        assert b.serving(AGENT) is provider, "one event is within the allowance"
        await _until(
            lambda: b.get("run_1") is not None and b.get("run_1").is_claimed, timeout=3.0
        )
        assert b.quality()["pk_provider"].misdeclared == 1
    finally:
        b.stop()


async def test_runs_of_a_withdrawn_provider_expire_on_the_ordinary_road():
    """With its provider withdrawn, the agent is simply unserved: queued runs
    travel the existing no-provider expiry road and fail loudly, instead of
    waiting on an abnormal provider's change of heart."""
    b = RunBroker(deliver_timeout_seconds=0.05, unserved_timeout_seconds=0.2,
                  quality_tolerance=1)
    b.start()
    try:
        provider = Recording(default=False)
        b.register_provider({AGENT: provider})
        failed: list = []

        async def _record_fail(run, cmd) -> None:
            failed.append((run.run_id, cmd.reason))

        b.enqueue_run("run_1", AGENT, "t1", _valid_input("run_1", "t1"), "ag-ui", {Fail: _record_fail})
        await _until(lambda: provider.offered == ["run_1"])
        await _until(lambda: failed == [("run_1", "no_provider_took_it")], timeout=2.0)
    finally:
        b.stop()


async def test_declining_while_funduq_believed_there_was_room_is_counted_not_believed(broker):
    """A provider has whatever room it said it has. The decline is recorded
    against it and the declaration is left alone — the in-flight number stays
    a count of what the provider is actually holding."""
    provider = Recording(max_concurrent_runs=2, default=False)
    broker.register_provider({AGENT: provider})
    _enqueue(broker, "run_1")

    await _until(lambda: bool(provider.offered))
    await _until(lambda: broker.quality()["pk_provider"].misdeclared == 1)

    quality = broker.quality()["pk_provider"]
    assert quality.declared == 2
    assert quality.in_flight == 0, "it is holding nothing, so that is what the count says"


async def test_one_decline_does_not_cost_a_provider_its_declared_room(broker):
    """funduq used to write its own conclusion into the count — `in_flight =
    declared`, "treating it as full". A count only knows how to be
    incremented and decremented, so the phantom places that injected never
    came back: a provider that declared room for five and declined once was
    capped at one, for good."""

    class DeclinesOnce(Recording):
        def __init__(self) -> None:
            super().__init__(max_concurrent_runs=5)
            self.declined = False
            self.holding: set[str] = set()

        async def deliver(self, run) -> bool:
            self.offered.append(run.run_id)
            if not self.declined:
                self.declined = True
                return False
            self.holding.add(run.run_id)
            return True

    provider = DeclinesOnce()
    broker.register_provider({AGENT: provider})
    for i in range(6):
        _enqueue(broker, f"run_{i}")
        await asyncio.sleep(0)

    await _until(lambda: len(provider.holding) == 5, timeout=2.0)
    assert broker.quality()["pk_provider"].in_flight == 5


async def test_a_provider_that_never_answers_is_not_waited_on_forever(broker):
    silent = Recording(key="pk_silent", hang=True)
    broker.register_provider({AGENT: silent})
    _enqueue(broker, "run_1")

    await _until(lambda: broker.quality()["pk_silent"].unanswered >= 1, timeout=2.0)
    assert broker.get("run_1").claimed_by is None

    working = Recording(key="pk_working")
    broker.register_provider({OTHER: working})
    _enqueue(broker, "run_2", OTHER)
    await _until(lambda: working.offered == ["run_2"], timeout=2.0)


async def test_a_full_provider_is_offered_nothing(broker):
    provider = Recording(max_concurrent_runs=1)
    broker.register_provider({AGENT: provider, OTHER: provider})
    _enqueue(broker, "run_1", AGENT)
    _enqueue(broker, "run_2", OTHER)

    await _until(lambda: len(provider.offered) == 1)
    await asyncio.sleep(0.05)

    assert len(provider.offered) == 1, "offered past a full provider's declared capacity"


async def test_the_place_comes_back_when_the_run_ends(broker):
    provider = Recording(max_concurrent_runs=1)
    broker.register_provider({AGENT: provider})
    _enqueue(broker, "run_1")
    _enqueue(broker, "run_2")
    await _until(lambda: provider.offered == ["run_1"])

    broker.forget("run_1")

    await _until(lambda: provider.offered == ["run_1", "run_2"])
    assert broker.quality()["pk_provider"].in_flight == 1


async def test_a_reconnecting_provider_keeps_its_bucket(broker):
    provider = Recording(max_concurrent_runs=1)
    broker.register_provider({AGENT: provider})
    _enqueue(broker, "run_1")
    await _until(lambda: broker.quality()["pk_provider"].in_flight == 1)

    broker.register_provider({AGENT: provider})

    assert broker.quality()["pk_provider"].in_flight == 1


async def test_missing_the_window_is_breakage_answered_by_a_fresh_offer(broker):
    """An acknowledgement is an intake decision; missing the window means the
    link or the provider is broken, not that it is thinking. funduq counts it,
    takes the run back, and offers it again — a provider that had actually
    taken the run and lost its answer sees the same run offered again and
    simply accepts again. There is no late-claim path."""

    class LostFirstAnswer(Recording):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def deliver(self, run) -> bool:
            self.calls += 1
            self.offered.append(run.run_id)
            if self.calls == 1:
                await asyncio.Event().wait()
            return True

    provider = LostFirstAnswer()
    # Its own broker: the retry rides the sweep, so the sweep must cycle fast.
    b = RunBroker(deliver_timeout_seconds=0.05, unserved_timeout_seconds=0.1)
    b.start()
    try:
        b.register_provider({AGENT: provider})
        b.enqueue_run("run_1", AGENT, "thread_run_1", _valid_input("run_1", "thread_run_1"), "ag-ui", {})
        await _until(lambda: b.quality()["pk_provider"].unanswered >= 1, timeout=2.0)
        assert b.get("run_1").claimed_by is None, "no answer, no claim"

        await _until(lambda: b.get("run_1").claimed_by == "pk_provider", timeout=2.0)
        assert provider.offered == ["run_1", "run_1"], "the same run, offered afresh"
        assert not hasattr(b, "accept_late_ack"), "the late-claim path is gone"
    finally:
        b.stop()


async def test_taking_a_run_and_never_ending_it_is_recorded(broker):
    provider = Recording()
    broker.register_provider({AGENT: provider})
    _enqueue(broker, "run_1")
    await _until(lambda: broker.get("run_1").claimed_by == "pk_provider")

    broker.push("run_1", Fail("stalled"))

    assert broker.quality()["pk_provider"].abandoned == 1


async def test_a_run_nobody_ever_takes_is_given_up_on(broker):
    """A run is only born with a provider online, so the way to be nobody's is
    to have your provider leave: here it is withdrawn while too full to have
    taken the run."""
    broker.register_provider({AGENT: Recording(max_concurrent_runs=0)})
    _enqueue(broker, "run_1")
    broker.unregister_provider([AGENT])

    expired = broker.expire_queued(timeout_seconds=0)

    assert expired == ["run_1"]
    await _until(lambda: broker.get("run_1") is None)


async def test_cancelling_a_delivered_run_keeps_the_provider_in_the_loop(broker):
    provider = Recording()
    broker.register_provider({AGENT: provider})
    _enqueue(broker, "run_1")
    await _until(lambda: broker.get("run_1").claimed_by == "pk_provider")

    assert broker.request_cancel("run_1") is True

    snapshot = broker.get("run_1")
    assert snapshot.cancel_requested is True
    assert snapshot.claimed_by == "pk_provider"


async def test_cancelling_a_queued_run_stops_it_ever_being_offered(broker):
    """Its provider has no room, so it is still funduq's when the cancel
    arrives — nobody to ask, so the cancel settles it, and it is never offered
    even once room appears."""
    full = Recording(max_concurrent_runs=0)
    broker.register_provider({AGENT: full})
    _enqueue(broker, "run_1")

    assert broker.request_cancel("run_1") is True
    await _until(lambda: broker.get("run_1") is None)

    roomy = Recording(key="pk_roomy")
    broker.register_provider({AGENT: roomy})
    await asyncio.sleep(0.05)

    assert full.offered == [] and roomy.offered == []


async def test_a_cancelled_run_does_not_block_the_one_behind_it(broker):
    """Same conversation, so run_2 really is behind run_1 — and a cancelled
    head must let go of its turn rather than hold the thread forever."""
    broker.register_provider({AGENT: Recording(max_concurrent_runs=0)})
    _enqueue(broker, "run_1", thread_id="one_chat")
    _enqueue(broker, "run_2", thread_id="one_chat")
    broker.request_cancel("run_1")
    await _until(lambda: broker.get("run_1") is None)

    provider = Recording(key="pk_roomy")
    broker.register_provider({AGENT: provider})

    await _until(lambda: provider.offered == ["run_2"])


async def test_the_place_comes_back_when_a_delivered_run_is_cancelled(broker):
    provider = Recording(max_concurrent_runs=1)
    broker.register_provider({AGENT: provider})
    _enqueue(broker, "run_1")
    _enqueue(broker, "run_2")
    await _until(lambda: provider.offered == ["run_1"])

    broker.request_cancel("run_1")
    broker.push("run_1", Fail("cancelled"))
    broker.forget("run_1")

    await _until(lambda: provider.offered == ["run_1", "run_2"])


def test_a_broker_can_be_built_outside_a_loop_and_started_in_two(caplog):
    broker = RunBroker(deliver_timeout_seconds=0.05)

    async def place_one(run_id: str) -> list[str]:
        provider = Recording()
        broker.start()
        try:
            broker.register_provider({AGENT: provider})
            _enqueue(broker, run_id)
            await _until(lambda: provider.offered == [run_id])
            await asyncio.sleep(0.05)
            return provider.offered
        finally:
            broker.forget(run_id)
            broker.stop()

    with caplog.at_level(logging.ERROR, logger="funduq.broker"):
        assert asyncio.run(place_one("run_1")) == ["run_1"]
        assert asyncio.run(place_one("run_2")) == ["run_2"]

    assert [r.getMessage() for r in caplog.records] == []


async def test_a_queued_run_waits_as_long_as_its_agent_is_served():
    b = RunBroker(deliver_timeout_seconds=0.02, unserved_timeout_seconds=0.05)
    b.start()
    try:
        b.register_provider({AGENT: Recording(max_concurrent_runs=1, default=False)})
        _enqueue(b, "run_1")
        await asyncio.sleep(0.25)
        run = b.get("run_1")
        assert run is not None and run.claimed_by is None
    finally:
        b.stop()


async def test_losing_the_provider_starts_the_clock_that_fails_the_run():
    b = RunBroker(deliver_timeout_seconds=0.02, unserved_timeout_seconds=0.05)
    b.start()
    try:
        b.register_provider({AGENT: Recording(max_concurrent_runs=1, default=False)})
        _enqueue(b, "run_1")
        await asyncio.sleep(0.25)
        assert b.get("run_1") is not None

        b.unregister_provider([AGENT])
        await _until(lambda: b.get("run_1") is None, timeout=2.0)
    finally:
        b.stop()


async def test_a_provider_returning_within_the_window_keeps_the_run():
    b = RunBroker(deliver_timeout_seconds=0.02, unserved_timeout_seconds=0.3)
    b.start()
    try:
        b.register_provider({AGENT: Recording(max_concurrent_runs=1, default=False)})
        _enqueue(b, "run_1")
        b.unregister_provider([AGENT])
        await asyncio.sleep(0.05)
        b.register_provider({AGENT: Recording(max_concurrent_runs=1, default=False)})
        await asyncio.sleep(0.6)
        assert b.get("run_1") is not None
    finally:
        b.stop()


async def test_a_threads_next_run_waits_for_the_turn_to_finish(broker):
    """One thread, one active run: the second utterance is not offered while
    the first is claimed and running — it goes out when the turn ends."""
    from funduq.broker import FinishStream

    provider = Recording()
    broker.register_provider({AGENT: provider})
    _enqueue(broker, "run_1", thread_id="thread_shared")
    _enqueue(broker, "run_2", thread_id="thread_shared")

    await _until(lambda: broker.get("run_1").is_claimed)
    await asyncio.sleep(0.1)
    assert provider.offered == ["run_1"], "the turn is open; the next utterance waits"

    broker.push("run_1", FinishStream())
    await _until(lambda: broker.get("run_2") and broker.get("run_2").is_claimed, timeout=2.0)
    assert provider.offered == ["run_1", "run_2"]


async def test_a_declined_head_is_not_overtaken_by_its_sibling(broker):
    """Arrival order is the one sequencing funduq does own: while the head of
    the queue stands declined, a later utterance of the same thread must not
    reach the provider first — offers resume (head first) as capacity
    frees.

    The provider declares no limit on purpose. With a declared one, a decline
    is additionally treated as reaching it, and *that* is what would hold the
    sibling back — the test would pass without arrival order existing at all.
    """
    from funduq.broker import FinishStream

    provider = Recording(answers=[True, False, True, True])
    broker.register_provider({AGENT: provider})
    _enqueue(broker, "run_1", thread_id="thread_shared")
    _enqueue(broker, "run_2", thread_id="thread_shared")
    _enqueue(broker, "run_3", thread_id="thread_shared")

    await _until(lambda: broker.get("run_1").is_claimed)
    broker.push("run_1", FinishStream())
    await _until(lambda: provider.offered.count("run_2") >= 1, timeout=2.0)
    await asyncio.sleep(0.1)
    assert "run_3" not in provider.offered, "run_3 must not overtake the declined run_2"

    await _until(lambda: broker.get("run_2") and broker.get("run_2").is_claimed, timeout=2.0)
    broker.push("run_2", FinishStream())
    await _until(lambda: "run_3" in provider.offered, timeout=2.0)
    assert provider.offered == ["run_1", "run_2", "run_2", "run_3"], (
        "the declined head is retried before its sibling is offered at all"
    )


async def test_a_paused_run_does_not_hold_back_its_siblings(broker):
    """A pause is between the provider and the asker; the thread's next
    utterance still reaches the provider, which knows its own paused run and
    decides how to sequence."""
    from funduq.broker import FinishStream

    provider = Recording()
    broker.register_provider({AGENT: provider})
    _enqueue(broker, "run_1", thread_id="t-paused")
    await _until(lambda: provider.offered == ["run_1"])
    broker._runs["run_1"].pause_payload = {"interrupts": []}
    broker.push("run_1", FinishStream())
    await _until(lambda: broker.get("run_1") is None, timeout=2.0)

    _enqueue(broker, "run_2", thread_id="t-paused")
    await _until(lambda: provider.offered == ["run_1", "run_2"], timeout=2.0)


async def test_an_unlimited_provider_that_declines_is_not_asked_again(broker):
    """funduq#128: declaring no limit is a declaration like any other, and a
    decline contradicts it. The contradiction is recorded once and offers
    stop — not re-asked every sweep, which only inflated `misdeclared` into
    noise — until the provider next does something observable."""
    provider = Recording(default=False)
    broker.register_provider({AGENT: provider})
    _enqueue(broker, "run_1")

    await _until(lambda: provider.offered == ["run_1"])
    await asyncio.sleep(0.2)
    assert provider.offered == ["run_1"], "one decline, no more offers"
    assert broker.quality()["pk_provider"].misdeclared == 1, "one event, one count"

    # Reconnecting is the provider acting; the withhold lifts.
    provider._default = True
    broker.register_provider({AGENT: provider})
    await _until(lambda: provider.offered == ["run_1", "run_1"], timeout=2.0)
    await _until(lambda: broker.get("run_1").is_claimed)




async def _recorder(seen: list[str], name: str):
    async def handler(run, cmd) -> None:
        seen.append(name)

    return handler


async def test_a_provider_slow_to_answer_does_not_hold_up_another_agents_handover(patient_broker):
    """One loop offering to one agent at a time, blocking on each answer, made
    a provider's slowness everyone's: an unrelated agent's trivial run took
    3.1s to reach its own unrelated provider (funduq#164). Handover is now one
    lane per agent, and only that agent's queue waits."""
    held = asyncio.Event()
    slow = Recording(key="pk_slow", hold=held)
    quick = Recording(key="pk_quick")
    patient_broker.register_provider({AGENT: slow, OTHER: quick})
    _enqueue(patient_broker, "run_slow", agent=AGENT)
    await _until(lambda: slow.offered == ["run_slow"])

    _enqueue(patient_broker, "run_quick", agent=OTHER)
    await _until(lambda: patient_broker.get("run_quick").is_claimed)

    assert patient_broker.get("run_slow").is_offered
    assert not patient_broker.get("run_slow").is_claimed, "the slow offer is still unanswered"
    held.set()


async def test_a_place_is_taken_when_the_offer_leaves_not_when_it_is_answered(patient_broker):
    """A provider that declared room for one, serving two agents, gets one
    offer — not two. The second lane would otherwise read an in-flight count
    the first lane has not been able to raise yet, and both would conclude
    there was room."""
    held = asyncio.Event()
    provider = Recording(max_concurrent_runs=1, hold=held)
    patient_broker.register_provider({AGENT: provider, OTHER: provider})
    _enqueue(patient_broker, "run_1", agent=AGENT)
    await _until(lambda: provider.offered == ["run_1"])

    _enqueue(patient_broker, "run_2", agent=OTHER)
    await asyncio.sleep(0.05)

    assert provider.offered == ["run_1"]
    assert patient_broker.quality()["pk_provider"].in_flight == 1
    held.set()


async def test_an_unaccepted_offer_gives_back_the_place_it_took(patient_broker):
    """The place is spent at dispatch, so a declined offer has to return it —
    otherwise a provider that declines enough times is silently full for good."""
    provider = Recording(default=False)
    patient_broker.register_provider({AGENT: provider})
    _enqueue(patient_broker, "run_1")

    await _until(lambda: provider.offered == ["run_1"])
    await _until(lambda: patient_broker.quality()["pk_provider"].in_flight == 0)
    assert patient_broker.get("run_1").is_offered is False


async def test_a_cancel_inside_the_dispatch_window_waits_for_the_answer(patient_broker):
    """A cancel arriving while an offer is unanswered used to take the queued
    path — funduq recorded the run cancelled and handed it to the provider a
    moment later, which then worked on something nobody would collect and lost
    its place for good (funduq#164). The claim is the older fact, so it is
    processed first and the cancel follows it: funduq asks the provider that
    took the run to stop, which is what a cancel is."""
    held = asyncio.Event()
    seen: list[str] = []
    handlers = {
        Claim: await _recorder(seen, "claim"),
        RequestCancel: await _recorder(seen, "cancel"),
    }
    provider = Recording(hold=held)
    patient_broker.register_provider({AGENT: provider})
    patient_broker.enqueue_run("run_1", AGENT, "thread_1", _valid_input("run_1", "thread_1"), "ag-ui", handlers)
    await _until(lambda: provider.offered == ["run_1"])

    assert patient_broker.request_cancel("run_1") is True
    held.set()

    await _until(lambda: seen == ["claim", "cancel"])
    assert patient_broker.get("run_1").claimed_by == "pk_provider"
    assert patient_broker.quality()["pk_provider"].in_flight == 1


async def test_a_cancel_inside_the_window_settles_the_run_when_nobody_takes_it(patient_broker):
    """The other half of the same window: the offer comes back declined, so no
    provider is working on anything, and the run is funduq's to end."""
    held = asyncio.Event()
    seen: list[str] = []
    handlers = {RequestCancel: await _recorder(seen, "cancel")}
    provider = Recording(default=False, hold=held)
    patient_broker.register_provider({AGENT: provider})
    patient_broker.enqueue_run("run_1", AGENT, "thread_1", _valid_input("run_1", "thread_1"), "ag-ui", handlers)
    await _until(lambda: provider.offered == ["run_1"])

    patient_broker.request_cancel("run_1")
    await asyncio.sleep(0.02)
    assert seen == [] and patient_broker.get("run_1") is not None, (
        "nothing about the run is settled while its answer is still out"
    )

    held.set()
    await _until(lambda: seen == ["cancel"])
    await _until(lambda: patient_broker.get("run_1") is None)
    assert patient_broker.quality()["pk_provider"].in_flight == 0


async def test_a_provider_that_stopped_serving_while_answering_does_not_keep_the_run(
    patient_broker,
):
    """The offer was out when the provider left the roster, and it came back
    accepted. The provider believes it took the run and nothing will finish
    it — the same fact `unregister_provider` records for a run it was already
    holding, reached through the one window that call cannot see into."""
    held = asyncio.Event()
    seen: list[str] = []
    handlers = {
        Claim: await _recorder(seen, "claim"),
        Fail: await _recorder(seen, "fail"),
    }
    provider = Recording(hold=held)
    patient_broker.register_provider({AGENT: provider})
    patient_broker.enqueue_run("run_1", AGENT, "thread_1", _valid_input("run_1", "thread_1"), "ag-ui", handlers)
    await _until(lambda: provider.offered == ["run_1"])

    patient_broker.unregister_provider([AGENT])
    held.set()

    await _until(lambda: seen == ["claim", "fail"])
    assert patient_broker.quality()["pk_provider"].abandoned == 1


async def test_two_conversations_with_one_agent_do_not_wait_for_each_other(patient_broker):
    """A thread is the pipe whose delivery order funduq guarantees. An agent is
    not a pipe: two of its conversations have no order between them, and a
    provider slow to answer about one of them says nothing about the other.
    Serializing per agent made Alice's 2s cost Bob 2s (funduq#164)."""
    held = asyncio.Event()

    class SlowAboutAlice(Recording):
        async def deliver(self, run) -> bool:
            self.offered.append(run.thread_id)
            if run.thread_id == "chat_alice":
                await held.wait()
            return True

    provider = SlowAboutAlice()
    patient_broker.register_provider({AGENT: provider})
    _enqueue(patient_broker, "run_alice", thread_id="chat_alice")
    await _until(lambda: provider.offered == ["chat_alice"])

    _enqueue(patient_broker, "run_bob", thread_id="chat_bob")
    await _until(lambda: patient_broker.get("run_bob").is_claimed)

    assert not patient_broker.get("run_alice").is_claimed
    held.set()


async def test_one_conversation_is_handed_over_one_utterance_at_a_time(patient_broker):
    """The order funduq does owe: a provider that takes turns can only take
    them in the order things reach it, so two utterances of the same thread are
    never in flight to it at once. Handing both over together would let its own
    sequencing lock in an order nobody chose."""
    held = asyncio.Event()

    class SlowAboutTheFirst(Recording):
        async def deliver(self, run) -> bool:
            self.offered.append(run.run_id)
            if run.run_id == "run_1":
                await held.wait()
            return True

    provider = SlowAboutTheFirst()
    patient_broker.register_provider({AGENT: provider})
    _enqueue(patient_broker, "run_1", thread_id="one_chat")
    await _until(lambda: provider.offered == ["run_1"])

    _enqueue(patient_broker, "run_2", thread_id="one_chat")
    await asyncio.sleep(0.05)
    assert provider.offered == ["run_1"], "the second utterance must not overtake the first"

    held.set()
    await _until(lambda: patient_broker.get("run_1").is_claimed)
    await asyncio.sleep(0.05)
    assert provider.offered == ["run_1"], "claiming opens no gate; finishing does"

    from funduq.broker import FinishStream

    patient_broker.push("run_1", FinishStream())
    await _until(lambda: provider.offered == ["run_1", "run_2"])


async def test_several_reasons_to_try_at_once_ask_the_run_once(broker):
    """A run's chance to be handed over can change for several reasons in the
    same breath — it was queued, a provider attached, a place freed. Each puts
    the same question in its lane, and without coalescing the run is offered
    once per copy: two offers for one dispatchable moment, and two counts
    against a provider for one decline."""
    provider = Recording(default=False)
    broker.register_provider({AGENT: provider})
    run = _enqueue(broker, "run_1")
    broker.register_provider({AGENT: provider})
    broker.register_provider({AGENT: provider})

    assert run.in_queue.qsize() == 1, "one pending question, however many reasons"


async def test_a_run_is_not_accepted_for_an_agent_nobody_is_serving(broker):
    """A run is only ever born with a provider online, and the lane is written
    to open by offering rather than by waiting for somebody to appear. Losing a
    provider later is an ordinary thing that happens to a live run; never
    having had one is not, and taking such a run would mean holding something
    nothing could ever finish.

    The refusal is a **value**, because the door cannot ask this first and
    then act on the answer: `await session.commit()` sits between, and a
    provider leaving inside it made the two readings disagree. One party
    reads the roster, with the insert it guards; the door acts on what it
    gets back — see `tests/test_a_provider_leaving_during_dispatch.py`."""
    assert _enqueue(broker, "run_1") is None

    broker.register_provider({AGENT: Recording()})
    _enqueue(broker, "run_2")
    await _until(lambda: broker.get("run_2").is_claimed)
