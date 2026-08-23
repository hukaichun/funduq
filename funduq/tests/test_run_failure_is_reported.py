from __future__ import annotations

import asyncio

from funduq_provider_sdk import InProcessLink, ProviderIdentity, ProviderRuntime

import pytest

from tests.conftest import publish_agents, publish_offline

from funduq import repo
from funduq.config import CoreSettings
from funduq.broker import RunBroker
from funduq.core import Funduq


class NeverFinishesProvider:
    """Claims a run and never ends its stream, so the provider stays at capacity."""

    async def run_stream(self, agent_name: str, run_input):
        yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_input.run_id}
        await asyncio.Event().wait()


async def _status_is(funduq, run_id: str, status: str) -> bool:
    run = await funduq.get_run(run_id)
    return run is not None and run.status == status


async def _until_async(predicate, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not await predicate():
            await asyncio.sleep(0.005)


async def _until(predicate, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


async def _register(funduq, *names: str):
    identity = ProviderIdentity.generate()
    registration = await publish_offline(funduq, identity, [{"name": n} for n in names])
    return registration, identity


@pytest.fixture
async def brisk(settings: CoreSettings):
    funduq = Funduq(settings)
    await funduq.start()
    runtimes: list[ProviderRuntime] = []

    async def _attach(identity, provider, names):
        runtime = ProviderRuntime(identity, provider)
        runtimes.append(runtime)
        runtime.start()
        await publish_agents(funduq, InProcessLink(funduq, runtime), list(names))
        return runtime

    funduq.attach = _attach
    try:
        yield funduq
    finally:
        for runtime in runtimes:
            await runtime.aclose(cancel_in_flight=True)
        await funduq.aclose()


async def test_a_provider_that_raises_reaches_the_caller_as_run_error(brisk):
    registration, identity = await _register(brisk, "explodes")
    agent_id = registration.agents["explodes"]

    class Exploding:
        async def run_stream(self, agent_id: str, run_input: dict):
            raise KeyError("token")
            yield

    await brisk.attach(identity, Exploding(), [agent_id.name])
    handle = await brisk.start_run(agent_id, {"messages": []})

    events = [e async for e in handle.events()]

    assert [e["type"] for e in events] == ["RUN_ERROR"]
    assert events[0]["code"] == "provider_stream_ended_without_finishing"

    await _until(lambda: handle.run_id not in brisk.active_runs())
    async with brisk.session() as session:
        stored = await repo.get_run(session, handle.run_id)
        persisted = await repo.get_run_events(session, handle.run_id)
    assert stored.status == "failed"
    assert [e["type"] for e in persisted] == ["RUN_ERROR"]


async def test_a_permanent_refusal_fails_the_run_with_the_providers_reason(brisk):
    from funduq_provider_sdk import Refusal

    registration, identity = await _register(brisk, "retired")
    agent_id = registration.agents["retired"]

    class Refuses:
        max_concurrent_runs = None

        def __init__(self) -> None:
            self.public_key = identity.public_key
            self.sign_connect = identity.sign_connect
            self.offers = 0

        async def deliver(self, run):
            self.offers += 1
            return Refusal("this agent was retired, run something newer")

        def cancel(self, run_id: str) -> None:
            pass

    link = Refuses()
    await brisk.attach_provider(link)
    await brisk.register_agents(link, [{"name": agent_id.name}])
    handle = await brisk.start_run(agent_id, {"messages": []})

    events = [e async for e in handle.events()]
    assert [e["type"] for e in events] == ["RUN_ERROR"]
    assert events[0]["message"] == "this agent was retired, run something newer"

    await _until(lambda: handle.run_id not in brisk.active_runs())
    async with brisk.session() as session:
        stored = await repo.get_run(session, handle.run_id)
    assert stored.status == "failed"
    assert stored.metadata["failureReason"] == "this agent was retired, run something newer"
    assert link.offers == 1


async def test_a_malformed_event_fails_the_run_instead_of_relaying_garbage(brisk):
    registration, identity = await _register(brisk, "malformed")
    agent_id = registration.agents["malformed"]

    class SendsGarbage:
        async def run_stream(self, agent_id: str, run_input: dict):
            yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_input.run_id}
            yield {"type": "TEXT_MESSAGE_START", "role": "assistant"}
            yield {"type": "RUN_FINISHED", "threadId": run_input.thread_id, "runId": run_input.run_id}

    await brisk.attach(identity, SendsGarbage(), [agent_id.name])
    handle = await brisk.start_run(agent_id, {"messages": []})

    events = [e async for e in handle.events()]

    assert [e["type"] for e in events] == ["RUN_STARTED", "RUN_ERROR"]
    assert events[-1]["message"] == "provider sent a malformed AG-UI event"

    await _until(lambda: handle.run_id not in brisk.active_runs())
    async with brisk.session() as session:
        stored = await repo.get_run(session, handle.run_id)
        persisted = await repo.get_run_events(session, handle.run_id)
    assert stored.status == "failed"
    assert stored.metadata["failureReason"] == "provider sent a malformed AG-UI event"
    assert [e["type"] for e in persisted] == ["RUN_STARTED", "RUN_ERROR"]


async def test_a_provider_that_reports_its_own_failure_is_not_corrected(brisk):
    registration, identity = await _register(brisk, "polite")
    agent_id = registration.agents["polite"]

    class ReportsItsOwn:
        async def run_stream(self, agent_id: str, run_input: dict):
            yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_input.run_id}
            yield {"type": "RUN_ERROR", "message": "upstream model refused the request"}

    await brisk.attach(identity, ReportsItsOwn(), [agent_id.name])
    handle = await brisk.start_run(agent_id, {"messages": []})

    events = [e async for e in handle.events()]

    assert [e["type"] for e in events] == ["RUN_STARTED", "RUN_ERROR"]
    assert events[-1]["message"] == "upstream model refused the request"

    await _until(lambda: handle.run_id not in brisk.active_runs())
    async with brisk.session() as session:
        assert (await repo.get_run(session, handle.run_id)).status == "failed"


