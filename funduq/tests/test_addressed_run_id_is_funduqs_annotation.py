"""`forwardedProps.funduq.addressedRunId` means funduq verified an interjection at the
door — never that a caller typed it. The record is read back on restart
(#122), so a caller-written value there would let a caller make funduq's
decision for it.
"""

from __future__ import annotations

import asyncio

from funduq.core import Funduq
from funduq.models import AgentRef
from funduq.props import build_forwarded_props

from tests.conftest import Identity

_AGENT = AgentRef(provider_key="k" * 64, name="a")


def test_a_caller_written_funduq_key_is_removed():
    props = build_forwarded_props("s", "run_1", _AGENT, False, {"funduq": {"addressedRunId": "forged"}, "theirs": 1})
    assert props == {"theirs": 1}


def test_a_declared_target_replaces_whatever_the_caller_wrote_under_funduqs_key():
    props = build_forwarded_props(
        "s", "run_1", _AGENT, False, {"funduq": {"addressedRunId": "forged", "kyok": "fake"}}, addressed_run_id="run_target"
    )
    assert props == {"funduq": {"addressedRunId": "run_target"}}


def test_nothing_to_add_leaves_the_callers_props_as_they_were():
    assert build_forwarded_props("s", "run_1", _AGENT, False, {"theirs": 1}) == {"theirs": 1}
    assert build_forwarded_props("s", "run_1", _AGENT, False, None) is None
    assert build_forwarded_props("s", "run_1", _AGENT, False, {}) == {}
    assert build_forwarded_props("s", "run_1", _AGENT, False, {"funduq": {"addressedRunId": "forged"}}) == {}


def test_a_top_level_addressed_run_id_is_the_callers_own_word():
    """Outside funduq's key the same name means nothing to funduq: relayed verbatim, never read back."""
    assert build_forwarded_props("s", "run_1", _AGENT, False, {"addressedRunId": "theirs"}) == {"addressedRunId": "theirs"}


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
        while not await predicate():
            await asyncio.sleep(0.01)


async def _status_is(funduq, run_id: str, status: str) -> bool:
    run = await funduq.get_run(run_id)
    return run is not None and run.status == status


async def test_a_recovered_run_is_not_made_an_interjection_by_its_callers_props(funduq, attach, settings):
    """The caller wrote `forwardedProps.funduq.addressedRunId` naming the running turn; no
    interjection was declared. After a restart the run is an ordinary queued
    turn — not failed as a lost interjection, not delivered as one."""
    identity = Identity()
    await attach(identity, NeverFinishes(), ["a"], max_concurrent_runs=1)
    agent = AgentRef(provider_key=identity.public_key, name="a")
    busy = await funduq.start_run(agent, {"messages": []})
    await _until(lambda: _status_is(funduq, busy.run_id, "running"))
    waiting = await funduq.start_run(
        agent,
        {"messages": [], "forwardedProps": {"funduq": {"addressedRunId": busy.run_id}, "theirs": True}},
        thread_id=busy.thread_id,
    )
    assert "funduq" not in (await funduq.get_run(waiting.run_id)).forwarded_props

    reborn = Funduq(settings)
    runtime = None
    try:
        await reborn.start()
        assert (await reborn.get_run(waiting.run_id)).status == "queued"

        from funduq_provider_sdk import InProcessLink, ProviderRuntime
        from tests.conftest import publish_agents

        provider = Receives()
        runtime = ProviderRuntime(identity, provider)
        runtime.start()
        await publish_agents(reborn, InProcessLink(reborn, runtime), ["a"])
        await _until(lambda: _status_is(reborn, waiting.run_id, "completed"))
        assert provider.rounds[0]["forwardedProps"] == {"theirs": True}
    finally:
        if runtime is not None:
            await runtime.aclose(cancel_in_flight=True)
        await reborn.aclose()
