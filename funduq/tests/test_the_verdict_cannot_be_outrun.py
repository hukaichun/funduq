"""funduq#249: a provider that answers and streams in the same breath.

The old broker read the verdict off `deliver`'s return and recorded the
claim in another task's continuation — so a provider fast enough to answer
and stream in one synchronous breath had its opening events refused by
core's own door ("nobody holds"). These tests are deterministic, not raced:
the fixture puts *zero awaits* between the verdict and the events, inside
`deliver`'s own call path, so the broker is provably still parked on the
hand-over when every event arrives. Under the old model that fails 100% of
the time; under this one it passes 100% of the time. Inserting any await
into the fixture would make it pass for the wrong reason on a fast day.
"""

from __future__ import annotations

import asyncio

import pytest

from funduq.broker import (
    Claim,
    Fail,
    FinishStream,
    Offer,
    RelayEvent,
    Requeue,
    RunBroker,
)
from funduq.models import AgentRef


AGENT = AgentRef(provider_key="pk_breath", name="quick")


def _valid_input(run_id: str, thread_id: str) -> dict:
    return {
        "threadId": thread_id,
        "runId": run_id,
        "state": None,
        "messages": [],
        "tools": [],
        "context": [],
        "forwardedProps": None,
    }


async def _until(predicate, timeout: float = 1.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0)


def _recording_handlers(record: list) -> dict:
    async def note(run, cmd) -> None:
        record.append(cmd)

    return {
        Offer: note,
        Requeue: note,
        Claim: note,
        RelayEvent: note,
        FinishStream: note,
        Fail: note,
    }


class SameBreath:
    """Answers the offer and streams its whole run in one synchronous breath —
    no awaits between the verdict and the last report."""

    max_concurrent_runs = None

    def __init__(self, broker: RunBroker, key: str = "pk_breath") -> None:
        self.broker = broker
        self.public_key = key

    async def deliver(self, run) -> None:
        self.broker.answer_offer(run.run_id, True, provider_key=self.public_key)
        for i in range(3):
            self.broker.report_event(
                run.run_id, {"type": "CUSTOM", "i": i}, origin=self.public_key
            )
        self.broker.finish_stream(run.run_id, origin=self.public_key)

    async def cancel(self, run_id: str) -> bool:
        return True


@pytest.fixture
async def broker():
    b = RunBroker(deliver_timeout_seconds=0.05, unserved_timeout_seconds=30)
    b.start()
    try:
        yield b
    finally:
        b.stop()


async def test_a_provider_that_answers_and_streams_in_the_same_breath_loses_nothing(broker):
    record: list = []
    broker.register_provider({AGENT: SameBreath(broker)})
    broker.enqueue_run(
        "run_1", AGENT, "t1", _valid_input("run_1", "t1"), "ag-ui",
        _recording_handlers(record),
    )

    await _until(lambda: broker.get("run_1") is None)

    kinds = [type(cmd).__name__ for cmd in record]
    assert kinds == ["Offer", "Claim", "RelayEvent", "RelayEvent", "RelayEvent", "FinishStream"], (
        "the record is ordered by construction: the claim lands before the "
        "events that followed it out of the same mouth, and nothing is refused"
    )
    assert broker.quality()["pk_breath"].abandoned == 0, (
        "a provider is not walked toward withdrawal for answering promptly"
    )
    assert broker.quality()["pk_breath"].unanswered == 0


async def test_a_declined_offer_buys_no_voice(broker):
    class DeclinesAndTalks(SameBreath):
        async def deliver(self, run) -> None:
            self.broker.answer_offer(run.run_id, False, provider_key=self.public_key)
            self.broker.report_event(
                run.run_id, {"type": "CUSTOM"}, origin=self.public_key
            )

    record: list = []
    broker.register_provider({AGENT: DeclinesAndTalks(broker)})
    broker.enqueue_run(
        "run_1", AGENT, "t1", _valid_input("run_1", "t1"), "ag-ui",
        _recording_handlers(record),
    )

    await _until(lambda: any(isinstance(c, Requeue) for c in record))
    assert not any(isinstance(c, RelayEvent) for c in record), (
        "declining and then talking records the decline and none of the talk"
    )


async def test_another_connections_words_never_enter_the_record(broker):
    class Impostor(SameBreath):
        async def deliver(self, run) -> None:
            self.broker.answer_offer(run.run_id, True, provider_key=self.public_key)
            # A different key speaks about the run in the same breath.
            self.broker.report_event(
                run.run_id, {"type": "CUSTOM"}, origin="pk_somebody_else"
            )
            self.broker.finish_stream(run.run_id, origin="pk_somebody_else")

    record: list = []
    broker.register_provider({AGENT: Impostor(broker)})
    broker.enqueue_run(
        "run_1", AGENT, "t1", _valid_input("run_1", "t1"), "ag-ui",
        _recording_handlers(record),
    )

    await _until(lambda: any(isinstance(c, Claim) for c in record))
    await asyncio.sleep(0.02)
    assert not any(isinstance(c, (RelayEvent, FinishStream)) for c in record)
    assert broker.get("run_1") is not None, "an impostor's finish ends nothing"


async def test_a_verdict_after_funduq_moved_on_lands_nowhere(broker):
    class AnswersTooLate(SameBreath):
        def __init__(self, broker) -> None:
            super().__init__(broker)
            self.saw = asyncio.Event()

        async def deliver(self, run) -> None:
            self.saw.set()
            # Never answers inside the window; the test answers later, by hand.

    record: list = []
    provider = AnswersTooLate(broker)
    broker.register_provider({AGENT: provider})
    broker.enqueue_run(
        "run_1", AGENT, "t1", _valid_input("run_1", "t1"), "ag-ui",
        _recording_handlers(record),
    )

    await provider.saw.wait()
    # Observe the state transition, then act — no sleeps guessed at.
    await _until(lambda: broker.quality()["pk_breath"].unanswered >= 1, timeout=2.0)
    await _until(lambda: any(isinstance(c, Requeue) for c in record))

    broker.answer_offer("run_1", True, provider_key="pk_breath")
    await asyncio.sleep(0.02)
    assert broker.get("run_1").claimed_by is None, (
        "an offer that lapsed cannot be claimed by answering it later"
    )
