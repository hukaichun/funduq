"""One funduq process, reachable over a unix socket. A probe fixture, not a gateway.

The horizontal-scaling work (design/broker-horizontal-scaling.md, kept in git
history at d78d063 rather than in the tree) is about what
happens when several funduq processes share one database, and CLAUDE.md's rule
is that this gets found by running something rather than by reading. Running
it needs two things funduq itself deliberately does not have: a way to reach a
funduq from outside its process, and something to spread calls across several of
them.

This is the first. It is the smallest possible stand-in for a serving layer:
newline-delimited JSON over a unix socket, no framework, no HTTP, no auth of
its own. It exists to be crude — every real decision it might make (which
port, which framework, how to authenticate) is the gateway's to make in its
own repository, and making any of them here would be this repo growing a
serving layer under a different name.

    python scripts/probes/node.py --name a --socket /tmp/funduq-a.sock

**Two shapes of connection, because dispatch has two shapes.** Most ops are
one request, one answer, one connection — a caller arriving, a reader asking
what happened. A *provider* is not that: funduq hands work down to it, so its
link is opened once and stays open, and both directions run over it. `attach`
turns the connection it arrives on into that link, and everything after the
first line is either an offer going down (`{"offer": …, "offerId": n}`) or its
receipt coming back (`{"ack": n, "accepted": …}`), or an ordinary request the
provider makes *on* its link.

This is the part the port from `claim_work` changed. Work used to be pulled:
every call was a request, so request-per-connection was the whole model and
this file needed nothing else. It is handed over now, and a socket that closes
after one answer has nowhere for an offer to arrive.

What it must be honest about is the domain: every op below is a plain call
into `Funduq`, with no shortcut past the connect handshake or `report_event`'s
ownership check. A probe that cheated on those would prove nothing about the
thing being probed. In particular the ticket is fetched over a *different*
connection than the link it admits — `issue_ticket` is deliberately not an op
on an open link, and a transport that made it one would have the link exist
before anything authorised it (see docs/writing-a-transport.md).

`FUNDUQ_DATABASE_URL`, `FUNDUQ_TOKEN_SIGNING_SECRET` and
`FUNDUQ_IDENTITY_PRIVATE_KEY` come from the environment, as they would
anywhere else. Every node in a cluster must share all three — the database
because that is the whole point, and the secret and the key because a provider
pins one funduq and must not be able to tell which process answered.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import signal
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from funduq import repo
from funduq.config import CoreSettings
from funduq.core import Funduq
from funduq.models import AgentRef

# The published wire form of an offered run (docs/contract-vectors.json's
# `delivered-run`). A transport's funduq half has to produce those bytes, and
# hand-writing the mapping here is exactly what this repo has been bitten by
# on two protocols already.
from funduq_provider_sdk import DeliveredRun

logger = logging.getLogger("probe.node")


@dataclass(frozen=True)
class _Refused:
    """A permanent refusal, the way funduq reads one: duck-typed off `reason`.

    Deliberately a local three-line type rather than the SDK's `Refusal` —
    that attribute name is the entire contract between the two sides, and a
    probe that imported the provider's class would stop demonstrating it.
    """

    reason: str


def _agent(req: dict[str, Any]) -> AgentRef:
    """An agent named the way funduq names one — the pair, off the wire."""
    return AgentRef(provider_key=req["provider_key"], name=req["agent_name"])


class _SocketProvider:
    """The funduq-side half of a provider link, where the link is this socket.

    Satisfies `ConnectedProvider` and nothing more: a key, a concurrency
    declaration, `deliver`, `cancel`. Both verbs write a frame down the
    connection the provider opened; `deliver` then waits for the receipt,
    which is the one timing funduq depends on (an offer's answer holds the
    next utterance of the same conversation).
    """

    def __init__(self, public_key: str, max_concurrent_runs: int | None, send) -> None:
        self.public_key = public_key
        self.max_concurrent_runs = max_concurrent_runs
        self._send = send
        self._pending: dict[int, asyncio.Future] = {}
        self._next_offer = 0

    async def deliver(self, run: Any) -> Any:
        try:
            delivered = DeliveredRun.from_claimed(run)
        except ValidationError as exc:
            return _Refused(f"input does not validate as RunAgentInput: {exc}")
        offer_id = self._next_offer
        self._next_offer += 1
        answer: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[offer_id] = answer
        try:
            await self._send({"offer": delivered.model_dump(by_alias=True), "offerId": offer_id})
            return await answer
        except Exception:
            # A link that cannot be written to, or that went away mid-offer,
            # is "not right now" rather than "never" — funduq re-offers, and
            # the provider is about to be detached anyway.
            return False
        finally:
            self._pending.pop(offer_id, None)

    def cancel(self, run_id: str) -> None:
        # Synchronous by contract, so this is a hand-off to the loop: funduq
        # asks a provider to stop and never waits to see whether it did.
        asyncio.get_running_loop().create_task(self._send({"cancel": run_id}))

    def answer_offer(self, frame: dict[str, Any]) -> None:
        pending = self._pending.get(frame["ack"])
        if pending is None or pending.done():
            return
        if frame.get("refusal") is not None:
            pending.set_result(_Refused(frame["refusal"]))
        else:
            pending.set_result(bool(frame.get("accepted")))

    def close(self) -> None:
        for pending in self._pending.values():
            if not pending.done():
                pending.set_result(False)


async def _dispatch(funduq: Funduq, req: dict[str, Any]) -> Any:
    """One domain call. Deliberately a flat table of `Funduq`'s own methods —
    if an op here needed logic of its own, that logic would be a serving-layer
    decision this probe has no business making.
    """
    op = req["op"]

    if op == "funduq_start":
        return {"reaped": await funduq.start()}

    if op == "issue_ticket":
        # The admission decision, over a channel that is not the link it
        # admits — which is why it is here and not among the link ops below.
        return {"ticket": funduq.issue_ticket(req["public_key"])}

    if op == "start_run":
        handle = await funduq.start_run(_agent(req), req["run_input"])
        return {"run_id": handle.run_id, "thread_id": handle.thread_id}

    if op == "report_event":
        # `claimed_by` is named by the caller here, not taken from a link:
        # this is the op a probe uses to report at a node the provider is
        # *not* attached to, which is a scenario, not a mistake.
        return funduq.report_event(req["run_id"], req["event"], claimed_by=req["claimed_by"])

    if op == "finish_run":
        return funduq.finish_run(req["run_id"], claimed_by=req["claimed_by"])

    if op == "cancel_run":
        return await funduq.cancel_run(req["run_id"], metadata=req.get("metadata"))

    if op == "get_run":
        record = await funduq.get_run(req["run_id"])
        return record.model_dump(mode="json") if record is not None else None

    if op == "get_run_events":
        return await funduq.get_run_events(req["run_id"])

    if op == "active_runs":
        return funduq.active_runs()

    if op == "list_agents":
        return [agent.model_dump(mode="json") for agent in await funduq.list_agents()]

    if op == "touch_agent":
        async with funduq.session() as session:
            await repo.touch_agents(session, req["provider_key"], [req["agent_name"]])
        return True

    raise ValueError(f"unknown op: {op}")


async def _link_op(funduq: Funduq, provider: _SocketProvider, req: dict[str, Any]) -> Any:
    """A request a provider makes **on its own open link**.

    Three verbs need the link itself rather than a name: registering (the link
    is the credential — nothing here is signed), and reporting or finishing,
    where the claimant is whoever holds the link and cannot be a parameter.
    Anything else falls through to the ordinary table, so an attached provider
    can read a run without opening a second connection.
    """
    op = req["op"]

    if op == "register_agents":
        registration = await funduq.register_agents(provider, req["agents"])
        return {
            name: {"provider_key": ref.provider_key, "agent_name": ref.name}
            for name, ref in registration.agents.items()
        }

    if op == "report_event":
        return funduq.report_event(
            req["run_id"], req["event"], claimed_by=provider.public_key
        )

    if op == "finish_run":
        return funduq.finish_run(req["run_id"], claimed_by=provider.public_key)

    if op == "thread_messages":
        return await funduq.get_thread_messages(req["thread_id"])

    return await _dispatch(funduq, req)


async def _serve_link(
    funduq: Funduq, name: str, req: dict[str, Any], reader: asyncio.StreamReader, send
) -> None:
    """Turn this connection into an open provider link and keep it open.

    The handshake is the transport's own: the provider signed the ticket it
    fetched elsewhere, this relays the proof, and funduq's answering signature
    goes back on the wire for the provider to check against its pin.
    """
    provider = _SocketProvider(req["public_key"], req.get("max_concurrent_runs"), send)
    answer = await funduq.attach_provider(
        provider,
        ticket=req.get("ticket"),
        provider_nonce=req.get("provider_nonce"),
        proof=req.get("proof"),
    )
    await send({"ok": True, "node": name, "result": {"attached": True, "answer": answer}})
    try:
        while line := await reader.readline():
            frame = json.loads(line)
            if "ack" in frame:
                provider.answer_offer(frame)
                continue
            reply: dict[str, Any] = {"id": frame.get("id"), "node": name}
            try:
                reply |= {"ok": True, "result": await _link_op(funduq, provider, frame)}
            except Exception as exc:
                logger.exception("link op failed")
                reply |= {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            await send(reply)
    finally:
        provider.close()
        # Named, so that cleanup of a link that has already been replaced
        # cannot take its replacement offline.
        funduq.detach_provider(provider.public_key, provider)


async def _handle(funduq: Funduq, name: str, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    lock = asyncio.Lock()

    async def send(obj: Any) -> None:
        # One writer, several producers: an offer leaving on this connection
        # and a reply to a request the provider made can be produced by
        # different tasks, and half a JSON line is not a frame.
        async with lock:
            writer.write((json.dumps(obj) + "\n").encode())
            await writer.drain()

    try:
        line = await reader.readline()
        if not line:
            return
        req = json.loads(line)

        # `subscribe` is the one streaming *read*: it answers with an
        # {"event": …} line per event and one {"end": true}, then closes.
        # Whether it produces anything at all is itself a probe result — a
        # node that is not dispatching the run answers with an immediately
        # empty stream (see RunBroker.subscribe), which is precisely the
        # cross-node read problem the design has to solve.
        if req.get("op") == "subscribe":
            await send({"ok": True, "node": name, "streaming": True})
            async for event in funduq.broker.subscribe(req["run_id"]):
                await send({"event": event})
            await send({"end": True})
            return

        if req.get("op") == "attach":
            await _serve_link(funduq, name, req, reader, send)
            return

        await send({"ok": True, "node": name, "result": await _dispatch(funduq, req)})
    except Exception as exc:
        logger.exception("op failed")
        with contextlib.suppress(Exception):
            await send({"ok": False, "node": name, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        with contextlib.suppress(Exception):
            writer.close()
            await writer.wait_closed()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="this node's label in probe output")
    parser.add_argument("--socket", required=True, help="unix socket path to listen on")
    parser.add_argument(
        "--start",
        action="store_true",
        help="call Funduq.start() on boot (orphan reconciliation + health sweeps), as a "
        "real deployment does. Off by default so a probe can choose when that happens — "
        "which node boots when is exactly what the design is about.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format=f"%(levelname)s [{args.name}] %(name)s: %(message)s"
    )

    # This one really is a process, started by cluster.py with the
    # environment it wants — so reading it is the right act here, named.
    funduq = Funduq(CoreSettings.from_env())
    if args.start:
        await funduq.start()

    with contextlib.suppress(FileNotFoundError):
        os.unlink(args.socket)
    server = await asyncio.start_unix_server(
        lambda r, w: _handle(funduq, args.name, r, w), path=args.socket
    )

    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopped.set)

    # Printed, not logged: the harness waits for this line to know the socket
    # is accepting rather than sleeping and hoping.
    print(f"READY {args.name} {args.socket}", flush=True)

    async with server:
        await stopped.wait()

    await funduq.aclose()
    with contextlib.suppress(FileNotFoundError):
        os.unlink(args.socket)


if __name__ == "__main__":
    asyncio.run(main())
