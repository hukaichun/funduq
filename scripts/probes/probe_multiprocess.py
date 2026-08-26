"""What two funduq processes behind a load balancer actually do, today.

The baseline the horizontal-scaling work is measured against (see
design/broker-horizontal-scaling.md, kept in git history at d78d063 rather
than in the tree). Everything here is expected to *fail* on
current code — that is the point. Each scenario prints what happened and what
the design says should happen instead, so the same script becomes the pass/fail
check as each phase lands rather than being thrown away.

    cd funduq && uv run python ../scripts/probes/probe_multiprocess.py
    FUNDUQ_DATABASE_URL=postgresql+psycopg://… uv run python ../scripts/probes/probe_multiprocess.py

Two real OS processes, one database, and an LB that round-robins every call
(scripts/probes/cluster.py). An earlier version of this probe ran two `Funduq`
objects in one process, which shares an event loop and therefore proves less
than it appears to.

**Re-measured against handed-down dispatch (issue #129).** The scenarios below
used to ask what happens when a worker's `claim_work` lands on a node that did
not enqueue the run. That call is gone: funduq hands work down a link the
provider holds open, so the question changed shape rather than going away. A
link belongs to one process, so the mismatch is no longer between two calls of
one worker — it is between the node a *caller* lands on and the node the
provider is attached to. Two of the old scenarios (a booting replica, a dead
owner) are unchanged in every respect but how the run gets into flight; the
rest are new questions the old dispatch model could not ask.
"""

from __future__ import annotations

import asyncio
import os
import time

from cluster import Cluster, NodeError, ProviderClient
from funduq_provider_sdk import ProviderIdentity

RUN_INPUT = {"messages": [{"id": "m1", "role": "user", "content": "hello"}], "state": {}}


class Findings:
    """Collects one line per scenario so the summary is the probe's own
    output, not something the reader assembles by scrolling."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []

    def record(self, name: str, healthy: bool, detail: str) -> None:
        self.rows.append((name, healthy, detail))
        print(f"  {'OK  ' if healthy else 'BROKEN'} {name}: {detail}")

    def summarize(self) -> int:
        broken = [row for row in self.rows if not row[1]]
        print(f"\n{len(self.rows) - len(broken)}/{len(self.rows)} healthy, {len(broken)} broken")
        for name, _healthy, detail in broken:
            print(f"  BROKEN {name}: {detail}")
        return len(broken)


async def until(predicate, timeout: float = 2.0) -> bool:
    """Waits for something to become true, rather than sleeping a guessed
    interval — a probe that sleeps intermittently measures its own timing."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.02)
    return predicate()


async def serve(cluster: Cluster, node: str) -> tuple[ProviderClient, dict]:
    """A provider attached to one named node, with `prober` published on that link.

    Both halves of the real ceremony: a ticket fetched over a different
    connection, a signed proof, and funduq's answer checked against the pinned
    key (all inside `Cluster.attach`). A probe that skipped them would prove
    nothing about what a provider actually goes through.
    """
    identity = ProviderIdentity.generate()
    provider = await cluster.attach(identity, node=node)
    registered = await provider.register("prober")
    return provider, registered["prober"]


async def in_flight(cluster: Cluster, node: str) -> tuple[ProviderClient, dict, dict]:
    """A run genuinely in flight on `node`: offered, accepted, started, unfinished.

    Returns the provider, the agent and the run. The provider reports
    `RUN_STARTED` and then holds the run open, which is what makes it a live
    run rather than a queued one — several scenarios below are about what
    another process does to a run that is being served right now.
    """
    provider, agent = await serve(cluster, node)
    run = await cluster.call({"op": "start_run", **agent, "run_input": RUN_INPUT}, node=node)
    await until(lambda: bool(provider.offers))
    if provider.offers:
        await provider.report_event(
            run["run_id"],
            {"type": "RUN_STARTED", "threadId": run["thread_id"], "runId": run["run_id"]},
        )
        # And wait for the claim to reach the database. The status write is on
        # the run's own pipeline task, after the ack has already been answered,
        # so a scenario that starts measuring immediately measures that window
        # instead of the thing it came for.
        await until_status(cluster, run["run_id"], "running", node=node)
    return provider, agent, run


async def until_status(cluster: Cluster, run_id: str, status: str, *, node: str, timeout: float = 2.0) -> str:
    """Waits for the run row to read `status`, and returns whatever it reads in the end."""
    deadline = time.monotonic() + timeout
    while True:
        record = await cluster.call({"op": "get_run", "run_id": run_id}, node=node)
        if record["status"] == status or time.monotonic() > deadline:
            return record["status"]
        await asyncio.sleep(0.02)


