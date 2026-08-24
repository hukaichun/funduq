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

The fix is the **presenter check**: the seat in front of funduq
authenticates whoever is calling and hands that key in, and funduq refuses
a chain whose last hop was signed by anyone else. This script was written
before it, red, as its acceptance test; it now runs the same scenarios
with a seat in place and is green. Each scenario still prints what
happened, so a regression reads as prose rather than a failed assert.

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
from funduq.identity import FunduqIdentity
from funduq.core import Funduq
from funduq.identity import InvalidActorChain, new_actor_chain
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
                "\nREGRESSION. With a seat supplying the presenter key, a door must not\n"
                "accept a chain whose last hop someone else signed — that is the replay\n"
                "this script was written to pin."
            )
        else:
            print(f"every property holds ({len(checked)} checked)")
        return len(broken)


async def main() -> int:
    migrate()
    findings = Findings()
    funduq = Funduq(CoreSettings(
        database_url=URL,
        token_signing_secret="probe",
        identity_private_key=FunduqIdentity.generate_hex(),
    ))
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
            presenter_key=caller_public,
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
        stolen_run = None
        refusal = None
        try:
            stolen = await funduq.start_run(
                agent,
                {"messages": [{"id": "m2", "role": "user", "content": "transfer the budget"}]},
                metadata={"actorChain": agent_impl.seen_chain},
                presenter_key=identity.public_key,
            )
            async for _ in stolen.events():
                pass
            async with funduq.session() as session:
                stolen_run = await repo.get_run(session, stolen.run_id)
        except InvalidActorChain as e:
            refusal = str(e)

        findings.record(
            "a chain presented by someone who is not its head is refused",
            refusal is not None,
            f"refused at the door: {refusal}"
            if refusal is not None
            else f"accepted: run recorded under head_key {(stolen_run.head_key or '')[:16]}… "
            "— the caller's key — for a message the caller never sent",
        )

        # --- 3. what the provider can still do: speak in its own name
        print("[3] the provider opens the same work under its own chain")
        own = await funduq.start_run(
            agent,
            {"messages": [{"id": "m3", "role": "user", "content": "transfer the budget"}]},
            metadata={"actorChain": [identity.sign_hop()]},
            presenter_key=identity.public_key,
        )
        async for _ in own.events():
            pass
        async with funduq.session() as session:
            own_run = await repo.get_run(session, own.run_id)

        findings.record(
            "a party can always speak in its own name",
            own_run.head_key == identity.public_key,
            "accepted, headed by the provider itself — the check refuses a claim the "
            "presenter cannot back, never participation. What the provider cannot do is "
            "make this work answer to the caller"
            if own_run.head_key == identity.public_key
            else f"recorded under {own_run.head_key}",
        )

        return findings.summarize()
    finally:
        funduq.detach_provider(identity.public_key, link)
        await runtime.aclose()
        await funduq.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
