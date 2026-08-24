from __future__ import annotations

import abc
import asyncio
import logging
import secrets
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from funduq import repo
from funduq.broker import (
    ConnectedProvider,
    FinishStream,
    RelayEvent,
    RunBroker,
    RunSnapshot,
)
from funduq.changes import ChangeEvent, LlmRosterChanged, RosterChanged, RunStatusChanged
from funduq.config import CoreSettings
from funduq.doors import (
    InboundRun,
    PendingAsk,
    authorize_cancel,
    dispatch,
    offline_events,
    open_run,
    resolve_kyok,
    verify_caller,
)
from funduq.db_schema import DEFAULT_DB_SCHEMA, EXPECTED_SCHEMA_REVISION, quoted_schema
from funduq.errors import (
    AgentInUse,
    AgentNotFound,
    InvalidRegistration,
    NoPendingAsk,
    RunNotCancellable,
    LlmOfferingInUse,
    LlmProviderNotFound,
)
from funduq.handlers import close_with_terminal_event, make_handlers
from funduq.identity import (
    FunduqIdentity,
    SIGNATURE_FRESHNESS_WINDOW_SECONDS,
    is_timestamp_fresh,
    provider_connect_signing_payload,
    funduq_connect_signing_payload,
    verify_signature,
)
from funduq.kyok import ConnectedLLMProvider, KyokRelay
from funduq.models import AgentRecord, AgentRef, AgentSummary, LlmRef, LlmSummary, RunRecord

logger = logging.getLogger("funduq.core")


@dataclass
class Registration:

    agents: dict[str, AgentRef]


@dataclass(frozen=True)
class Health:
    """Snapshot of database reachability, schema version, and dispatch state."""

    database: bool
    schema_revision: str | None
    expected_schema_revision: str
    dispatching: bool = False
    database_error: str | None = None

    @property
    def schema_current(self) -> bool:
        return self.schema_revision == self.expected_schema_revision

    @property
    def ready(self) -> bool:
        return self.database and self.schema_current and self.dispatching


@dataclass
class RunHandle:
    """Caller-facing reference to a run: its id, thread, and its event stream."""

    run_id: str
    thread_id: str
    _broker: RunBroker | None = None
    _events: AsyncIterator[Any] | None = None

    async def events(self) -> AsyncIterator[Any]:
        """Yield the run's AG-UI events; yields nothing if no stream was attached."""
        if self._events is None:
            return
        async for item in self._events:
            yield item

    def cancel(self) -> None:
        if self._broker is not None:
            self._broker.request_cancel(self.run_id)