async def test_a_cancelled_run_gets_no_run_error(brisk):
    registration, identity = await _register(brisk, "stoppable")
    agent_id = registration.agents["stoppable"]
    started = asyncio.Event()

    class WaitsForever:
        async def run_stream(self, agent_id: str, run_input: dict):
            yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_input.run_id}
            started.set()
            await asyncio.Event().wait()

    await brisk.attach(identity, WaitsForever(), [agent_id.name])
    handle = await brisk.start_run(agent_id, {"messages": []})

    stream = handle.events()
    assert (await stream.__anext__())["type"] == "RUN_STARTED"
    await started.wait()
    handle.cancel()

    assert [e["type"] async for e in stream] == []

    await _until(lambda: handle.run_id not in brisk.active_runs())
    async with brisk.session() as session:
        assert (await repo.get_run(session, handle.run_id)).status == "cancelled"


async def test_a_run_nobody_ever_comes_for_is_given_up_on(settings: CoreSettings):
    """The unserved window fails a run that is queued when its agent stops being served.

    Reaching that state takes the sequence it actually arises from, because
    no entrance will queue for an agent nobody serves: a provider is
    attached, a run is queued behind one it declined for capacity, and the
    provider then detaches. The clock runs from the later of when the run
    was queued and when the agent went unserved — here, the detach.
    """
    funduq = Funduq(settings, broker=RunBroker(unserved_timeout_seconds=0.05))
    await funduq.start()
    runtime = None
    try:
        registration, identity = await _register(funduq, "unserved")
        agent = registration.agents["unserved"]

        runtime = ProviderRuntime(
            identity, NeverFinishesProvider(), max_queued_runs=1, max_concurrent_runs=1
        )
        runtime.start()
        link = InProcessLink(funduq, runtime)
        await publish_agents(funduq, link, ["unserved"])

        # Fills the declared capacity and never finishes, so the next run is
        # declined and sits queued rather than being offered.
        busy = await funduq.start_run(agent, {"messages": []})
        await _until(lambda: busy.run_id in funduq.active_runs())
        handle = await funduq.start_run(agent, {"messages": []})

        # No provider has accepted it — which is either of the two pending
        # statuses, depending on whether the offer that will be declined has
        # gone out yet. Asserting the exact one makes this a race with the
        # database's own speed, not a statement about the run.
        async with funduq.session() as session:
            status = (await repo.get_run(session, handle.run_id)).status
        assert status in repo.PENDING_RUN_STATUSES

        funduq.detach_provider(identity.public_key, link)
        assert not funduq.is_serving(agent)

        await _until(lambda: handle.run_id not in funduq.active_runs())
        run = await funduq.get_run(handle.run_id)
        assert run.status == "failed"
        assert run.metadata["failureReason"] == "no_provider_took_it"
    finally:
        if runtime is not None:
            await runtime.aclose(cancel_in_flight=True)
        await funduq.aclose()


