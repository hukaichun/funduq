"""A queued run was never in any process, so a restart is not its business (#122).

Its row is the input its provider will receive (#254), its messages are in
the thread, and its KYOK opt-in — context included — is in its metadata. A
new process reads the rows back and queues them in the order they arrived.
Providers connect after start, so each waits on the unserved clock like any
run whose provider stepped away. What a process *held* — an offer out, a
claim, a cancel in flight — dies with it and is failed loudly, as before.
"""

from __future__ import annotations

import asyncio

from funduq_provider_sdk import InProcessLink, ProviderRuntime
from funduq_provider_sdk.llm import InProcessLLMProvider, ProviderIdentity

from funduq import repo
from funduq.broker import RunBroker
from funduq.core import Funduq
from funduq.models import LlmRef
from funduq.props import ADDRESSED_RUN_METADATA_KEY
from funduq.protocols.a2a import A2AAdapter

from tests.conftest import Identity, publish_agents, publish_llm


class NeverFinishes:
    async def run_stream(self, agent_name: str, run_input):
        yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_input.run_id}
        await asyncio.Event().wait()


class Receives:
    def __init__(self) -> None:
        self.rounds: list[dict] = []

    async def run_stream(self, agent_name: str, run_input):
        self.rounds.append(run_input.model_dump(mode="json", by_alias=True))
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        yield {"type": "RUN_FINISHED", **ids}