class _Roster(abc.ABC):
    """One live roster of served names, stated once for both vocabularies.

    The agent roster and the LLM-offering roster share these semantics:
    registration is signed and fresh, and re-registering a subset withdraws
    the omitted names from live serving; attaching requires prior
    registration, touches, and announces; detaching is a silent no-op when
    nothing is served. The steps live here because two hand-kept copies
    drifted twice — a member-by-member fix first, then a probe catching the
    withdraw step missing on the LLM side — and a copy of a base can't
    drop a step.
    """

    party: str
    served: str

    def __init__(self, funduq: "Funduq") -> None:
        self._funduq = funduq
        # public key -> the links it has open. Registering and deleting are
        # operations on one of these; nothing else is.
        self._open: dict[str, list[Any]] = {}

    @abc.abstractmethod
    async def touch(self, session: AsyncSession, public_key: str, names: list[str]) -> None: ...

    @abc.abstractmethod
    def ref(self, public_key: str, name: str) -> Any: ...

    @abc.abstractmethod
    def served_by(self, public_key: str) -> list[Any]: ...

    @abc.abstractmethod
    def write_live(self, mapping: dict[Any, Any]) -> None: ...

    @abc.abstractmethod
    def withdraw(self, refs: list[Any]) -> None: ...

    @abc.abstractmethod
    def not_found(self, message: str) -> Exception: ...

    @abc.abstractmethod
    def changed(self) -> ChangeEvent: ...

    def open_links(self, public_key: str) -> list[Any]:
        return self._open.get(public_key, [])

    def require_open(self, connection: Any) -> None:
        """Raises unless `connection` completed a handshake and has not detached.

        **The link is the credential.** Registering and deleting carry no
        signature of their own because the key was proved once, when the link
        opened, and re-proving it per operation is what the four retired
        payload families were doing. What this asks of a transport in return
        is the ordinary thing: an open link stays the party that opened it.
        """
        if connection not in self._open.get(connection.public_key, []):
            raise InvalidRegistration(
                f"{self.party} '{connection.public_key}' is not on an open link — "
                "open one with a ticket first; registering and deleting happen on it"
            )

    async def open(
        self,
        connection: Any,
        *,
        ticket: str | None = None,
        provider_nonce: str | None = None,
        proof: str | None = None,
    ) -> str | None:
        """Authenticate and open a link. **No names**: registering is what puts one live.

        `proof` is a signature over `provider_connect_signing_payload(this
        funduq's public key, ticket, provider_nonce)`, where `ticket` came
        from `Funduq.issue_ticket` **and names this key**. funduq chose it and
        destroys it here, so a recording is worthless; the payload names this
        funduq as the recipient, so a proof coaxed out by one funduq cannot be
        relayed to attach at another. A connection that can sign (it exposes
        `sign_connect`, as the in-process links do) is ticketed and verified
        automatically; in-process is not trusted either. A connection that
        offers no proof is rejected, and there is deliberately no way to
        switch this off — one handshake everywhere is what lets a provider in
        any language implement it once against the published vectors.

        funduq answers in kind: the return value is its own signature over
        `funduq_connect_signing_payload(ticket, provider_nonce)` — the proof a
        provider checks against the funduq key it pinned — or None if this
        funduq has no identity configured and so cannot prove itself. A
        transport relays the answer to the far side; a connection exposing
        `confirm_connect` (as the in-process links do) is handed it before the
        link is recorded open, so a provider that pins can refuse the wrong
        funduq by raising there.
        """
        signer = getattr(connection, "sign_connect", None)
        if proof is None and callable(signer):
            ticket = self._funduq.issue_ticket(connection.public_key)
            provider_nonce = secrets.token_hex(16)
            proof = signer(self._funduq.identity_public_key or "", ticket, provider_nonce)
        if proof is None:
            raise InvalidRegistration(
                f"{self.party} '{connection.public_key}' tried to open a link without a "
                "connect proof — sign the ticket from issue_ticket, or expose sign_connect"
            )
        if ticket is None or not self._funduq._claim_ticket(ticket, connection.public_key):
            raise InvalidRegistration(
                f"connect proof for {self.party} '{connection.public_key}' does not answer "
                "a live ticket funduq issued to that key"
            )
        payload = provider_connect_signing_payload(
            self._funduq.identity_public_key or "", ticket, provider_nonce or ""
        )
        if not verify_signature(connection.public_key, proof, payload):
            raise InvalidRegistration(
                f"invalid connect proof for {self.party} '{connection.public_key}'"
            )
        answer = (
            self._funduq.sign(funduq_connect_signing_payload(ticket, provider_nonce or ""))
            if self._funduq.identity is not None
            else None
        )
        confirm = getattr(connection, "confirm_connect", None)
        if callable(confirm):
            confirm(ticket, provider_nonce or "", answer)
        self._open.setdefault(connection.public_key, []).append(connection)
        return answer

    async def register(
        self,
        connection: Any,
        names: list[str],
        store: Callable[[AsyncSession], Any],
    ) -> Any:
        """Publish `names` on an open link and serve them from it.

        One act, because it was always one act: what a name *is* and who is
        answering for it right now are decided together, by the party that
        holds the key, on the link that proved it. Nothing here is signed —
        the link is.

        **Not registered is offline.** The names this connection serves are
        exactly the ones it last registered, so a smaller batch takes the
        omitted ones off the roster. Names the same key serves on a
        *different* link are untouched: a provider may split its agents
        across processes, and each link answers for what it registered.
        """
        self.require_open(connection)
        if not names:
            raise ValueError(
                f"{self.party} '{connection.public_key}' registered no {self.served} — "
                "there would be nothing to serve"
            )
        async with self._funduq.session() as session:
            registered = await store(session)
        keep = {self.ref(connection.public_key, name) for name in registered}
        withdrawn = [
            ref
            for ref in self.served_by(connection.public_key)
            if self.live(ref) is connection and ref not in keep
        ]
        if withdrawn:
            self.withdraw(withdrawn)
        self.write_live({ref: connection for ref in keep})
        async with self._funduq.session() as session:
            await self.touch(session, connection.public_key, list(registered))
            await session.commit()
        self._funduq._notify_change(self.changed())
        return registered

    def take_offline(self, connection: Any, name: str) -> None:
        """Withdraw one name this connection serves, ahead of deleting its record.

        Deleting happens on the link that serves the name, so "something is
        serving it" cannot be the guard it used to be — the caller is that
        something. What still guards a deletion is what the record means:
        a name with a conversation behind it stays.
        """
        ref = self.ref(connection.public_key, name)
        if self.live(ref) is connection:
            self.withdraw([ref])

    @abc.abstractmethod
    def live(self, ref: Any) -> Any: ...

    def detach(self, public_key: str, connection: Any) -> None:
        """Take offline the names of `public_key` that `connection` currently serves;
        a no-op (no change event) if it serves none.

        funduq holds one connection per role: a re-attach under the same key
        replaces the old connection, and replicas are the provider's own
        concern behind its single connection. Naming the connection is what
        makes cleanup after a *replaced* link safe — only names whose current
        connection is that object (by identity) are withdrawn, so a
        replacement that already re-attached stays serving. The compare and
        the withdraw run without an await between them, so nothing can slip
        a replacement in between. Taking a key offline regardless of which
        connection serves it is a different, deliberately louder verb:
        `detach_all`.
        """
        links = self._open.get(public_key, [])
        if connection in links:
            links.remove(connection)
            if not links:
                self._open.pop(public_key, None)
        attached = [r for r in self.served_by(public_key) if self.live(r) is connection]
        if not attached:
            return
        self.withdraw(attached)
        self._funduq._notify_change(self.changed())

    def detach_all(self, public_key: str) -> None:
        """Take every name served by `public_key` offline, whichever connection
        serves it; a no-op (no change event) if nothing is. The eviction form —
        cleanup after one closed link belongs to `detach`, which cannot take
        down a replacement."""
        self._open.pop(public_key, None)
        attached = self.served_by(public_key)
        if not attached:
            return
        self.withdraw(attached)
        self._funduq._notify_change(self.changed())


