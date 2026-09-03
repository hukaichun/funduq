from __future__ import annotations

import asyncio

from funduq.broker import RelayEvent, RunBroker
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


AGENT = AgentRef(provider_key="sdk_1", name="agent_1")


class _Taker:

    public_key = "sdk_1"
    max_concurrent_runs = None

    def __init__(self, broker: RunBroker) -> None:
        self.broker = broker

    async def deliver(self, run) -> None:
        self.broker.answer_offer(run.run_id, True, provider_key=self.public_key)

    async def cancel(self, run_id: str) -> bool:
        return True
async def _delivered(broker: RunBroker, key: str = "sdk_1"):
    """A claimed run, plus the list its lane records relays into. Observed
    through a handler rather than by reading `run.in_queue`: the run has its
    own lane from the moment it is queued, and reading its queue from a test
    is racing that lane for it."""
    provider = _Taker(broker)
    provider.public_key = key
    broker.register_provider({AGENT: provider})
    relayed: list = []

    async def record(run, cmd) -> None:
        relayed.append(cmd)

    run = broker.enqueue_run("run_1", AGENT, "thread_1", _valid_input("run_1", "thread_1"), "ag-ui", {RelayEvent: record})
    async with asyncio.timeout(1):
        while run.claimed_by is None:
            await asyncio.sleep(0)
    return run, relayed


async def test_a_reported_event_lands_on_the_runs_own_queue_untouched(funduq):
    broker = RunBroker()
    broker.start()
    funduq.broker, original = broker, funduq.broker
    try:
        _run, relayed = await _delivered(broker)

        event = {"type": "CUSTOM", "value": object()}
        assert funduq.report_event("run_1", event, claimed_by="sdk_1") is True

        async with asyncio.timeout(1):
            while not relayed:
                await asyncio.sleep(0)
        assert isinstance(relayed[0], RelayEvent)
        assert relayed[0].event is event
    finally:
        broker.stop()
        funduq.broker = original


async def test_an_event_for_someone_elses_run_is_refused(funduq):
    broker = RunBroker()
    broker.start()
    funduq.broker, original = broker, funduq.broker
    try:
        _run, relayed = await _delivered(broker, key="sdk_owner")

        # The door attributes and accepts the report for judgment (True =
        # the run is known); whether the reporter holds the run is judged
        # by the run's owner — and the impostor's words never reach the
        # record. The run also does not end on an impostor's say-so.
        assert funduq.report_event("run_1", {"type": "CUSTOM"}, claimed_by="sdk_impostor") is True
        assert funduq.finish_run("run_1", claimed_by="sdk_impostor") is True
        await asyncio.sleep(0.02)
        assert relayed == []
        assert broker.get("run_1") is not None, "an impostor's finish ends nothing"

        assert funduq.report_event("run_1", {"type": "CUSTOM"}, claimed_by="sdk_owner") is True
        async with asyncio.timeout(1):
            while not relayed:
                await asyncio.sleep(0)
    finally:
        broker.stop()
        funduq.broker = original


def test_reporting_for_a_run_funduq_no_longer_has_is_not_an_error(funduq):
    assert funduq.report_event("run_gone", {"type": "CUSTOM"}, claimed_by="sdk_1") is False
    assert funduq.finish_run("run_gone", claimed_by="sdk_1") is False
