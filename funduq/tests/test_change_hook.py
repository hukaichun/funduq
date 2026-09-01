from __future__ import annotations

import ast
import asyncio
import logging
import time
from pathlib import Path

import pytest

from tests.conftest import publish_offline
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from funduq.changes import RosterChanged, RunStatusChanged
from funduq.core import Funduq
from funduq_provider_sdk import ProviderIdentity
from funduq_contract import Registration

FUNDUQ_PACKAGE = Path(__file__).resolve().parent.parent / "funduq"


async def _register(funduq: Funduq, name: str = "echo"):
    identity = ProviderIdentity.generate()
    registration = await publish_offline(funduq, identity, [Registration(name=name)])
    return registration[name], identity


class _Provider:
    async def run_stream(self, agent: str, run_input: dict):
        yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_FINISHED", "threadId": run_input.thread_id, "runId": run_input.run_id}


async def _until(predicate, timeout: float = 5.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


async def test_publishing_changes_the_roster_and_opening_a_link_does_not(
    funduq: Funduq, attach
) -> None:
    """Opening a link puts nothing on the roster — it proves a key and
    nothing else. Publishing is the act that changes what anyone can see,
    and taking the link down is the act that changes it back."""
    agent, identity = await _register(funduq)
    seen: list = []
    funduq.on_change(seen.append)

    runtime, link = await attach(identity, _Provider(), [])
    assert seen == [], "a link with nothing published changes no roster"

    await funduq.register_agents(link, [Registration(name=agent.name)])
    assert seen == [RosterChanged()]

    funduq.detach_all_for(agent.provider_key)
    assert seen == [RosterChanged(), RosterChanged()]


async def test_a_run_reports_every_status_it_moves_through(funduq: Funduq, attach) -> None:
    seen: list = []
    funduq.on_change(lambda e: seen.append(e) if isinstance(e, RunStatusChanged) else None)

    agent, _identity = await _register(funduq)
    await attach(_identity, _Provider(), [agent.name])
    handle = await funduq.start_run(agent, {"messages": []})
    [event async for event in handle.events()]
    await _until(lambda: any(e.status == "completed" for e in seen))

    assert [e.status for e in seen] == ["offering", "running", "completed"]
    assert {e.run_id for e in seen} == {handle.run_id}


class _Decliner:
    """A provider with no room right now: it answers every offer "not me, not
    yet" — the answer that sends a run back to the queue."""

    public_key = "pk_decliner"
    max_concurrent_runs = None

    def __init__(self) -> None:
        self.offered: list[str] = []

    async def deliver(self, run) -> bool:
        self.offered.append(run.run_id)
        return False

    async def cancel(self, run_id: str) -> bool:
        return True
async def test_a_declined_run_is_reported_back_where_it_came_from(funduq: Funduq) -> None:
    """The dispatch window has two ends and the record follows both. A run
    handed to a provider is "offering"; a provider that declines it leaves it
    exactly where it was, and saying so is the only way a reader can tell an
    offer still out from one that came back."""
    seen: list = []
    funduq.on_change(lambda e: seen.append(e.status) if isinstance(e, RunStatusChanged) else None)

    agent, _identity = await _register(funduq, "declined")
    provider = _Decliner()
    funduq.broker.register_provider({agent: provider})
    handle = await funduq.start_run(agent, {"messages": []})

    await _until(lambda: seen[:2] == ["offering", "queued"])
    run = await funduq.get_run(handle.run_id)
    assert run.status == "queued"
    assert provider.offered == [handle.run_id]


async def test_unsubscribing_stops_it(funduq: Funduq) -> None:
    seen: list = []
    unsubscribe = funduq.on_change(seen.append)

    # Two changes per registration: publishing puts it on the roster, and
    # closing the link takes it off again — which is the only way to reach
    # registered-but-offline now.
    await _register(funduq, "first")
    unsubscribe()
    await _register(funduq, "second")

    assert seen == [RosterChanged(), RosterChanged()]


async def test_a_subscriber_that_raises_does_not_break_the_thing_that_notified_it(
    funduq: Funduq, caplog
) -> None:
    caplog.set_level(logging.ERROR, logger="funduq.core")

    def explode(event) -> None:
        raise RuntimeError("subscriber is broken")

    funduq.on_change(explode)
    survivor: list = []
    funduq.on_change(survivor.append)

    agent, _ = await _register(funduq)

    assert agent
    assert survivor == [RosterChanged(), RosterChanged()]
    assert "on_change subscriber raised" in caplog.text


async def test_events_arrive_before_the_call_that_caused_them_returns(funduq: Funduq) -> None:
    seen: list = []
    funduq.on_change(seen.append)

    await _register(funduq)

    assert seen


def test_nothing_moves_a_run_status_behind_the_hook() -> None:
    offenders = []
    for module in sorted(FUNDUQ_PACKAGE.rglob("*.py")):
        if module.name in ("repo.py", "core.py"):
            continue
        for node in ast.walk(ast.parse(module.read_text())):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "mark_run_status"
                and isinstance(node.value, ast.Name)
                and node.value.id == "repo"
            ):
                offenders.append(f"{module.name}:{node.lineno}")

    assert not offenders, (
        f"these call repo.mark_run_status directly: {offenders}. Use "
        "Funduq.mark_run_status, or the change is made without anyone watching "
        "being told — see funduq/changes.py."
    )