class _AgentRoster(_Roster):

    party = "provider"
    served = "agent names"

    async def touch(self, session: AsyncSession, public_key: str, names: list[str]) -> None:
        await repo.touch_agents(session, public_key, names)

    def ref(self, public_key: str, name: str) -> AgentRef:
        return AgentRef(provider_key=public_key, name=name)

    def served_by(self, public_key: str) -> list[AgentRef]:
        return self._funduq.broker.agents_served_by(public_key)

    def live(self, ref: AgentRef) -> Any:
        return self._funduq.broker.serving(ref)

    def write_live(self, mapping: dict[Any, Any]) -> None:
        self._funduq.broker.register_provider(mapping)

    def withdraw(self, refs: list[Any]) -> None:
        self._funduq.broker.unregister_provider(refs)

    def not_found(self, message: str) -> Exception:
        return AgentNotFound(message)

    def changed(self) -> ChangeEvent:
        return RosterChanged()


class _LlmRoster(_Roster):

    party = "LLM provider"
    served = "model names"

    async def touch(self, session: AsyncSession, public_key: str, names: list[str]) -> None:
        await repo.touch_llm_providers(session, public_key, names)

    def ref(self, public_key: str, name: str) -> LlmRef:
        return LlmRef(provider_key=public_key, name=name)

    def served_by(self, public_key: str) -> list[LlmRef]:
        return self._funduq.kyok_relay.served_by(public_key)

    def live(self, ref: LlmRef) -> Any:
        return self._funduq.kyok_relay.serving(ref)

    def write_live(self, mapping: dict[Any, Any]) -> None:
        self._funduq.kyok_relay.attach(mapping)

    def withdraw(self, refs: list[Any]) -> None:
        self._funduq.kyok_relay.withdraw(refs)

    def not_found(self, message: str) -> Exception:
        return LlmProviderNotFound(message)

    def changed(self) -> ChangeEvent:
        return LlmRosterChanged()