async def _until(predicate, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while True:
            result = predicate()
            if asyncio.iscoroutine(result):
                result = await result
            if result:
                return
            await asyncio.sleep(0.01)


async def _serve_on(funduq, identity, provider, names, **kwargs):
    runtime = ProviderRuntime(identity, provider, **kwargs)
    runtime.start()
    link = InProcessLink(funduq, runtime)
    await publish_agents(funduq, link, list(names))
    return runtime


async def _one_running_one_queued(funduq, attach, identity):
    """A provider at capacity holds one run; the next utterance on the same thread waits behind it."""
    await attach(identity, NeverFinishes(), ["a"], max_concurrent_runs=1)
    from funduq.models import AgentRef
    agent = AgentRef(provider_key=identity.public_key, name="a")
    busy = await funduq.start_run(agent, {"messages": [{"id": "m1", "role": "user", "content": "first"}]})
    await _until(lambda: _status_is(funduq, busy.run_id, "running"))
    waiting = await funduq.start_run(
        agent, {"messages": [{"id": "m2", "role": "user", "content": "second"}]}, thread_id=busy.thread_id
    )
    assert (await funduq.get_run(waiting.run_id)).status == "queued"
    return agent, busy, waiting


async def _status_is(funduq, run_id: str, status: str) -> bool:
    run = await funduq.get_run(run_id)
    return run is not None and run.status == status


async def test_the_held_run_dies_with_the_process_and_the_waiting_one_does_not(funduq, attach, settings):
    identity = Identity()
    agent, busy, waiting = await _one_running_one_queued(funduq, attach, identity)

    reborn = Funduq(settings)
    runtime = None
    try:
        orphaned = await reborn.start()

        assert busy.run_id in orphaned
        assert waiting.run_id not in orphaned
        assert (await reborn.get_run(waiting.run_id)).status == "queued"
        assert waiting.run_id in reborn.active_runs(), "taken back, waiting for its provider"

        provider = Receives()
        runtime = await _serve_on(reborn, identity, provider, ["a"])
        await _until(lambda: _status_is(reborn, waiting.run_id, "completed"))

        stored = await reborn.get_run(waiting.run_id)
        assert provider.rounds == [stored.input_json], "delivered exactly what the row held"
    finally:
        if runtime is not None:
            await runtime.aclose(cancel_in_flight=True)
        await reborn.aclose()


async def test_recovered_runs_keep_the_order_they_arrived_in(funduq, attach, settings):
    identity = Identity()
    agent, busy, second = await _one_running_one_queued(funduq, attach, identity)
    third = await funduq.start_run(
        agent, {"messages": [{"id": "m3", "role": "user", "content": "third"}]}, thread_id=busy.thread_id
    )

    reborn = Funduq(settings)
    runtime = None
    try:
        await reborn.start()
        provider = Receives()
        runtime = await _serve_on(reborn, identity, provider, ["a"])
        await _until(lambda: _status_is(reborn, third.run_id, "completed"))

        assert [r["runId"] for r in provider.rounds] == [second.run_id, third.run_id]
    finally:
        if runtime is not None:
            await runtime.aclose(cancel_in_flight=True)
        await reborn.aclose()


async def test_a_kyok_binding_is_read_back_from_the_row(funduq, attach, settings):
    llm_identity = ProviderIdentity.generate()

    async def _no_completions(delivered):
        raise AssertionError("never called")
        yield  # pragma: no cover

    await publish_llm(funduq, InProcessLLMProvider(llm_identity, _no_completions), ["gpt4"])
    ref = LlmRef(provider_key=llm_identity.public_key, name="gpt4")

    identity = Identity()
    await attach(identity, NeverFinishes(), ["a"], max_concurrent_runs=1)
    from funduq.models import AgentRef
    agent = AgentRef(provider_key=identity.public_key, name="a")
    busy = await funduq.start_run(agent, {"messages": []})
    await _until(lambda: _status_is(funduq, busy.run_id, "running"))
    opt_in = {
        "kyok": {
            "llmProvider": {"providerKey": llm_identity.public_key, "name": "gpt4"},
            "context": {"voucher": "v1"},
        }
    }
    waiting = await funduq.start_run(agent, {"messages": []}, thread_id=busy.thread_id, metadata=opt_in)
    assert funduq.kyok_relay.binding_for(waiting.run_id).context == {"voucher": "v1"}

    reborn = Funduq(settings)
    try:
        await reborn.start()
        binding = reborn.kyok_relay.binding_for(waiting.run_id)
        assert binding is not None
        assert binding.llm_provider == ref
        assert binding.context == {"voucher": "v1"}, "ordinary content of the record, read back like the rest"
        assert (await reborn.get_run(waiting.run_id)).metadata["kyok"]["context"] == {"voucher": "v1"}
    finally:
        await reborn.aclose()
        funduq.detach_all_for(llm_identity.public_key)


async def test_an_interjection_whose_target_died_fails_loudly(funduq, attach, settings):
    identity = Identity()
    agent, busy, _ = await _one_running_one_queued(funduq, attach, identity)

    # Declared against the running turn; the provider is at capacity, so it waits.
    interjecting = asyncio.create_task(
        A2AAdapter(funduq).send_task(
            agent,
            {
                "role": "user",
                "parts": [{"type": "text", "text": "actually, in metric"}],
                "contextId": busy.thread_id,
                "metadata": {ADDRESSED_RUN_METADATA_KEY: busy.run_id},
            },
        )
    )

    async def _queued_interjection():
        async with funduq.session() as session:
            rows = await repo.queued_runs(session)
        return next((r for r in rows if r.protocol == "a2a"), None)

    await _until(lambda: _queued_interjection())
    interjection = await _queued_interjection()
    assert interjection.input_json["forwardedProps"]["addressedRunId"] == busy.run_id

    reborn = Funduq(settings)
    try:
        await reborn.start()
        stored = await reborn.get_run(interjection.run_id)
        assert stored.status == "failed"
        assert stored.metadata["failureReason"] == "interjection_target_lost"
        assert interjection.run_id not in reborn.active_runs()
        async with reborn.session() as session:
            events = await repo.get_run_events(session, interjection.run_id)
        assert events[-1] == {"type": "RUN_ERROR", "message": "interjection_target_lost"}
    finally:
        interjecting.cancel()
        await reborn.aclose()


async def test_a_recovered_run_nobody_comes_back_for_is_given_up_on(funduq, attach, settings):
    identity = Identity()
    agent, busy, waiting = await _one_running_one_queued(funduq, attach, identity)

    reborn = Funduq(settings, broker=RunBroker(unserved_timeout_seconds=0.05))
    try:
        await reborn.start()
        await _until(lambda: _status_is(reborn, waiting.run_id, "failed"))
        assert (await reborn.get_run(waiting.run_id)).metadata["failureReason"] == "no_provider_took_it"
    finally:
        await reborn.aclose()
