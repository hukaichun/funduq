"""What holds a conversation, and what releases it.

One thread has one active run. The next utterance of a conversation is
handed over when the one before it **finishes** — not when it is answered,
and not when it is claimed. An unanswered offer holds it; a declined offer
holds it; a claimed run still running holds it. Nothing wider than the one
conversation waits.

Measured rather than reasoned about, and the first two attempts measured the
harness instead — see the note on `_settle`.
"""

from __future__ import annotations

import asyncio
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from funduq.core import Funduq
from funduq.models import AgentRef
from funduq_provider_sdk import InProcessLink, ProviderIdentity, ProviderRuntime
from funduq_contract import Registration


class _Identity(ProviderIdentity):

    def __init__(self) -> None:
        super().__init__(Ed25519PrivateKey.generate())


class _GatedAgent:
    """Holds every run open until released, which is what makes "what is
    funduq waiting on" observable at all."""

    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def run_stream(self, agent_name: str, run_input: Any):
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        await self.release.wait()
        yield {"type": "RUN_FINISHED", **ids}


class _SlowLink(InProcessLink):
    """Answers offers only when let through."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.gate = asyncio.Event()
        self.verdict: bool | None = None
        self.offered: list[str] = []

    async def deliver(self, run) -> None:
        self.offered.append(run.run_id)
        if self.verdict is not None:
            self._funduq.answer_offer(
                run.run_id, self.verdict, provider_key=self.public_key
            )
            return
        await self.gate.wait()
        await super().deliver(run)


async def _settle() -> None:
    """Real time, not `sleep(0)`.

    A lane writes its `offering` row before the offer leaves, and on SQLite
    that round trip happens on another thread. Yielding the loop without
    letting the clock move measures the probe rather than funduq — which is
    exactly how an earlier version of this reported that a run on an unrelated
    thread was blocked, when nothing of the sort was happening.
    """
    for _ in range(10):
        await asyncio.sleep(0.02)


async def _serving(funduq: Funduq, agent_impl=None, link_class=_SlowLink):
    identity = _Identity()
    agent_impl = agent_impl or _GatedAgent()
    runtime = ProviderRuntime(identity, agent_impl)
    runtime.start()
    link = link_class(funduq, runtime)
    await funduq.attach_provider(link)
    await funduq.register_agents(link, [Registration(name="translator")])
    return link, runtime, AgentRef(provider_key=identity.public_key, name="translator")


async def test_an_unanswered_offer_holds_its_own_conversation_and_nothing_else(
    funduq: Funduq,
) -> None:
    agent_impl = _GatedAgent()
    link, runtime, agent = await _serving(funduq, agent_impl)
    try:
        first = await funduq.start_run(agent, {"messages": []})
        await _settle()
        assert link.offered == [first.run_id]

        same_thread = await funduq.start_run(
            agent, {"messages": []}, thread_id=first.thread_id
        )
        other_thread = await funduq.start_run(agent, {"messages": []})
        await _settle()

        assert same_thread.run_id not in link.offered, (
            "the next utterance of a conversation was handed over while the one "
            "before it was still unanswered"
        )
        assert other_thread.run_id in link.offered, (
            "an unrelated conversation waited too. Nothing wider than the one "
            "conversation is supposed to; a slow answer would otherwise stall "
            "every caller on the link"
        )
        assert (await funduq.get_run(same_thread.run_id)).status == "queued"

        link.gate.set()
        await _settle()

        assert same_thread.run_id not in link.offered, (
            "claiming opened the gate. One thread has one active run: the next "
            "utterance waits for the turn to finish, not for it to be accepted"
        )
        assert (await funduq.get_run(first.run_id)).status == "running"

        agent_impl.release.set()
        await _settle()

        assert same_thread.run_id in link.offered, (
            "the turn finished and its conversation stayed held"
        )
    finally:
        funduq.detach_all_for(link.public_key)
        await runtime.aclose(cancel_in_flight=True)


async def test_a_decline_answers_promptly_and_holds_the_conversation_anyway(
    funduq: Funduq,
) -> None:
    """A declined run goes back to `queued` at the head of its thread, so the
    utterance behind it keeps waiting — the order is the thing being
    protected."""
    link, runtime, agent = await _serving(funduq)
    link.verdict = False
    try:
        first = await funduq.start_run(agent, {"messages": []})
        await _settle()
        behind = await funduq.start_run(agent, {"messages": []}, thread_id=first.thread_id)
        await _settle()

        assert first.run_id in link.offered
        assert behind.run_id not in link.offered
        assert (await funduq.get_run(first.run_id)).status == "queued"
        assert (await funduq.get_run(behind.run_id)).status == "queued"
    finally:
        funduq.detach_all_for(link.public_key)
        await runtime.aclose(cancel_in_flight=True)