class Funduq:
    """The network-free facade: agent/LLM-provider rosters, threads, runs, and dispatch."""

    def __init__(self, settings: CoreSettings | None = None, broker: RunBroker | None = None) -> None:
        self.settings = settings or CoreSettings()
        self.identity = (
            FunduqIdentity.from_hex(self.settings.identity_private_key)
            if self.settings.identity_private_key
            else None
        )
        self.engine = _create_engine(self.settings)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)
        self.broker = broker or RunBroker(
            spawn=self.spawn,
            quality_tolerance=self.settings.provider_quality_tolerance,
        )
        self.kyok_relay = KyokRelay()
        self.broker.add_forget_listener(self.kyok_relay.discard)
        self._agent_roster = _AgentRoster(self)
        self._llm_roster = _LlmRoster(self)
        # ticket -> (the key it admits, when it was issued). Node-local, like
        # everything else about a connection.
        self._tickets: dict[str, tuple[str, float]] = {}
        self._tasks: set[asyncio.Task] = set()
        self._started = False
        self._change_subscribers: set[Callable[[ChangeEvent], None]] = set()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as session:
            yield session


    @property
    def identity_public_key(self) -> str | None:
        return self.identity.public_key if self.identity is not None else None

    def issue_ticket(self, public_key: str) -> str:
        """Mint a single-use ticket admitting `public_key` to open a link, and
        return it.

        **Issuing is the admission decision.** A key with no ticket cannot
        connect at all, so whoever calls this — over whatever channel the
        deployment gives it — is the party that decides who may serve here.

        The ticket names the key it admits, and that is what makes it safe to
        hand across a channel funduq does not control: a leaked ticket is
        worthless, because only the named key can produce the signature that
        answers it, and a stranger cannot burn it (the name is matched before
        it is destroyed — see `_claim_ticket`).

        **This is deliberately not an operation on a connection**, and must
        not become one. A ticket fetched over the link would mean the link
        existed before anything authorised it. Core keeps the verb here and
        out of the link's operation set; whether a deployment really uses a
        separate channel is the transport's to answer, and its guide says so.

        Valid for the signature freshness window, and destroyed by the
        handshake that answers it.
        """
        now = time.time()
        self._tickets = {
            ticket: issued
            for ticket, issued in self._tickets.items()
            if now - issued[1] <= SIGNATURE_FRESHNESS_WINDOW_SECONDS
        }
        ticket = secrets.token_hex(16)
        self._tickets[ticket] = (public_key, now)
        return ticket

    def _claim_ticket(self, ticket: str, public_key: str) -> bool:
        """Spends `ticket` if it exists, is fresh, and was issued to `public_key`.

        **Matched before it is destroyed, and destroyed only for the key it
        names.** The order is the point: a version that popped first let
        anyone who had merely *seen* a live ticket burn it with a garbage
        proof, and the provider it was minted for could not connect. That
        needs no key at all, so it was a denial available to anyone on the
        path the ticket travelled.
        """
        issued = self._tickets.get(ticket)
        if issued is None or issued[0] != public_key:
            return False
        if time.time() - issued[1] > SIGNATURE_FRESHNESS_WINDOW_SECONDS:
            self._tickets.pop(ticket, None)
            return False
        self._tickets.pop(ticket, None)
        return True

    def sign(self, payload: bytes) -> str:
        """Sign `payload` with this funduq's identity key, or raise if none is configured."""
        if self.identity is None:
            raise RuntimeError(
                "this funduq has no identity: set identity_private_key "
                "(FUNDUQ_IDENTITY_PRIVATE_KEY) to a hex-encoded Ed25519 seed"
            )
        return self.identity.sign(payload)


    async def start(self) -> list[str]:
        """Run once: fail any run left queued/running from a prior process and start dispatch.

        A second call is a no-op that returns an empty list, so it cannot reap runs
        queued after the first call. Returns the ids of runs marked failed as orphaned.
        """
        if self._started:
            return []
        self._started = True
        async with self.session() as session:
            orphaned = await repo.fail_orphaned_runs(session)
        for run_id in orphaned:
            await close_with_terminal_event(self, run_id, "orphaned_by_funduq_restart")
        if orphaned:
            logger.warning(
                "start: marked %d run(s) failed — still queued/running from before this "
                "process, and funduq's dispatch state does not survive a restart: %s",
                len(orphaned),
                orphaned,
            )
        self.broker.start()
        return orphaned

    async def health(self, timeout: float = 2.0) -> Health:
        """Probe the database within `timeout` and report reachability, schema, and dispatch state."""
        revision: str | None = None
        reachable = True
        error: str | None = None
        try:
            async with asyncio.timeout(timeout):
                async with self.session() as session:
                    await session.execute(text("SELECT 1"))
                    revision = await repo.get_schema_revision(session)
        except TimeoutError:
            reachable, error = False, "TimeoutError"
        except Exception as exc:
            reachable, error = False, type(exc).__name__

        return Health(
            database=reachable,
            schema_revision=revision,
            expected_schema_revision=EXPECTED_SCHEMA_REVISION,
            dispatching=self.broker.is_running,
            database_error=error,
        )


    def spawn(self, coro, *, name: str | None = None) -> asyncio.Task:
        """Start `coro` as a tracked background task so `aclose` can cancel it later."""
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def aclose(self) -> None:
        """Stop dispatch, cancel every task spawned via `spawn`, and dispose the engine."""
        self.broker.stop()
        self._started = False
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
        await self.engine.dispose()


    async def register_agents(
        self,
        connection: Any,
        agents: list[dict[str, Any]],
        provider_name: str | None = None,
    ) -> Registration:
        """Publish `agents` on `connection`'s open link and serve them from it.

        Nothing here is signed: the key was proved when the link opened, and
        this is that link speaking. Raises `InvalidRegistration` if the
        connection has no open link.

        The names this link serves are exactly the ones it last registered,
        so registering a smaller roster takes the omitted ones offline —
        their records stay, readable as `online: false`.
        """
        public_key = connection.public_key
        registered = await self._agent_roster.register(
            connection,
            [a["name"] for a in agents],
            store=lambda session: repo.register_agents(
                session, public_key, agents, provider_name=provider_name
            ),
        )
        return Registration(
            agents={
                name: AgentRef(provider_key=public_key, name=name) for name in registered
            }
        )

    async def delete_agent(self, connection: Any, name: str) -> None:
        """Remove an agent's record, on the link that serves it.

        Nothing is signed: this is the open link speaking, and the link
        proved the key. The name is taken offline first — "a provider is
        serving it" cannot be a guard when the caller *is* that provider.

        What still guards a deletion is what the record means: **an agent
        with a conversation behind it stays.** Stop offering it instead and
        it goes offline and off the roster with its record intact. Raises
        `AgentNotFound` if unregistered, `AgentInUse` if it has any thread or
        run history, and `InvalidRegistration` if the connection has no open
        link.
        """
        self._agent_roster.require_open(connection)
        agent = AgentRef(provider_key=connection.public_key, name=name)
        async with self.session() as session:
            record = await repo.get_agent(session, agent)
            if record is None:
                raise AgentNotFound(f"agent '{agent}' is not registered")
            if await repo.count_threads_for_agent(
                session, agent
            ) or await repo.count_runs_for_agent(session, agent):
                raise AgentInUse(
                    f"agent '{agent}' has a conversation behind it and cannot be removed — "
                    "stop offering it instead, and it goes offline and off the roster with "
                    "its record intact",
                    reason="has_history",
                )
            self._agent_roster.take_offline(connection, name)
            await repo.delete_agent(session, agent)
        self._notify_change(RosterChanged())

    async def delete_llm_offering(self, connection: Any, name: str) -> None:
        """Remove an LLM offering's record, on the link that serves it — the mirror of `delete_agent`.

        The offering is taken offline first, so "a provider is serving it"
        cannot be the guard. A live run bound to it still refuses: that is
        work in flight, not a connection. Offerings carry no conversation
        history, so there is no `has_history` refusal.
        """
        self._llm_roster.require_open(connection)
        ref = LlmRef(provider_key=connection.public_key, name=name)
        async with self.session() as session:
            record = await repo.get_llm_provider(session, ref)
            if record is None:
                raise LlmProviderNotFound(f"LLM offering '{ref}' is not registered")
            bound = self.kyok_relay.bound_runs(ref)
            if bound:
                raise LlmOfferingInUse(
                    f"LLM offering '{ref}' has {bound} live run(s) bound to it",
                    reason="active_run",
                )
            self._llm_roster.take_offline(connection, name)
            await repo.delete_llm_provider(session, ref)
        self._notify_change(LlmRosterChanged())

    def report_event(self, run_id: str, event: Any, *, claimed_by: str) -> bool:
        """Relay `event` into the run's stream if `claimed_by` holds the run (or can late-claim it).

        Returns False, without relaying, for an unknown run or one held by a different claimant.
        """
        run = self.broker.get(run_id)
        if run is None:
            return False
        if run.claimed_by is None:
            if not self.broker.accept_late_ack(run_id, claimed_by):
                logger.warning(
                    "report_event: '%s' reported for run %s, which nobody holds",
                    claimed_by,
                    run_id,
                )
                return False
        elif run.claimed_by != claimed_by:
            logger.warning(
                "report_event: '%s' reported for run %s, which is held by '%s'",
                claimed_by,
                run_id,
                run.claimed_by,
            )
            return False
        return self.broker.push(run_id, RelayEvent(event))

    def finish_run(self, run_id: str, *, claimed_by: str) -> bool:
        """End the run's stream if `claimed_by` currently holds it; False for an unknown or mismatched run."""
        run = self.broker.get(run_id)
        if run is None:
            return False
        if run.claimed_by != claimed_by:
            logger.warning(
                "finish_run: '%s' tried to end run %s, which is held by '%s'",
                claimed_by,
                run_id,
                run.claimed_by,
            )
            return False
        return self.broker.push(run_id, FinishStream())

    async def attach_provider(
        self,
        provider: ConnectedProvider,
        *,
        ticket: str | None = None,
        provider_nonce: str | None = None,
        proof: str | None = None,
    ) -> str | None:
        """Open an authenticated link for `provider`. **No names** — registering is
        what puts one live, and it happens on this link (`register_agents`).

        A transport passes the `ticket` it relayed (from `issue_ticket`, minted
        for this provider's key), the provider's `provider_nonce`, and the
        returned `proof`, then relays the returned answer — funduq's own
        signature, for the provider to check against its pinned funduq key. A
        connection exposing `sign_connect` does all of that itself. See
        `_Roster.open`.
        """
        return await self._agent_roster.open(
            provider, ticket=ticket, provider_nonce=provider_nonce, proof=proof
        )

    async def register_llm_providers(
        self,
        connection: Any,
        names: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, LlmRef]:
        """Publish `names` as LLM offerings on `connection`'s open link and serve
        them from it — the mirror of `register_agents`.

        An offering this link served and omitted from this batch goes offline;
        its record stays.
        """
        public_key = connection.public_key
        registered = await self._llm_roster.register(
            connection,
            names,
            store=lambda session: repo.register_llm_providers(
                session, public_key, names, metadata
            ),
        )
        return {
            name: LlmRef(provider_key=public_key, name=name) for name in registered
        }

    async def attach_llm_provider(
        self,
        link: ConnectedLLMProvider,
        *,
        ticket: str | None = None,
        provider_nonce: str | None = None,
        proof: str | None = None,
    ) -> str | None:
        """Open an authenticated link for `link`. Connect authentication — funduq's
        answering signature included — works exactly as in `attach_provider`, and
        offerings are published on the open link with `register_llm_providers`.
        """
        return await self._llm_roster.open(
            link, ticket=ticket, provider_nonce=provider_nonce, proof=proof
        )

    def detach_llm_provider(self, public_key: str, connection: Any) -> None:
        """Take offline the model offerings that `connection` serves for `public_key`;
        a no-op (no change event) if it serves none.

        Naming the connection is required: it is what keeps cleanup after a
        replaced link (a closed socket) from taking down the replacement that
        already re-attached. To evict a key outright, whichever connection
        serves it, call `detach_all_for`. See `_Roster.detach`.
        """
        self._llm_roster.detach(public_key, connection)

    def detach_provider(self, provider_public_key: str, connection: Any) -> None:
        """Take offline the agents that `connection` serves for `provider_public_key`;
        a no-op if it serves none.

        Naming the connection is required: it is what keeps cleanup after a
        replaced link (a closed socket) from taking down the replacement that
        already re-attached. To evict a key outright, whichever connection
        serves it, call `detach_all_for`. See `_Roster.detach`.
        """
        self._agent_roster.detach(provider_public_key, connection)

    def detach_all_for(self, public_key: str) -> None:
        """Take `public_key` offline entirely — every agent and every model offering,
        whichever connections serve them; a no-op where it serves nothing.

        This is the eviction form, per identity, and it is deliberately a
        different name: cleanup after one closed link belongs to
        `detach_provider` / `detach_llm_provider`, which cannot take down a
        replacement. The dangerous operation only answers to its full name.
        """
        self._agent_roster.detach_all(public_key)
        self._llm_roster.detach_all(public_key)


    def on_change(self, callback: Callable[[ChangeEvent], None]) -> Callable[[], None]:
        self._change_subscribers.add(callback)

        def unsubscribe() -> None:
            self._change_subscribers.discard(callback)

        return unsubscribe

    def _notify_change(self, event: ChangeEvent) -> None:
        for callback in list(self._change_subscribers):
            try:
                callback(event)
            except Exception:
                logger.exception("on_change subscriber raised for %r", event)

    async def mark_run_status(
        self, session: AsyncSession, run_id: str, status: str, metadata: dict[str, Any] | None = None
    ) -> bool:
        """Applies the status transition (see `repo.LEGAL_STATUS_TRANSITIONS`) and
        notifies change subscribers only when it actually applied. Returns whether
        it did — a refused transition means another, legal one won the row."""
        applied = await repo.mark_run_status(session, run_id, status, metadata=metadata)
        if applied:
            self._notify_change(RunStatusChanged(run_id=run_id, status=status))
        return applied

    async def return_run_to_queue(self, session: AsyncSession, run_id: str) -> bool:
        """Puts a run whose offer was not accepted back to "queued"
        (`repo.return_run_to_queue`) and notifies change subscribers only when
        it actually applied — the mirror of `mark_run_status`, for the one
        transition that function deliberately does not write."""
        applied = await repo.return_run_to_queue(session, run_id)
        if applied:
            self._notify_change(RunStatusChanged(run_id=run_id, status="queued"))
        return applied

    async def list_agents(self) -> list[AgentSummary]:
        """List registered agents with `online` set to whether a provider is currently serving each."""
        async with self.session() as session:
            stored = await repo.list_agents(
                session,
                stale_hidden_window_seconds=self.settings.stale_hidden_window_seconds,
            )
        return [
            summary.model_copy(update={"online": self.is_serving(
                AgentRef(provider_key=summary.provider_key, name=summary.name)
            )})
            for summary in stored
        ]

    async def list_llm_providers(self) -> list[LlmSummary]:
        """List registered LLM offerings with `online` set to whether a provider is currently serving each — the mirror of `list_agents`."""
        async with self.session() as session:
            stored = await repo.list_llm_providers(
                session,
                stale_hidden_window_seconds=self.settings.stale_hidden_window_seconds,
            )
        return [
            summary.model_copy(update={"online": self.is_serving_llm(
                LlmRef(provider_key=summary.provider_key, name=summary.name)
            )})
            for summary in stored
        ]

    def is_serving(self, agent: AgentRef) -> bool:
        return self.broker.serving(agent) is not None

    def is_serving_llm(self, ref: LlmRef) -> bool:
        return self.kyok_relay.serving(ref) is not None

    async def get_agent(self, agent: AgentRef) -> AgentRecord | None:
        async with self.session() as session:
            return await repo.get_agent(session, agent)

    async def resolve_agent(self, provider: str, name: str) -> AgentRecord | None:
        async with self.session() as session:
            return await repo.resolve_agent(session, provider, name)


    async def create_thread(
        self, agent: AgentRef, parent_thread_id: str | None = None, metadata: dict | None = None
    ) -> str:
        async with self.session() as session:
            thread_id = await repo.create_thread(session, agent, parent_thread_id, metadata)
            await session.commit()
            return thread_id

    async def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        async with self.session() as session:
            return await repo.get_thread(session, thread_id)

    async def get_thread_messages(self, thread_id: str) -> list[dict[str, Any]]:
        async with self.session() as session:
            return await repo.get_thread_messages(session, thread_id)

    async def get_thread_snapshot(self, thread_id: str) -> dict[str, Any] | None:
        async with self.session() as session:
            return await repo.get_thread_snapshot(session, thread_id)

    async def get_thread_tree(self, thread_id: str) -> dict[str, Any] | None:
        """Return `thread_id` and its descendant threads nested as `children`, or None if it doesn't exist."""
        async with self.session() as session:
            root = await repo.get_thread(session, thread_id)
            if root is None:
                return None

            async def build(node_thread_id: str) -> list[dict[str, Any]]:
                children = await repo.get_thread_children(session, node_thread_id)
                return [
                    {**child, "children": await build(child["thread_id"])} for child in children
                ]

            return {
                "thread_id": thread_id,
                "provider_key": root["provider_key"],
                "agent_name": root["agent_name"],
                "children": await build(thread_id),
            }


    async def get_run(self, run_id: str) -> RunRecord | None:
        async with self.session() as session:
            return await repo.get_run(session, run_id)

    async def get_run_events(self, run_id: str, since_seq: int = 0) -> list[dict[str, Any]]:
        async with self.session() as session:
            return await repo.get_run_events(session, run_id, since_seq=since_seq)

    def active_runs(self) -> list[str]:
        return self.broker.active_run_ids()

    def enqueue_run(
        self,
        run_id: str,
        agent: AgentRef,
        thread_id: str,
        input_json: dict[str, Any],
        protocol: str,
        seq: int = 0,
    ) -> RunSnapshot:
        return self.broker.enqueue_run(
            run_id,
            agent,
            thread_id,
            input_json,
            protocol,
            make_handlers(self),
            seq=seq,
        )

    async def start_run(
        self,
        agent: AgentRef,
        run_input: dict[str, Any],
        thread_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        presenter_key: str | None = None,
    ) -> RunHandle:
        """Create (or reuse) a thread, open a queued run on it, and enqueue it for dispatch.

        Returns a live `RunHandle` subscribed to the run's event stream — or, if the agent is
        registered but nobody is currently serving it, one carrying the same terminal
        `RUN_ERROR` a caller at either door would get, because the run is recorded `failed` and
        a silent stream would hide that.

        `run_input` is AG-UI-shaped, and this goes through the very
        machinery both doors go through (`doors.open_run` then
        `doors.dispatch`): the caller's metadata is verified and stripped of
        funduq's reserved keys, a KYOK opt-in is honoured, the messages
        enter the thread's history, and funduq's forwarded-props are built.
        Embedding funduq is not a reason to get a weaker entrance than a
        socket would — the same rule in-process providers live under.
        """
        async with self.session() as session:
            caller_metadata, head_key, actor_chain = await verify_caller(session, metadata or {}, presenter_key=presenter_key)
            caller_metadata, kyok = await resolve_kyok(session, caller_metadata)
            resolved_thread_id = await repo.ensure_thread(
                session, agent, thread_id, metadata=caller_metadata,
                create_if_missing=True, head_key=head_key,
            )
            opened = await open_run(
                self, session,
                agent=agent,
                thread_id=resolved_thread_id,
                # An embedder speaks; it does not answer a pending ask. A
                # result has its own verb, `resume_run`.
                entrance="utterance",
                ask=None,
                run_input=run_input,
                metadata=caller_metadata,
                head_key=head_key,
                protocol="ag-ui",
            )
            live = await dispatch(
                self, session,
                InboundRun(
                    agent=agent,
                    messages=run_input.get("messages", []),
                    metadata=caller_metadata,
                    head_key=head_key,
                    actor_chain=actor_chain,
                    kyok=kyok,
                    state=run_input.get("state"),
                    tools=run_input.get("tools"),
                    context=run_input.get("context"),
                    resume=run_input.get("resume"),
                    parent_run_id=run_input.get("parentRunId"),
                    forwarded_props=run_input.get("forwardedProps"),
                    protocol="ag-ui",
                ),
                thread_id=resolved_thread_id,
                run_id=opened.run_id,
                starting_seq=opened.starting_seq,
            )

        return RunHandle(
            run_id=opened.run_id,
            thread_id=resolved_thread_id,
            _broker=self.broker,
            _events=(
                self.broker.subscribe(opened.run_id)
                if live
                else offline_events(resolved_thread_id, opened.run_id)
            ),
        )

    async def resume_run(
        self,
        run_id: str,
        run_input: dict[str, Any],
        metadata: dict | None = None,
        presenter_key: str | None = None,
    ) -> RunHandle:
        """Deliver a deferred call's result back into the run it suspended.

        The run **keeps its id**, because it is the same run: a deferred call is a pause inside
        the agent's loop, not the end of it. The provider sees that pause as an ending — its
        stream really did return — and funduq holds the run's identity across the gap the
        provider cannot hold, invoking the agent again with the result attached and continuing
        the event log from where it stopped.

        Raises `LookupError` if `run_id` doesn't exist, and `NoPendingAsk` if it exists but is
        not waiting for a result — a run that already reached its natural exit has no
        suspension to return to, and running it again would put a second loop under one run's
        id. That is a new run; open one with `start_run`.

        This is the result entrance, and `start_run` is the utterance one. There is no third.
        """
        async with self.session() as session:
            stored = await repo.get_run(session, run_id)
            if stored is None:
                raise LookupError(f"no such run: {run_id}")
            if stored.status != "input-required":
                raise NoPendingAsk(
                    f"run '{run_id}' is {stored.status}, not waiting for a result"
                )
            agent = AgentRef(provider_key=stored.provider_key, name=stored.agent_name)

            caller_metadata, head_key, actor_chain = await verify_caller(session, metadata or {}, presenter_key=presenter_key)
            caller_metadata, kyok = await resolve_kyok(session, caller_metadata)

            opened = await open_run(
                self, session,
                agent=agent,
                thread_id=stored.thread_id,
                entrance="result",
                ask=PendingAsk(run_id=run_id, head_key=stored.head_key),
                run_input=run_input,
                metadata=caller_metadata,
                head_key=head_key,
                protocol=stored.protocol or "ag-ui",
            )
            if opened is None:
                # Another result reached the same ask first. The reopen is
                # status-guarded, so exactly one wins and this one has
                # nothing left to land on.
                raise NoPendingAsk(f"run '{run_id}' is no longer waiting for a result")

            live = await dispatch(
                self, session,
                InboundRun(
                    agent=agent,
                    messages=run_input.get("messages", []),
                    metadata=caller_metadata,
                    head_key=head_key,
                    actor_chain=actor_chain,
                    kyok=kyok,
                    state=run_input.get("state"),
                    tools=run_input.get("tools"),
                    context=run_input.get("context"),
                    resume=run_input.get("resume"),
                    parent_run_id=run_input.get("parentRunId"),
                    forwarded_props=run_input.get("forwardedProps"),
                    protocol=stored.protocol or "ag-ui",
                ),
                thread_id=stored.thread_id,
                run_id=run_id,
                starting_seq=opened.starting_seq,
            )

        return RunHandle(
            run_id=run_id,
            thread_id=stored.thread_id,
            _broker=self.broker,
            _events=(
                self.broker.subscribe(run_id)
                if live
                else offline_events(stored.thread_id, run_id)
            ),
        )

    async def cancel_run(self, run_id: str, *, metadata: dict[str, Any] | None = None) -> bool:
        """Asks the run's provider to stop, after checking whoever asked may.

        On a thread that bound an authority at birth, `metadata["cancel"]`
        must carry a signature from one of the run's authorities — see
        `doors.authorize_cancel`, and it raises `InvalidCancel` otherwise. An
        unbound run needs nothing, which is the behaviour every run had
        before. (The AG-UI door has no cancel verb of its own; A2A's is
        `A2AAdapter.cancel_task`, which comes through here.)

        Returns False for a run funduq is no longer tracking — it has
        already ended, and there is nobody left to ask. Raises
        `RunNotCancellable` for a **paused** run, which is neither: no
        provider is working on it, so there is nothing to relay the request
        to, and False would say it had ended when it is still waiting for an
        answer. That gap used to fall through to False, and through A2A to a
        task returned unchanged with no marker — a cancel that read exactly
        like never having asked.

        The order matters and is the same one every other door check uses:
        authority first, then whether the act is possible at all. Answering
        "not cancellable" to a caller who holds no authority over the run
        would tell them the run's state for free.
        """
        async with self.session() as session:
            stored = await repo.get_run(session, run_id)
        if stored is None:
            return False
        authorize_cancel(stored, metadata or {})
        if stored.status == "input-required":
            raise RunNotCancellable(
                f"run '{run_id}' is paused waiting for a result; no provider is "
                "working on it, so there is nobody to ask to stop"
            )
        return self.broker.request_cancel(run_id)


def _create_engine(settings: CoreSettings):
    is_sqlite = make_url(settings.database_url).get_backend_name() == "sqlite"

    connect_args = (
        {"options": f"-c search_path={quoted_schema(settings.db_schema)},public"}
        if not is_sqlite and settings.db_schema != DEFAULT_DB_SCHEMA
        else {}
    )

    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=not is_sqlite,
        connect_args=connect_args,
    )

    if is_sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine
