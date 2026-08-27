"""funduq#214, end to end: a provider whose socket drops mid-run and comes back.

The deployment this protects is the architecture's own favourite — a provider
behind NAT on a consumer connection, the party outbound dispatch exists for.
For that party a two-second blip is weather, and before this it cost the
caller its run and the provider an `abandoned` mark for work it was still
doing and about to finish.

Three things had to change together, which is why it was never a kwarg: core
had to stop welding "this link is gone" to "give up on what it holds", the
runtime had to stop dropping events produced while no link was attached, and
the protocol had to carry enough for the two sides to agree where they were.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from funduq.core import Funduq
from funduq.models import AgentRef
from funduq_provider_sdk import ProviderIdentity

from tests.test_protocol_loopback import Loopback, _ReportingRuntimeLink


class _Identity(ProviderIdentity):

    def __init__(self) -> None:
        super().__init__(Ed25519PrivateKey.generate())


class Halting:
    """Says one thing, waits to be let go, then finishes."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.go = asyncio.Event()

    async def run_stream(self, agent_name: str, run_input: Any):
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        yield {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "before"}
        self.started.set()
        await self.go.wait()
        yield {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m2", "delta": "after"}
        yield {"type": "RUN_FINISHED", **ids}


@pytest.fixture
def graceful(funduq: Funduq):
    """A deployment that forgives a blip. Zero — no grace at all — is the
    default and what every other test in this suite runs under."""
    before = funduq.broker.provider_grace_seconds
    funduq.broker.provider_grace_seconds = 30.0
    yield funduq
    funduq.broker.provider_grace_seconds = before


async def _deltas(handle) -> list[str]:
    out = []
    async for event in handle.events():
        dump = getattr(event, "model_dump", None)
        body = dump(by_alias=True) if dump else event
        if body.get("delta"):
            out.append(body["delta"])
    return out


async def test_a_dropped_socket_no_longer_ends_a_run_the_provider_is_still_doing(
    graceful: Funduq,
) -> None:
    agent = Halting()
    link = Loopback(graceful, _Identity(), agent)
    link.runtime.link = _ReportingRuntimeLink(link)
    await link.open()
    await link.register(["translator"])

    handle = await graceful.start_run(
        AgentRef(provider_key=link.public_key, name="translator"), {"messages": []}
    )
    await asyncio.wait_for(agent.started.wait(), 2)

    await link.drop()
    agent.go.set()
    for _ in range(10):
        await asyncio.sleep(0.01)

    assert (await graceful.get_run(handle.run_id)).status == "running", (
        "the run was settled while its provider was merely off the wire — the "
        "outcome funduq had not observed"
    )

    await link.reconnect()
    deltas = await _deltas(handle)

    assert deltas == ["before", "after"], (
        "the caller should see the whole stream: what arrived before the blip, "
        "and what the provider produced while it was away"
    )
    assert (await graceful.get_run(handle.run_id)).status == "completed"
    assert graceful.broker.quality()[link.public_key].abandoned == 0

    await link.close()


async def test_a_provider_that_does_not_come_back_is_still_recorded_as_abandoning(
    graceful: Funduq,
) -> None:
    """The grace forgives a blip; it does not forgive leaving. Shortened here
    rather than waited out — the clock is a value, which is the point of it
    being a clock over a fact funduq owns."""
    agent = Halting()
    link = Loopback(graceful, _Identity(), agent)
    link.runtime.link = _ReportingRuntimeLink(link)
    await link.open()
    await link.register(["translator"])

    handle = await graceful.start_run(
        AgentRef(provider_key=link.public_key, name="translator"), {"messages": []}
    )
    await asyncio.wait_for(agent.started.wait(), 2)
    await link.drop()

    graceful.broker.provider_grace_seconds = 0.0001
    for _ in range(20):
        graceful.broker.expire_gone_providers(0.0001)
        await asyncio.sleep(0.01)

    await _deltas(handle)
    run = await graceful.get_run(handle.run_id)

    assert run.status == "failed"
    assert run.metadata["failureReason"] == "provider_left_holding_it"
    assert graceful.broker.quality()[link.public_key].abandoned == 1

    agent.go.set()
    await link.close()
