"""Can a provider open a run in its caller's name?

funduq hands the caller's actor chain to the provider verbatim
(`forwardedProps.actorChain`) — deliberately, so the agent can verify for
itself rather than trust a summary funduq wrote. The chain is also what a
door reads to decide whose authority a request carries.

Those two facts together are the question this asks: the provider now holds,
in full, the thing a door accepts as authority. Nothing about a chain binds
it to the run it was handed for, and nothing about presenting one proves the
presenter is its head — **a chain proves origin, not possession.**

A hop used to carry an expiry, which bounded this to five minutes. That
expiry is gone (it could not do the job it looked like it was doing: a
verifier sees bytes, not a live presenter). Removing it did not open this
hole — a provider inside the window could always do this — it stopped the
window from making the gap look guarded.

**Everything here is expected to FAIL on current code.** That is the point:
it is the acceptance test for the fix, written before it. The fix is a
presenter check at the door — the seat in front of funduq authenticates
whoever is calling and hands that key in, and funduq refuses a chain whose
last hop was signed by anyone else. Each scenario prints what happened and
what should happen instead, so the same script becomes the pass/fail check
when the check lands.

    cd funduq && uv run python ../scripts/probes/probe_a_provider_can_speak_as_the_caller.py
    FUNDUQ_DATABASE_URL=postgresql+psycopg://… uv run python ../scripts/probes/probe_a_provider_can_speak_as_the_caller.py
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
from funduq.identity import new_actor_chain
from funduq.models import AgentRef
from funduq_provider_sdk import InProcessLink, ProviderIdentity, ProviderRuntime


DB = Path(tempfile.gettempdir()) / "funduq_probe_speak_as_caller.db"
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
    """Serves runs, and keeps whatever funduq forwarded — which is how the
    provider comes to hold the caller's chain in the first place."""

    def __init__(self) -> None:
        self.seen_chain: list[str] | None = None

    async def run_stream(self, name: str, run_input):
        props = getattr(run_input, "forwarded_props", None)
        if props is not None:
            chain = props.get("actorChain") if isinstance(props, dict) else getattr(props, "actorChain", None)
            if chain:
                self.seen_chain = list(chain)
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        yield {"type": "RUN_FINISHED", **ids}


class Findings:
    """Separates the properties that must hold from the one arrangement that is
    deliberate.

    The provider holding the caller's chain is not the defect — it is the design
    (`forwardedProps.actorChain`, so the agent verifies for itself rather than
    trusting a summary). Counting it as a failure would make this script
    permanently red for the wrong reason, and the first person to tidy that up
    would delete the line that explains where the exposure comes from.
    """

    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, bool]] = []

    def record(self, name: str, held: bool, detail: str, *, by_design: bool = False) -> None:
        self.rows.append((name, held, by_design))
        mark = "CONTEXT" if by_design else ("HOLDS  " if held else "BROKEN ")
        print(f"  {mark} {name}\n           {detail}\n")

    def summarize(self) -> int:
        broken = [n for n, held, by_design in self.rows if not held and not by_design]
        checked = [n for n, _h, by_design in self.rows if not by_design]
        if broken:
            print(f"{len(broken)} of {len(checked)} propert{'y' if len(broken) == 1 else 'ies'} do not hold:")
            for name in broken:
                print(f"    {name}")
            print(
                "\nExpected on current code. A door accepts a chain on the strength of\n"
                "its signatures alone, so whoever holds one speaks with its authority.\n"
                "The fix is the presenter check; when it lands, this script goes green."
            )
        else:
            print(f"every property holds ({len(checked)} checked)")
        return len(broken)


async def main() -> int:
    migrate()
    findings = Findings()
    funduq = Funduq(CoreSettings(database_url=URL, token_signing_secret="probe"))
    await funduq.start()

    caller_key = Ed25519PrivateKey.generate()
    caller_public = caller_key.public_key().public_bytes_raw().hex()
    chain = new_actor_chain(caller_key)

    agent_impl = Agent()
    identity = ProviderIdentity(Ed25519PrivateKey.generate())
    runtime = ProviderRuntime(identity, agent_impl)
    runtime.start()
    link = InProcessLink(funduq, runtime)
    await funduq.attach_provider(link)
    await funduq.register_agents(link, [{"name": "assistant"}])
    agent = AgentRef(provider_key=identity.public_key, name="assistant")

    try:
        # --- 1. the caller speaks, and funduq hands its chain to the provider
        print("\n[1] the caller opens a run carrying its chain")
        handle = await funduq.start_run(
            agent,
            {"messages": [{"id": "m1", "role": "user", "content": "summarise this document"}]},
            metadata={"actorChain": chain},
        )
        async for _ in handle.events():
            pass
        async with funduq.session() as session:
            caller_run = await repo.get_run(session, handle.run_id)
        print(
            f"           run {handle.run_id[:8]}… recorded with head_key "
            f"{(caller_run.head_key or '')[:16]}… (the caller)\n"
        )

        findings.record(
            "the provider holds the caller's chain, byte for byte",
            agent_impl.seen_chain == chain,
            "by design — it arrives in forwardedProps so the agent can verify for itself "
            "instead of trusting a summary funduq wrote. Not the defect; the precondition "
            "for the two below"
            if agent_impl.seen_chain == chain
            else "the provider did not receive the chain — the rest of this probe assumes it does",
            by_design=True,
        )

        # --- 2. the provider replays it on work the caller never asked for
        print("[2] the provider presents that same chain at a door, for its own work")
        stolen = await funduq.start_run(
            agent,
            {"messages": [{"id": "m2", "role": "user", "content": "transfer the budget"}]},
            metadata={"actorChain": agent_impl.seen_chain},
        )
        async for _ in stolen.events():
            pass
        async with funduq.session() as session:
            stolen_run = await repo.get_run(session, stolen.run_id)

        findings.record(
            "a chain presented by someone who is not its head is refused",
            stolen_run.head_key != caller_public,
            f"accepted: run {stolen.run_id[:8]}… is recorded under head_key "
            f"{(stolen_run.head_key or '')[:16]}… — the caller's key — for a message the "
            "caller never sent. The presenter was the provider; nothing at the door asked "
            "who was presenting"
            if stolen_run.head_key == caller_public
            else f"refused, or recorded under {stolen_run.head_key}",
        )

        # --- 3. and the record cannot tell the two apart
        print("[3] can the record distinguish the caller's run from the provider's?")
        same = (
            caller_run.head_key == stolen_run.head_key
            and caller_run.provider_key == stolen_run.provider_key
        )
        findings.record(
            "the record shows who actually presented each run",
            not same,
            "identical in every field that carries authority: same head_key, same agent. "
            "An auditor reading these two rows cannot tell that the caller opened one of "
            "them and the provider opened the other in its name"
            if same
            else "the two runs differ in the record",
        )

        return findings.summarize()
    finally:
        funduq.detach_provider(identity.public_key, link)
        await runtime.aclose()
        await funduq.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