async def test_an_event_type_funduq_does_not_know_is_relayed_untouched(brisk):
    registration, identity = await _register(brisk, "futuristic")
    agent_id = registration.agents["futuristic"]
    future_event = {
        "type": "SOME_FUTURE_EVENT",
        "payload": {"nested": ["anything", 42]},
        "rawEvent": None,
    }

    class SpeaksNewerAgUi:
        async def run_stream(self, agent_id: str, run_input: dict):
            ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
            yield {"type": "RUN_STARTED", **ids}
            yield dict(future_event)
            yield {"type": "RUN_FINISHED", **ids}

    await brisk.attach(identity, SpeaksNewerAgUi(), [agent_id.name])
    handle = await brisk.start_run(agent_id, {"messages": []})

    events = [e async for e in handle.events()]

    assert [e["type"] for e in events] == ["RUN_STARTED", "SOME_FUTURE_EVENT", "RUN_FINISHED"]
    assert events[1] == future_event, "the relay must not rewrite what it does not understand"

    await _until(lambda: handle.run_id not in brisk.active_runs())
    async with brisk.session() as session:
        stored = await repo.get_run(session, handle.run_id)
        persisted = await repo.get_run_events(session, handle.run_id)
    assert stored.status == "completed"
    assert [e["type"] for e in persisted] == ["RUN_STARTED", "SOME_FUTURE_EVENT", "RUN_FINISHED"]
    assert persisted[1] == future_event


async def test_an_event_with_no_type_string_is_malformation_not_version_skew(brisk):
    registration, identity = await _register(brisk, "typeless")
    agent_id = registration.agents["typeless"]

    class SendsTypeless:
        async def run_stream(self, agent_id: str, run_input: dict):
            ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
            yield {"type": "RUN_STARTED", **ids}
            yield {"payload": "no type at all"}
            yield {"type": "RUN_FINISHED", **ids}

    await brisk.attach(identity, SendsTypeless(), [agent_id.name])
    handle = await brisk.start_run(agent_id, {"messages": []})

    events = [e async for e in handle.events()]

    assert [e["type"] for e in events] == ["RUN_STARTED", "RUN_ERROR"]
    assert events[-1]["message"] == "provider sent a malformed AG-UI event"


class BlockedProvider:
    """Claims its run, says one thing, and then goes quiet indefinitely."""

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run_stream(self, agent_name: str, run_input):
        yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_input.run_id}
        self.started.set()
        await asyncio.Event().wait()


async def test_a_provider_that_leaves_holding_a_run_fails_it_at_once(settings: CoreSettings):
    """The one fact funduq owns about a claimed run is whether the party holding it is still
    here. When they are not, nobody is going to finish it, and that is settled immediately —
    not inferred from a clock later, and recorded as what actually happened.

    The same fact is the judgment about the provider: failing a claimed run
    is what records `abandoned` against it — took a run and never ended it.
    """
    funduq = Funduq(settings, broker=RunBroker())
    await funduq.start()
    runtime = None
    try:
        registration, identity = await _register(funduq, "held")
        agent = registration.agents["held"]
        provider = BlockedProvider()
        runtime = ProviderRuntime(identity, provider)
        runtime.start()
        link = InProcessLink(funduq, runtime)
        await publish_agents(funduq, link, ["held"])

        handle = await funduq.start_run(agent, {"messages": []})
        await asyncio.wait_for(provider.started.wait(), 5)
        # The claim's status write is asynchronous; wait for it to land so
        # the assertion below is about a run that was genuinely claimed.
        await _until_async(lambda: _status_is(funduq, handle.run_id, "running"))

        funduq.detach_provider(identity.public_key, link)

        await _until(lambda: handle.run_id not in funduq.active_runs())
        run = await funduq.get_run(handle.run_id)
        assert run.status == "failed"
        assert run.metadata["failureReason"] == "provider_left_holding_it"
        assert funduq.broker.quality()[identity.public_key].abandoned == 1
    finally:
        if runtime is not None:
            await runtime.aclose(cancel_in_flight=True)
        await funduq.aclose()


async def test_a_provider_that_is_merely_quiet_keeps_its_run(settings: CoreSettings):
    """Silence is not a verdict. How long a provider holds a run is its own business — funduq
    does not pace a provider's work, and an agent's loop is silent for most of its life by
    construction, because the model call it waits on is the segment nothing can be injected
    into.

    There used to be a clock here (`run_stall_timeout_seconds`, 120s) that
    failed a claimed run for going quiet. It blamed slow providers for
    doing nothing wrong, and it blamed runs whose silence funduq itself was
    causing by holding their KYOK completion. The party with a stake has a
    lever that funduq does not need: the caller can cancel.

    There is now no clock of funduq's left to run at all — the health sweep
    that used to tick went with the pause deadline — so this asserts the
    absence rather than a sweep declining to act.
    """
    funduq = Funduq(settings, broker=RunBroker())
    await funduq.start()
    runtime = None
    try:
        registration, identity = await _register(funduq, "thinking")
        agent = registration.agents["thinking"]
        provider = BlockedProvider()
        runtime = ProviderRuntime(identity, provider)
        runtime.start()
        await publish_agents(funduq, InProcessLink(funduq, runtime), ["thinking"])

        handle = await funduq.start_run(agent, {"messages": []})
        await asyncio.wait_for(provider.started.wait(), 5)
        await _until_async(lambda: _status_is(funduq, handle.run_id, "running"))

        await asyncio.sleep(0.05)
        assert (await funduq.get_run(handle.run_id)).status == "running"
        assert funduq.broker.quality()[identity.public_key].abandoned == 0

        assert await funduq.cancel_run(handle.run_id) is True
        await _until(lambda: handle.run_id not in funduq.active_runs())
    finally:
        if runtime is not None:
            await runtime.aclose(cancel_in_flight=True)
        await funduq.aclose()


