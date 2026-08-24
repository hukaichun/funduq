"""Can a chain be rewritten to leave someone out?

Verification proves nobody was *inserted*, *reordered*, or *spliced in from
another chain*. It does not prove nobody was **removed**, and completeness is
what an audit wants.

`caller → A → B`, and B rebuilds it as `caller → B`. Every signature in the
result is genuine and every link is genuine: B holds hop zero's full token, so
it can hash it and sign its own hop pointing at it. Nothing is forged. The
chain is *branched*, and the branch verifies.

Two things resist. The **head** cannot be dropped — a chain whose first hop
carries a `prevHash` is refused, so truncation only works from the tail
backwards. And once a door checks the presenter, B cannot drop **itself**
either, because it has to sign the hop it presents. What is left in between —
everyone between the head and the presenter — can be erased at will.

`actor-chain.md` records the narrow case of this (a silent hop: a forwarder
erasing *itself*, "an omission, not a break"). The general case is worse than
the page suggests: a party can erase *someone else*, and the result reads
exactly like a chain where that party was never there.

This is **not** what the presenter check fixes — that check answers "are you
who you say you are", and here B does not lie about being B. Kept as its own
probe so it cannot quietly redden the presenter check's acceptance test.

**Expected to fail on current code**, except the two properties that genuinely
hold, which are asserted here so a future change cannot lose them silently.

    cd funduq && uv run python ../scripts/probes/probe_a_chain_can_be_branched.py
    FUNDUQ_DATABASE_URL=postgresql+psycopg://… uv run python ../scripts/probes/probe_a_chain_can_be_branched.py
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from funduq import repo
from funduq.config import CoreSettings
from funduq.core import Funduq
from funduq.identity import (
    InvalidActorChain,
    extend_actor_chain,
    new_actor_chain,
    verify_actor_chain,
)
from funduq.models import AgentRef
from funduq_provider_sdk import InProcessLink, ProviderIdentity, ProviderRuntime


DB = Path(tempfile.gettempdir()) / "funduq_probe_branched_chain.db"
URL = os.environ.get("FUNDUQ_DATABASE_URL") or f"sqlite+aiosqlite:///{DB}"


def migrate() -> None:
    if URL.startswith("sqlite"):
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(DB) + suffix)
            if p.exists():
                p.unlink()
    os.environ["FUNDUQ_DATABASE_URL"] = URL
    cfg = Config()
    cfg.set_main_option("script_location", "funduq:alembic")
    command.upgrade(cfg, "head")


class Agent:
    async def run_stream(self, name: str, run_input):
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        yield {"type": "RUN_FINISHED", **ids}


class Findings:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool]] = []

    def record(self, name: str, held: bool, detail: str) -> None:
        self.rows.append((name, held))
        print(f"  {'HOLDS  ' if held else 'BROKEN '} {name}\n           {detail}\n")

    def summarize(self) -> int:
        broken = [n for n, held in self.rows if not held]
        if broken:
            print(f"{len(broken)} of {len(self.rows)} properties do not hold:")
            for name in broken:
                print(f"    {name}")
            print(
                "\nExpected on current code. A chain's completeness is not verifiable:\n"
                "signatures and links prove nobody was added, never that nobody was\n"
                "removed. The presenter check does not address this — B is honestly B.\n"
                "What would: funduq signing each dispatch with the agent it dispatched\n"
                "to, so a kept funduq hop contradicts a branch and a dropped one leaves\n"
                "a gap a consumer can require against."
            )
        else:
            print(f"every property holds ({len(self.rows)} checked)")
        return len(broken)


def hexk(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes_raw().hex()


async def main() -> int:
    migrate()
    findings = Findings()
    funduq = Funduq(CoreSettings(database_url=URL, token_signing_secret="probe"))
    await funduq.start()

    caller, a_key, b_key = (Ed25519PrivateKey.generate() for _ in range(3))

    identity = ProviderIdentity(Ed25519PrivateKey.generate())
    runtime = ProviderRuntime(identity, Agent())
    runtime.start()
    link = InProcessLink(funduq, runtime)
    await funduq.attach_provider(link)
    await funduq.register_agents(link, [{"name": "assistant"}])
    agent = AgentRef(provider_key=identity.public_key, name="assistant")

    try:
        # --- 1. the honest path
        print("\n[1] the honest path: caller → A → B")
        honest = extend_actor_chain(b_key, extend_actor_chain(a_key, new_actor_chain(caller)))
        honest_keys = verify_actor_chain(honest).actor_public_keys
        print(f"           three hops, in order: {[k[:8] for k in honest_keys]}\n")

        # --- 2. B rebuilds it without A
        print("[2] B rebuilds it as caller → B, using hop zero it already holds")
        branched = extend_actor_chain(b_key, [honest[0]])
        result = verify_actor_chain(branched)
        findings.record(
            "a chain records every hand it passed through",
            hexk(a_key) in result.actor_public_keys,
            f"A is gone and the branch verifies: {[k[:8] for k in result.actor_public_keys]}, "
            f"head still the caller ({result.head == hexk(caller)}). Nothing was forged — "
            "B hashed hop zero's own token and signed a hop pointing at it",
        )

        # --- 3. the door takes it
        print("[3] the door takes the branch")
        handle = await funduq.start_run(
            agent,
            {"messages": [{"id": "m1", "role": "user", "content": "act on the caller's behalf"}]},
            metadata={"actorChain": branched},
        )
        async for _ in handle.events():
            pass
        async with funduq.session() as session:
            run = await repo.get_run(session, handle.run_id)
        findings.record(
            "the record keeps the chain that was presented",
            run.actor_chain == branched,
            f"run {handle.run_id[:8]}… keeps all {len(run.actor_chain or [])} hop(s) it "
            f"arrived with, under head_key {(run.head_key or '')[:16]}… — so an auditor can "
            "at least read the path that was claimed, which was impossible while only the "
            "head was stored"
            if run.actor_chain == branched
            else f"stored {run.actor_chain!r}, presented {branched!r}",
        )
        findings.record(
            "the record shows the hands the work actually passed through",
            False,
            "the stored chain is the branched one: A is absent from it exactly as A was "
            "absent from what B presented. Keeping the chain makes the claim auditable, "
            "not the erasure detectable — nothing on the record contradicts a chain that "
            "never mentioned A",
        )

        # --- 4. what the design does guarantee
        print("[4] what resists")
        try:
            verify_actor_chain(honest[1:])
            dropped_head = True
            detail = "a chain starting mid-way verified — the head can be dropped"
        except InvalidActorChain as e:
            dropped_head = False
            detail = f"refused: {str(e)[:72]}… — the first hop must carry a null prevHash, so truncation works only from the tail backwards"
        findings.record("the head cannot be dropped", not dropped_head, detail)

        spliced_ok = True
        try:
            elsewhere = new_actor_chain(Ed25519PrivateKey.generate())
            verify_actor_chain([*honest[:1], extend_actor_chain(b_key, elsewhere)[-1]])
        except InvalidActorChain:
            spliced_ok = False
        findings.record(
            "a hop from another chain cannot be grafted on",
            not spliced_ok,
            "refused — prevHash ties each hop to this chain's own tail, so a branch can only "
            "be built from hops the branching party genuinely received"
            if not spliced_ok
            else "a foreign hop verified",
        )

        return findings.summarize()
    finally:
        funduq.detach_provider(identity.public_key, link)
        await runtime.aclose()
        await funduq.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
