"""N funduq processes and a hand-rolled load balancer over them.

The second half of the probe fixture (see node.py for the first). A real
deployment puts nginx or a cloud LB in front of several funduq processes; this
is fifty lines that do the part that matters for finding bugs — send each call
to a different process — without introducing a dependency, a config file or a
second thing to install.

**Deliberately harsher than a real load balancer.** This round-robins *every
single call*, with no session affinity and no stickiness of any kind: the call
that starts a run, the worker's claim for it, each event that worker reports,
and the caller's read of the result can all land on four different processes.
Real load balancers are usually kinder than that, and kindness is what makes
this class of bug show up in production six months late instead of here. When
a probe needs a specific node — "boot B *now*, while A is holding a run" — it
asks for one by name (`call(..., node="b")`), because that is a scenario, not
a routing decision.

The processes are real: separate OS processes, spawned with `subprocess`, each
constructing its own `Funduq` with its own engine and its own in-memory broker,
sharing only `FUNDUQ_DATABASE_URL`. That is the whole point — two `Funduq` objects
in one process share an event loop and can be made to look like they work by
accident, which is how the first version of this probe overstated what it had
shown.

Usage:

    async with Cluster(nodes=["a", "b"]) as c:
        run = await c.call({"op": "start_run", ...})     # lands wherever
        await c.call({"op": "funduq_start"}, node="b")     # lands on b
        provider = await c.attach(identity, node="a")    # a link, to one node
        c.kill("a")                                      # SIGKILL, no cleanup

The LB half of this stops at the door. Work is handed *down* a provider's
link now rather than pulled by a request, so a provider is attached to one
named process and stays there — `attach` takes no round-robin form. Which
node a caller lands on is still a coin toss, and that mismatch is what most
of the multiprocess probe now measures.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from funduq_provider_sdk import (
    ProviderIdentity,
    funduq_connect_payload,
    new_nonce,
    verify_signature,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FUNDUQ_DIR = REPO_ROOT / "funduq"
NODE_SCRIPT = Path(__file__).resolve().parent / "node.py"

SIGNING_SECRET = "probe-signing-secret"

IDENTITY_KEY = "5a" * 32

# What a provider pins. Derived here rather than asked of a node on purpose:
# the whole point of pinning is that the value does not come from the party
# being authenticated.
FUNDUQ_PUBLIC_KEY = (
    Ed25519PrivateKey.from_private_bytes(bytes.fromhex(IDENTITY_KEY))
    .public_key()
    .public_bytes_raw()
    .hex()
)


class NodeError(RuntimeError):
    """A node answered `ok: false`. Carries which node, since 'who said this'
    is half of every finding in a multi-process probe."""


class Cluster:
    """A running cluster of funduq processes, plus the LB that talks to them."""

    def __init__(
        self,
        nodes: list[str],
        *,
        database_url: str | None = None,
        start_nodes: bool = False,
        env: dict[str, str] | None = None,
    ) -> None:
        """`start_nodes` calls `Funduq.start()` on every node at boot, as a real
        deployment would. Off by default: *when* each node reconciles is the
        subject of several probes, not a detail they can leave to chance.
        """
        self.names = list(nodes)
        self.tmpdir = Path(tempfile.mkdtemp(prefix="funduq-probe-"))
        self.database_url = database_url or f"sqlite+aiosqlite:///{self.tmpdir / 'funduq.db'}"
        self.start_nodes = start_nodes
        self.extra_env = env or {}
        self.procs: dict[str, subprocess.Popen] = {}
        self.clients: list["ProviderClient"] = []
        self._next = 0

    # ---- Lifecycle

    def _env(self) -> dict[str, str]:
        return {
            **os.environ,
            "FUNDUQ_DATABASE_URL": self.database_url,
            "FUNDUQ_TOKEN_SIGNING_SECRET": SIGNING_SECRET,
            # Both nodes share one identity on purpose: they are one funduq
            # behind a load balancer, and a provider pins the key it connected
            # to. Two keys would make which node answered visible to every
            # provider, which is not what horizontal scaling means.
            "FUNDUQ_IDENTITY_PRIVATE_KEY": IDENTITY_KEY,
            **self.extra_env,
        }

    def migrate(self) -> None:
        """`alembic upgrade head`, once, before any node boots — the same
        separate step a real deployment runs (see funduq/alembic/)."""
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=FUNDUQ_DIR,
            env=self._env(),
            check=True,
            capture_output=True,
        )

    def socket_path(self, name: str) -> Path:
        return self.tmpdir / f"{name}.sock"

    async def __aenter__(self) -> "Cluster":
        self.migrate()
        for name in self.names:
            self.spawn(name)
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        for client in self.clients:
            await client.close()
        self.clients.clear()
        self.shutdown()

    def spawn(self, name: str) -> None:
        """Start one node and wait until its socket is accepting. Waits for the
        node's own READY line rather than sleeping — a probe that sleeps is a
        probe that intermittently measures its own timing."""
        cmd = [sys.executable, str(NODE_SCRIPT), "--name", name, "--socket", str(self.socket_path(name))]
        if self.start_nodes:
            cmd.append("--start")
        proc = subprocess.Popen(
            cmd,
            cwd=FUNDUQ_DIR,
            env=self._env(),
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
        )
        self.procs[name] = proc
        for line in proc.stdout:  # type: ignore[union-attr]
            if line.startswith("READY"):
                return
        raise RuntimeError(f"node {name} exited before becoming ready (rc={proc.poll()})")

    def kill(self, name: str) -> None:
        """SIGKILL, no unwinding — the failure the lease design exists for.
        SIGTERM would let `Funduq.aclose()` run, which is a *graceful* shutdown
        and a different scenario entirely (and one that still leaves its runs
        `running` in the database, by design)."""
        proc = self.procs.pop(name, None)
        if proc is not None:
            proc.send_signal(signal.SIGKILL)
            proc.wait()
        if name in self.names:
            self.names.remove(name)

    def shutdown(self) -> None:
        for proc in self.procs.values():
            proc.terminate()
        for proc in self.procs.values():
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.procs.clear()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    # ---- The load balancer

    def pick(self) -> str:
        """Round-robin. No affinity, on purpose — see the module docstring."""
        if not self.names:
            raise RuntimeError("no nodes left in the cluster")
        name = self.names[self._next % len(self.names)]
        self._next += 1
        return name

    async def call(self, request: dict[str, Any], *, node: str | None = None) -> Any:
        """One domain call, through the LB. Returns the node's `result`, and
        raises NodeError if the node reported a failure — a probe should not
        have to check a status field on every line to notice something broke.
        """
        name = node or self.pick()
        reader, writer = await asyncio.open_unix_connection(str(self.socket_path(name)))
        try:
            writer.write((json.dumps(request) + "\n").encode())
            await writer.drain()
            response = json.loads(await reader.readline())
            if not response.get("ok"):
                raise NodeError(f"node {name}: {response.get('error')}")
            return response["result"]
        finally:
            writer.close()
            await writer.wait_closed()

    async def call_on(self, request: dict[str, Any]) -> tuple[str, Any]:
        """Like `call`, but also says which node answered — for probe output
        that has to show the spread rather than assert it happened."""
        name = self.pick()
        return name, await self.call(request, node=name)

    # ---- Providers, which the LB cannot help with

    async def attach(
        self,
        identity: ProviderIdentity,
        *,
        node: str,
        ticket_from: str | None = None,
        max_concurrent_runs: int | None = None,
    ) -> "ProviderClient":
        """Open a provider link on one named node and return the provider's half.

        **`node` is required and there is no round-robin form**, which is the
        first thing the port to attach-based dispatch showed: a link is a
        connection to one process, so "which node" is not a routing decision
        an LB can make per call — it is a property of the link for as long as
        it is open.

        The handshake is the real one, in the documented order: a ticket
        fetched over a *different* connection (`ticket_from` names which node
        issues it, since that is worth being able to vary), a proof over
        `provider_connect_payload`, and funduq's answer checked against the
        pinned key before this agrees the link is open.
        """
        ticket = (
            await self.call({"op": "issue_ticket", "public_key": identity.public_key},
                            node=ticket_from or node)
        )["ticket"]
        provider_nonce = new_nonce()
        reader, writer = await asyncio.open_unix_connection(str(self.socket_path(node)))
        writer.write(
            (
                json.dumps(
                    {
                        "op": "attach",
                        "public_key": identity.public_key,
                        "ticket": ticket,
                        "provider_nonce": provider_nonce,
                        "proof": identity.sign_connect(
                            FUNDUQ_PUBLIC_KEY, ticket, provider_nonce
                        ),
                        "max_concurrent_runs": max_concurrent_runs,
                    }
                )
                + "\n"
            ).encode()
        )
        await writer.drain()
        answered = json.loads(await reader.readline())
        if not answered.get("ok"):
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
            raise NodeError(f"node {node}: {answered.get('error')}")
        if not verify_signature(
            FUNDUQ_PUBLIC_KEY,
            answered["result"]["answer"],
            funduq_connect_payload(ticket, provider_nonce),
        ):
            raise NodeError(f"node {node}: the funduq answering this link did not prove its key")
        client = ProviderClient(node, identity, reader, writer)
        self.clients.append(client)
        return client

    async def subscribe(self, run_id: str, *, node: str, timeout: float = 5.0) -> list[Any]:
        """Drain a run's event stream from one specific node, until the stream
        ends or `timeout` passes. Node-specific by necessity: *which* node can
        answer this is the question, so letting the LB choose would hide it.

        A timeout is an ordinary result here, not an error — a node that is not
        dispatching the run answers with a stream that never ends because it
        never started (see RunBroker.subscribe's `_no_events`).
        """
        reader, writer = await asyncio.open_unix_connection(str(self.socket_path(node)))
        events: list[Any] = []
        try:
            writer.write((json.dumps({"op": "subscribe", "run_id": run_id}) + "\n").encode())
            await writer.drain()
            await reader.readline()  # the {"streaming": true} acknowledgement
            async with asyncio.timeout(timeout):
                while True:
                    line = await reader.readline()
                    if not line:
                        break
                    frame = json.loads(line)
                    if frame.get("end"):
                        break
                    events.append(frame["event"])
        except TimeoutError:
            pass
        finally:
            writer.close()
            # Closing a socket whose node was SIGKILLed is expected here, not
            # an error — several probes kill a node mid-stream on purpose.
            with contextlib.suppress(Exception):
                await writer.wait_closed()
        return events


class ProviderClient:
    """The provider half of an attached link — the side that receives work.

    A crude stand-in for `ProviderRuntime` over a socket, and crude in the
    same places node.py is: no reconnect, no backpressure, no framing beyond
    a newline. What it does not cut corners on is the two things funduq
    actually depends on. It **answers an offer from its own state, at once**
    (the receipt that holds the next utterance of the same conversation), and
    it **checks funduq's answering signature against the pinned key** before
    it agrees the link is open.

    It records rather than acts: offers and cancels land in lists, so a
    scenario can assert on what a provider was handed rather than on what
    some agent did with it.
    """

    def __init__(
        self,
        node: str,
        identity: ProviderIdentity,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.node = node
        self.identity = identity
        self.offers: list[dict[str, Any]] = []
        self.cancels: list[str] = []
        # What the next offer is answered with: True (accepted), False (full
        # right now), or a string (a permanent refusal, carrying its reason).
        self.answer: bool | str = True
        self._reader = reader
        self._writer = writer
        self._replies: dict[int, asyncio.Future] = {}
        self._next_id = 0
        self._pump = asyncio.create_task(self._read_loop())

    @property
    def public_key(self) -> str:
        return self.identity.public_key

    async def _send(self, frame: dict[str, Any]) -> None:
        self._writer.write((json.dumps(frame) + "\n").encode())
        await self._writer.drain()

    async def _read_loop(self) -> None:
        while line := await self._reader.readline():
            frame = json.loads(line)
            if "offer" in frame:
                self.offers.append(frame["offer"])
                answer = self.answer
                await self._send(
                    {
                        "ack": frame["offerId"],
                        "accepted": answer is True,
                        "refusal": answer if isinstance(answer, str) else None,
                    }
                )
                continue
            if "cancel" in frame:
                self.cancels.append(frame["cancel"])
                continue
            pending = self._replies.pop(frame.get("id"), None)
            if pending is not None and not pending.done():
                pending.set_result(frame)

    async def request(self, request: dict[str, Any]) -> Any:
        """One request on the open link, answered by the node holding it.

        There is no `node=` here, and that is the finding rather than a
        limitation of the fixture: a link is a connection to one process, so
        an LB has nothing to choose between.
        """
        request = {**request, "id": self._next_id}
        self._next_id += 1
        reply: asyncio.Future = asyncio.get_running_loop().create_future()
        self._replies[request["id"]] = reply
        await self._send(request)
        answered = await reply
        if not answered.get("ok"):
            raise NodeError(f"node {self.node}: {answered.get('error')}")
        return answered["result"]

    async def register(self, *names: str) -> dict[str, Any]:
        """Publish `names` on this link. Unsigned, because the link is the credential."""
        return await self.request(
            {"op": "register_agents", "agents": [{"name": n} for n in names]}
        )

    async def report_event(self, run_id: str, event: dict[str, Any]) -> bool:
        return await self.request({"op": "report_event", "run_id": run_id, "event": event})

    async def finish_run(self, run_id: str) -> bool:
        return await self.request({"op": "finish_run", "run_id": run_id})

    async def close(self) -> None:
        self._pump.cancel()
        with contextlib.suppress(Exception):
            self._writer.close()
            await self._writer.wait_closed()