async def scenario_cross_node_dispatch(cluster: Cluster, findings: Findings) -> None:
    """A caller landing on the node the provider is *not* attached to. The base
    case, and the one the port changed: with a load balancer in front, whether
    the caller's node is the one holding the link is a coin toss.
    """
    print("\n[1] a caller lands on the node that does not hold the provider's link")
    provider, agent = await serve(cluster, "a")
    run = await cluster.call({"op": "start_run", **agent, "run_input": RUN_INPUT}, node="b")
    delivered = await until(lambda: bool(provider.offers), timeout=1.5)
    record = await cluster.call({"op": "get_run", "run_id": run["run_id"]}, node="b")
    roster_b = await cluster.call({"op": "list_agents"}, node="b")
    online_on_b = [a["online"] for a in roster_b if a["name"] == agent["agent_name"]]

    findings.record(
        "a run started on B reaches a provider attached to A",
        delivered,
        f"B recorded the run {record['status']!r} "
        f"({record['metadata'].get('failureReason')}) and the provider was offered "
        f"{len(provider.offers)} run(s); B's roster reads online={online_on_b} for an "
        "agent whose link is open on A — the run is not even queued for it",
    )
    await provider.close()


async def scenario_ticket_is_process_local(cluster: Cluster, findings: Findings) -> None:
    """The admission half of the same coin toss, and the one the old probe
    could not ask at all: `claim_work` carried a token any node could verify
    from the shared secret, while a ticket is minted in one process's memory.

    A provider that fetches its ticket through the LB and then opens its link
    through the LB has no reason to land on the same process twice.
    """
    print("\n[2] a ticket issued by one node, answered at another")
    identity = ProviderIdentity.generate()
    try:
        provider = await cluster.attach(identity, node="b", ticket_from="a")
        findings.record(
            "a ticket issued on A admits a link opened on B",
            True,
            "B accepted a ticket A minted",
        )
        await provider.close()
    except NodeError as exc:
        findings.record(
            "a ticket issued on A admits a link opened on B",
            False,
            f"B refused it — {exc}. A provider behind an LB cannot open a link at all "
            "unless issue and attach happen to land on one process",
        )


async def scenario_new_replica_reaps(cluster: Cluster, findings: Findings) -> None:
    """A new replica boots while another node is mid-run — a rolling deploy,
    an autoscaler, a restarted container. Its startup reconciliation is
    database-wide, so it declares the live run failed; and the node actually
    running it never learns, so it keeps persisting events into a run the
    database says is over.

    The booting node must genuinely be fresh: `Funduq.start()` runs once per
    process by design, so calling it again on a node that already started is a
    no-op and proves nothing. (It quietly made an earlier version of this
    scenario pass.)
    """
    print("\n[3] a new replica boots mid-run")
    provider, _agent, run = await in_flight(cluster, "a")
    if not provider.offers:
        findings.record("a booting replica leaves live runs alone", False, "nothing was offered on A")
        return

    cluster.spawn("c")
    reaped = await cluster.call({"op": "funduq_start"}, node="c")
    record = await cluster.call({"op": "get_run", "run_id": run["run_id"]}, node="c")
    still_dispatching = run["run_id"] in await cluster.call({"op": "active_runs"}, node="a")

    findings.record(
        "a booting replica leaves another node's live run alone",
        run["run_id"] not in reaped["reaped"],
        f"C reaped {len(reaped['reaped'])} run(s); the run now reads {record['status']!r} "
        f"({record['metadata'].get('failureReason')}) while A is still dispatching it: {still_dispatching}",
    )

    accepted = await provider.report_event(
        run["run_id"],
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "still here"},
    )
    await asyncio.sleep(0.4)
    events = await cluster.call({"op": "get_run_events", "run_id": run["run_id"]}, node="c")
    findings.record(
        "nothing lands in a run already declared failed",
        not (record["status"] == "failed" and accepted and events),
        f"the run reads {record['status']!r}, yet A accepted a further event ({accepted}) and "
        f"{len(events)} event(s) are persisted against it — a caller polling the run and one "
        "on its stream get contradictory accounts",
    )
    await provider.close()


async def scenario_report_to_wrong_node(cluster: Cluster, findings: Findings) -> None:
    """An event reported at a node that does not hold the run.

    Under `claim_work` this was a routing accident: a worker's next request
    landed anywhere. It cannot happen by accident now — reports ride the link,
    and the link is one connection to one process — so what this measures is
    the answer a serving layer gets if it exposes reporting as an ordinary
    call, which is exactly what a stateless HTTP gateway in front of N nodes
    would do.
    """
    print("\n[4] an event reported to the node that does not hold the run")
    provider, _agent, run = await in_flight(cluster, "a")
    if not provider.offers:
        findings.record("an event reported to any node reaches the run", False, "nothing was offered on A")
        return

    accepted = await cluster.call(
        {
            "op": "report_event",
            "run_id": run["run_id"],
            "event": {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "hi"},
            "claimed_by": provider.public_key,
        },
        node="b",
    )
    await asyncio.sleep(0.3)
    events = await cluster.call({"op": "get_run_events", "run_id": run["run_id"]}, node="a")
    # The event by its own content, not by a count: the run's own RUN_STARTED
    # is still being persisted while this runs, and a count would read that as
    # the reported event arriving.
    landed = [e for e in events if e.get("delta") == "hi"]
    findings.record(
        "an event reported to any node reaches the run",
        bool(accepted) and bool(landed),
        f"B answered {accepted} and {len(landed)} copy of it is persisted against the run — "
        "B holds no such run, and the reporter is not told which node does",
    )
    await provider.close()


