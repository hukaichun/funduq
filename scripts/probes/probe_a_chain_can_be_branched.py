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

Verification alone can never catch this — there is no signature over what is
absent — so that row is marked LIMIT rather than counted as a failure. What a
branch cannot survive is **funduq's own dispatch hop**, which names the agent
it dispatched to: an agent is `(provider_key, name)`, and that provider key is
exactly the key that signs the next hop when the provider extends honestly, so
the hop and its successor contradict each other. This script pins that, and the
two properties that genuinely resist, so none of them can be lost silently.

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
from funduq.identity import FunduqIdentity
from funduq.core import Funduq
from funduq.identity import (
    InvalidChain,
    extend_chain,
    new_chain,
    verify_chain,
)
from funduq.models import AgentRef
from funduq_contract import Registration
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
    """Separates properties that must hold from the one that never can.

    Verification cannot detect a removal — that is a permanent property of
    signatures over a hash chain, not a defect awaiting a fix, so counting it
    as a failure would leave this script red forever and the first person to
    tidy that up would delete the record of *why* funduq's dispatch hops
    exist. It is marked LIMIT and the rest are pass/fail.
    """

    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, bool]] = []

    def record(self, name: str, held: bool, detail: str, *, permanent: bool = False) -> None:
        self.rows.append((name, held, permanent))
        mark = "LIMIT  " if permanent else ("HOLDS  " if held else "BROKEN ")
        print(f"  {mark} {name}\n           {detail}\n")

    def summarize(self) -> int:
        broken = [n for n, held, perm in self.rows if not held and not perm]
        checked = [n for n, _h, perm in self.rows if not perm]
        if broken:
            print(f"{len(broken)} of {len(checked)} properties do not hold:")
            for name in broken:
                print(f"    {name}")
            print(
                "\nREGRESSION. Verification never detects a removal, so what a branch\n"
                "cannot survive is funduq's own dispatch hop: it names the agent it\n"
                "dispatched to, and that provider key is exactly the key that signs the\n"
                "next hop when the provider extends honestly."
            )
        else:
            print(f"every property holds ({len(checked)} checked)")
        return len(broken)


def hexk(key: Ed25519PrivateKey) -> str:
    return key.public_key().public_bytes_raw().hex()


async def main() -> int:
    migrate()
    findings = Findings()
    funduq = Funduq(CoreSettings(
        database_url=URL,
        token_signing_secret="probe",
        identity_private_key=FunduqIdentity.generate_hex(),
    ))
    await funduq.start()

    caller, a_key, b_key = (Ed25519PrivateKey.generate() for _ in range(3))

    identity = ProviderIdentity(Ed25519PrivateKey.generate())
    runtime = ProviderRuntime(identity, Agent())
    runtime.start()
    link = InProcessLink(funduq, runtime)
    await funduq.attach_provider(link)
    await funduq.register_agents(link, [Registration(name="assistant")])
    agent = AgentRef(provider_key=identity.public_key, name="assistant")

    try:
        # --- 1. the honest path
        print("\n[1] the honest path: caller → A → B")
        honest = extend_chain(b_key, extend_chain(a_key, new_chain(caller)))
        honest_keys = verify_chain(honest).actor_public_keys
        print(f"           three hops, in order: {[k[:8] for k in honest_keys]}\n")

        # --- 2. B rebuilds it without A
        print("[2] B rebuilds it as caller → B, using hop zero it already holds")
        branched = extend_chain(b_key, [honest[0]])
        result = verify_chain(branched)
        findings.record(
            "a chain records every hand it passed through",
            hexk(a_key) in result.actor_public_keys,
            f"A is gone and the branch verifies: {[k[:8] for k in result.actor_public_keys]}, "
            f"head still the caller ({result.head == hexk(caller)}). Nothing was forged — "
            "B hashed hop zero's own token and signed a hop pointing at it. Verification "
            "can never catch this on its own: it proves nobody was added, and there is no "
            "signature over what is absent",
            permanent=True,
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
        stored = run.actor_chain or []
        # As dispatched: every hop the branching party presented, and then the
        # one funduq signs naming where it sent the run. The record used to
        # keep the presented chain alone, which left funduq's own books unable
        # to tell a run it had dispatched from a chain that reached it having
        # passed no witness at all — the agent always got the longer one and
        # only the record was short.
        kept_what_arrived = stored[: len(branched)] == branched
        witnessed = (
            len(stored) == len(branched) + 1
            and verify_chain(stored).hops[-1].dispatched_to is not None
        )
        findings.record(
            "the record keeps the chain as dispatched",
            kept_what_arrived and witnessed,
            f"run {handle.run_id[:8]}… keeps all {len(branched)} hop(s) it arrived with "
            f"under head_key {(run.head_key or '')[:16]}…, and funduq's own dispatch hop "
            "after them — so an auditor reads both the path that was claimed and the fact "
            "that this one passed a witness"
            if kept_what_arrived and witnessed
            else f"stored {stored!r}, presented {branched!r}",
        )
        # --- 4. what funduq's own hop makes visible
        print("[4] B does the same thing to a chain that went out through funduq")
        # As A would have received it: the caller's hop, then funduq's, naming
        # the agent it dispatched to.
        as_dispatched = funduq.identity.dispatch_hop(new_chain(caller), agent)
        rebranched = extend_chain(b_key, as_dispatched)
        # Read off the verified chain, not off the JWT. Hand-decoding here was
        # the same posture that produced the bug this step exists for.
        claimed = verify_chain(as_dispatched).hops[-1].dispatched_to

        # This comparison used to be performed *here*, by the probe, because
        # `verify_chain` wrote `dispatchedTo` and never read it: the property
        # was available and nothing enforced it. It is the verifier's now, so
        # what this step checks is that the verifier refuses — a probe that
        # keeps doing the work itself would stay green if the rule were ever
        # taken back out.
        try:
            verify_chain(rebranched)
            refused = None
        except InvalidChain as e:
            refused = str(e)

        findings.record(
            "an erased hand is refused",
            refused is not None,
            f"funduq's hop says it dispatched to provider {claimed.provider_key[:8]}… "
            f"(agent '{claimed.name}'), and verification refuses the hop after it: "
            f"{refused} — an agent is (provider_key, name), and that provider key is "
            "exactly the key that signs the next hop when it extends honestly, so the "
            "hop and its successor check each other"
            if refused is not None
            else "verification accepted the branch — the rule is not being applied",
        )

        # --- 5. what the design does guarantee
        print("[5] what resists")
        try:
            verify_chain(honest[1:])
            dropped_head = True
            detail = "a chain starting mid-way verified — the head can be dropped"
        except InvalidChain as e:
            dropped_head = False
            detail = f"refused: {str(e)[:72]}… — the first hop must carry a null prevHash, so truncation works only from the tail backwards"
        findings.record("the head cannot be dropped", not dropped_head, detail)

        spliced_ok = True
        try:
            elsewhere = new_chain(Ed25519PrivateKey.generate())
            verify_chain([*honest[:1], extend_chain(b_key, elsewhere)[-1]])
        except InvalidChain:
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
