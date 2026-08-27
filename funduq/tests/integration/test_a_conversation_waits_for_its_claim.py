"""What an unanswered offer holds up, and what it does not.

`writing-a-transport.md` calls this the one timing funduq depends on — a
thread's delivery order survives a transport that guarantees none because an
offer's answer comes back before the next utterance is handed over. Nothing
pinned it, and the sentence describing it was imprecise in a way that matters
to a provider author: what releases the conversation is the **claim**, not the
answer. A declined offer answers promptly and holds the thread anyway.

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


class _Identity(ProviderIdentity):

    def __init__(self) -> None:
        super().__init__(Ed25519PrivateKey.generate())


class _Agent:

    async def run_stream(self, agent_name: str, run_input: Any):
        yield {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "hi"}


class _SlowLink(InProcessLink):
    """Answers offers only when let through, which is what makes "what is
    funduq waiting on" observable at all."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.gate = asyncio.Event()
        self.verdict: bool | None = None
        self.offered: list[str] = []

    async def offer(self, run) -> bool:
        self.offered.append(run.run_id)
        if self.verdict is not None:
            return self.verdict
        await self.gate.wait()
        return await super().offer(run)


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


async def _serving(funduq: Funduq, link_class=_SlowLink):
    identity = _Identity()
    runtime = ProviderRuntime(identity, _Agent())
    runtime.start()
    link = link_class(funduq, runtime)
    await funduq.attach_provider(link)
    await funduq.register_agents(link, [{"name": "translator"}])
    return link, runtime, AgentRef(provider_key=identity.public_key, name="translator")


async def test_an_unanswered_offer_holds_its_own_conversation_and_nothing_else(
    funduq: Funduq,
) -> None:
    link, runtime, agent = await _serving(funduq)
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
            "before it was still unanswered — the ordering the whole three-valued "
            "answer exists to protect"
        )
        assert other_thread.run_id in link.offered, (
            "an unrelated conversation waited too. Nothing wider than the one "
            "conversation is supposed to; a slow answer would otherwise stall "
            "every caller on the link"
        )
        assert (await funduq.get_run(same_thread.run_id)).status == "queued"
        assert (await funduq.get_run(other_thread.run_id)).status == "offering"

        link.gate.set()
        await _settle()

        assert same_thread.run_id in link.offered
    finally:
        funduq.detach_all_for(link.public_key)
        await runtime.aclose(cancel_in_flight=True)


async def test_a_decline_answers_promptly_and_holds_the_conversation_anyway(
    funduq: Funduq,
) -> None:
    """What releases the conversation is the claim, not the answer.

    A declined run goes back to `queued` at the head of its thread, so the
    utterance behind it keeps waiting — correctly, since the order is the
    thing being protected, but not what "held until this answer lands" says.
    """
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