async def scenario_cross_node_stream(cluster: Cluster, findings: Findings) -> None:
    """A caller streaming on the node that is not dispatching the run. This is
    the read half: even when everything else works, the consumer has to receive
    what a provider reported elsewhere.
    """
    print("\n[5] consumer on the node that does not own the run")
    provider, _agent, run = await in_flight(cluster, "a")
    if not provider.offers:
        findings.record("a consumer on B sees a run owned by A", False, "nothing was offered on A")
        return

    async def produce() -> None:
        await asyncio.sleep(0.2)
        for delta in ("one", "two"):
            await provider.report_event(
                run["run_id"],
                {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": delta},
            )
        await provider.finish_run(run["run_id"])

    on_b, _ = await asyncio.gather(cluster.subscribe(run["run_id"], node="b", timeout=3.0), produce())
    findings.record(
        "a consumer on B sees a run owned by A",
        len(on_b) >= 2,
        f"B's stream yielded {len(on_b)} event(s) for a run producing on A",
    )
    await provider.close()


async def scenario_owner_dies(cluster: Cluster, findings: Findings) -> None:
    """The node holding a run is SIGKILLed. Nobody finishes the run, and no
    surviving node has any way to tell "its owner is dead" from "its provider
    is quiet" — the only cleanup that keys off a node being gone is the *next*
    boot's reconciliation.

    Handed-down dispatch adds a second casualty the pull model did not have:
    the provider's link died with the process. So the provider is also asked
    here to do the obvious recovery — re-attach to the survivor — and the run
    it was in the middle of serving is looked for from there.
    """
    print("\n[6] the owning node dies")
    provider, _agent, run = await in_flight(cluster, "a")
    if not provider.offers:
        findings.record("a dead node's run reaches a verdict", False, "nothing was offered on A")
        return

    cluster.kill("a")
    record = await cluster.call({"op": "get_run", "run_id": run["run_id"]}, node="b")
    print(
        f"       (the row reads {record['status']!r} at the moment A dies — "
        "'offering' would mean the claim never reached the database)"
    )
    findings.record(
        "a dead node's run reaches a verdict promptly",
        record["status"] in ("failed", "cancelled"),
        f"A is gone; B leaves the run at {record['status']!r} — nothing B runs keys off "
        "a node being dead. There used to be a `sweep_once` op poked here to provoke a "
        "verdict; it could not produce one either (the clock it drove only reaped paused "
        "runs) and it is gone with that deadline.",
    )

    await provider.close()
    reattached = await cluster.attach(provider.identity, node="b")
    await reattached.register("prober")
    resumed = await until(lambda: bool(reattached.offers), timeout=1.5)
    accepted = await reattached.report_event(
        run["run_id"], {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m", "delta": "still here"}
    )
    findings.record(
        "a provider that re-attaches can carry on with the run it was serving",
        resumed or accepted,
        f"the same key re-attached to B and was offered {len(reattached.offers)} run(s); "
        f"reporting into its own half-served run answered {accepted}. The run is alive in "
        "the database and its provider is back — but the claim, the queues and the "
        "subscribers were process state on A",
    )
    await reattached.close()


async def main() -> int:
    findings = Findings()
    database_url = os.environ.get("FUNDUQ_DATABASE_URL")
    print(f"two funduq processes, one database ({(database_url or 'sqlite, throwaway file').split('://')[0]})")
    print("a caller's call lands wherever the LB sends it; a provider's link belongs to one node\n")

    async with Cluster(nodes=["a", "b"], database_url=database_url) as cluster:
        await cluster.call({"op": "funduq_start"}, node="a")
        await cluster.call({"op": "funduq_start"}, node="b")
        await scenario_cross_node_dispatch(cluster, findings)
        await scenario_ticket_is_process_local(cluster, findings)
        await scenario_new_replica_reaps(cluster, findings)
        await scenario_report_to_wrong_node(cluster, findings)
        await scenario_cross_node_stream(cluster, findings)
        await scenario_owner_dies(cluster, findings)

    return findings.summarize()


if __name__ == "__main__":
    raise SystemExit(1 if asyncio.run(main()) else 0)