async def test_a_provider_that_delivers_nothing_is_counted_not_cut_off(settings: CoreSettings):
    """Whether a provider is working is read from what it **delivers**, not from whether it
    started. A `RUN_STARTED` is not delivery, and neither is any amount of visible motion —
    only the run ending clears this.

    Accepting is the declaration being judged. A provider that does not
    want the work has two honest answers already in the protocol, decline
    and refuse; choosing *accepted* says it has taken it. So the count
    lands on the provider, and the run is left alone: funduq still does not
    decide how long anyone may hold one.
    """
    funduq = Funduq(settings, broker=RunBroker(undelivered_window_seconds=0.05))
    await funduq.start()
    runtime = None
    try:
        registration, identity = await _register(funduq, "squatter")
        agent = registration.agents["squatter"]
        provider = BlockedProvider()          # emits RUN_STARTED, then nothing, forever
        runtime = ProviderRuntime(identity, provider)
        runtime.start()
        await publish_agents(funduq, InProcessLink(funduq, runtime), ["squatter"])

        handle = await funduq.start_run(agent, {"messages": []})
        await asyncio.wait_for(provider.started.wait(), 5)
        await _until_async(lambda: _status_is(funduq, handle.run_id, "running"))

        await _until(lambda: funduq.broker.quality()[identity.public_key].undelivered >= 1)

        # Give anything the observation might have queued time to land, so
        # this asserts the run was left alone rather than merely not-yet-
        # touched.
        await asyncio.sleep(0.3)
        assert handle.run_id in funduq.active_runs(), (
            "the run is untouched — funduq judges the provider, not the work"
        )
        assert (await funduq.get_run(handle.run_id)).status == "running"
        assert [e["type"] for e in await funduq.get_run_events(handle.run_id)] == [
            "RUN_STARTED"
        ], "nothing was appended to the caller's stream on its behalf"
        assert funduq.broker.quality()[identity.public_key].abandoned == 0, (
            "and it is the observed counter, not the certain one"
        )

        await funduq.cancel_run(handle.run_id)
        await _until(lambda: handle.run_id not in funduq.active_runs())
    finally:
        if runtime is not None:
            await runtime.aclose(cancel_in_flight=True)
        await funduq.aclose()


async def test_one_run_never_counts_twice_against_its_provider(settings: CoreSettings):
    """`undelivered` is what funduq observed; `abandoned` is what it knows for certain. A run
    already counted as undelivered is not counted again when its provider then leaves holding
    it — otherwise one incident reads as two, and the whole reason for keeping the counters
    apart (telling a provider that dropped three times from one that was slow three times)
    is lost."""
    funduq = Funduq(settings, broker=RunBroker(undelivered_window_seconds=0.05))
    await funduq.start()
    runtime = None
    try:
        registration, identity = await _register(funduq, "slow-then-gone")
        agent = registration.agents["slow-then-gone"]
        provider = BlockedProvider()
        runtime = ProviderRuntime(identity, provider)
        runtime.start()
        link = InProcessLink(funduq, runtime)
        await publish_agents(funduq, link, ["slow-then-gone"])

        handle = await funduq.start_run(agent, {"messages": []})
        await asyncio.wait_for(provider.started.wait(), 5)
        await _until(lambda: funduq.broker.quality()[identity.public_key].undelivered == 1)

        funduq.detach_provider(identity.public_key, link)
        await _until(lambda: handle.run_id not in funduq.active_runs())

        quality = funduq.broker.quality()[identity.public_key]
        assert quality.undelivered == 1
        assert quality.abandoned == 0, "one run, one count — the first thing funduq observed"
        assert (await funduq.get_run(handle.run_id)).status == "failed"
    finally:
        if runtime is not None:
            await runtime.aclose(cancel_in_flight=True)
        await funduq.aclose()
