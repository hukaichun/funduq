"""Dispatch. Three owners, one boundary each.

- A provider handler owns everything core knows about one provider *key*:
  the live connection (or none), declared capacity and its in-flight count,
  and the conduct counters. It is born the first time the key is seen and
  survives disconnects — a connection is a visitor; the key is the identity.
- A thread handler owns the entire lifecycle of every run on its thread.
  Everything that happens to a run — the verdict included — arrives as a
  message in the thread's one inbox and is acted on by this one owner in
  arrival order. Nothing else writes a run's state.
- Doors attribute; the owner judges. `report_event` and `finish_stream` tag
  the reporting key and post. Whether that key holds the run is decided by
  the thread handler, against state nothing can outrun — the same road the
  verdict took (`answer_offer`), so a verdict and the events that follow it
  are one speaker's consecutive statements and cannot race. `deliver` only
  hands an offer over; it carries no answer.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import deque
from collections.abc import Awaitable, Callable, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from ag_ui.core import RunAgentInput
from funduq_contract import DeliveredRun
from pydantic import ValidationError

from funduq.config import (
    DELIVER_TIMEOUT_SECONDS,
    UNDELIVERED_WINDOW_SECONDS,
    UNSERVED_TIMEOUT_SECONDS,
)
from funduq.models import AgentRef

logger = logging.getLogger("funduq.broker")

END_OF_STREAM = object()


# ---- the record vocabulary (what a run's history is made of) -------------


@dataclass
class Offer:
    """The run has been handed to a provider and funduq is waiting for an answer."""


@dataclass
class Requeue:
    """The offer was not accepted, so the run goes back where it came from."""


@dataclass
class Claim:
    pass


@dataclass
class RelayEvent:

    event: Any


@dataclass
class FinishStream:
    pass


@dataclass
class RequestCancel:
    pass


@dataclass
class Fail:

    reason: str


Command = Offer | Requeue | Claim | RelayEvent | FinishStream | RequestCancel | Fail

HandlerMap = dict[type, Callable[["Run", Any], Awaitable[None]]]


# ---- inbox messages (how anything reaches a thread handler) --------------


@dataclass
class _Queued:
    run: "Run"


@dataclass
class _Answered:
    """A provider's verdict on an outstanding offer, in through `answer_offer`."""

    run_id: str
    provider_key: str
    accepted: Any  # bool, or a Refusal


@dataclass
class _Said:
    """Something a connection reported about a run, in through a door."""

    run_id: str
    origin: str
    command: RelayEvent | FinishStream


@dataclass
class _Trusted:
    """A command funduq itself (or a test) puts on the record, no attribution to judge."""

    run_id: str
    command: Command


@dataclass
class _CancelAsked:
    run_id: str


@dataclass
class _OfferLapsed:
    """The offer's clock ran out, or handing it over failed."""

    run_id: str
    offer_id: int


@dataclass
class _Poke:
    """Something may have changed (a connection arrived, a place freed): look again."""


_Message = _Queued | _Answered | _Said | _Trusted | _CancelAsked | _OfferLapsed | _Poke


# ---- the provider seam ----------------------------------------------------


class Refusal(Protocol):
    """A permanent decline of an offer, read duck-typed off `answer_offer`'s answer: any object with a `reason` string."""

    reason: str


class ConnectedProvider(Protocol):

    public_key: str
    max_concurrent_runs: int | None

    async def deliver(self, run: DeliveredRun) -> None:
        """Hand the offer over. The verdict does not ride the return — it comes back through `answer_offer`."""
        ...

    async def cancel(self, run_id: str) -> bool:
        ...


@dataclass(frozen=True)
class ProviderQuality:
    """Per-provider counters of protocol violations observed while dispatching: declining an offer after claiming to have room (misdeclared), taking a run and never ending it (abandoned), taking one and not delivering it inside the window (undelivered), and not answering an offer within the delivery timeout (unanswered)."""

    in_flight: int
    declared: int | None
    misdeclared: int
    abandoned: int
    undelivered: int
    unanswered: int


_COUNTERS = ("misdeclared", "abandoned", "undelivered", "unanswered")


@dataclass
class _ProviderHandler:
    """One provider key's presence: the connection slot, capacity, and conduct counters. Born the first time the key is seen; a disconnect empties the slot, it does not kill the handler."""

    public_key: str
    connection: ConnectedProvider | None = None
    declared: int | None = None
    in_flight: int = 0
    counters: dict[str, int] = field(
        default_factory=lambda: dict.fromkeys(_COUNTERS, 0)
    )

    @property
    def has_room(self) -> bool:
        return self.declared is None or self.in_flight < self.declared


# ---- runs -----------------------------------------------------------------


@dataclass
class Run:
    """One run, from queued to forgotten."""

    run_id: str
    agent: AgentRef
    thread_id: str
    input_json: dict[str, Any]
    protocol: str
    queued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    seq: int = 0
    round_starting_seq: int = 0
    pause_payload: dict[str, Any] | None = None
    # The run this one asked to join, verbatim from the caller's declaration.
    addressed_run_id: str | None = None
    offered_to: str | None = None
    offered_conn: ConnectedProvider | None = None
    offer_id: int = 0
    verdict_open: bool = False
    offer_timer: asyncio.Task | None = None
    handover_task: asyncio.Task | None = None
    is_interjection: bool = False
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    noted_abnormal: bool = False
    # Set by a record handler that judged the content fatal; the owner ends the run with it.
    poison: str | None = None
    cancel_notify: Callable[[str], Awaitable[bool]] | None = None
    cancel_requested: bool = False
    saw_run_finished: bool = False
    saw_run_error: bool = False
    out_queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)
    settled: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass(frozen=True)
class RunSnapshot:

    run_id: str
    agent: AgentRef
    thread_id: str
    protocol: str
    offered_to: str | None
    claimed_by: str | None
    cancel_requested: bool

    @property
    def is_claimed(self) -> bool:
        return self.claimed_by is not None

    @property
    def is_offered(self) -> bool:
        """Handed to a provider — reserved on it, whether or not it has answered."""
        return self.offered_to is not None


def _snapshot(run: Run) -> RunSnapshot:
    return RunSnapshot(
        run_id=run.run_id,
        agent=run.agent,
        thread_id=run.thread_id,
        protocol=run.protocol,
        offered_to=run.offered_to,
        claimed_by=run.claimed_by,
        cancel_requested=run.cancel_requested,
    )


async def _drain_run(run: Run) -> AsyncIterator[Any]:
    """Yields items placed on `run.out_queue` until the END_OF_STREAM sentinel, then returns."""
    while True:
        item = await run.out_queue.get()
        if item is END_OF_STREAM:
            return
        yield item


async def _no_events() -> AsyncIterator[Any]:
    """An empty async iterator, returned by `subscribe` for an unknown run_id."""
    return
    yield  # pragma: no cover - what makes this an async generator


@dataclass(eq=False)
class _ThreadHandler:
    """One thread's owner: the inbox everything arrives through, and the turn queue. Bound at birth to its agent — the half of that name that is a provider key can never change hands, so the binding is permanent; the connection serving it is looked up fresh at every offer."""

    thread_id: str
    agent: AgentRef
    inbox: asyncio.Queue[_Message] = field(default_factory=asyncio.Queue)
    queue: deque[Run] = field(default_factory=deque)
    live: dict[str, Run] = field(default_factory=dict)
    task: asyncio.Task | None = None
    # Set after a declined or unanswered offer: don't re-offer the same head
    # until something changes (a poke, a new run) — retrying into the same
    # answer is noise, not persistence.
    resting: bool = False


class RunBroker:
    """Matches queued runs to connected providers, one thread's turn at a time, respecting each provider's declared concurrency, and tracks per-provider quality-of-service counters (`ProviderQuality`)."""

    def __init__(
        self,
        spawn=None,
        *,
        sweep_interval_seconds: float = 1.0,
        unserved_timeout_seconds: float = UNSERVED_TIMEOUT_SECONDS,
        deliver_timeout_seconds: float = DELIVER_TIMEOUT_SECONDS,
        undelivered_window_seconds: float = UNDELIVERED_WINDOW_SECONDS,
        quality_tolerance: int | None = None,
    ) -> None:
        self._spawn = spawn or self._spawn_unsupervised
        self._runs: dict[str, Run] = {}
        self._run_threads: dict[str, _ThreadHandler] = {}
        self._threads: dict[str, _ThreadHandler] = {}
        # Who serves an agent is two lookups with one owner each: the agent's
        # current serving key, and that key's handler (connection, capacity,
        # counters). In production the agent's own provider_key and the serving
        # connection's key are the same key; core does not assume it.
        self._serving: dict[AgentRef, str] = {}
        self._providers: dict[str, _ProviderHandler] = {}
        self._agent_threads: dict[AgentRef, set[_ThreadHandler]] = {}
        self._unserved_since: dict[AgentRef, datetime] = {}
        self._handlers: dict[str, HandlerMap] = {}
        self._lane_tasks: set[asyncio.Task] = set()
        self.sweep_interval_seconds = sweep_interval_seconds
        self.undelivered_window_seconds = undelivered_window_seconds
        self.unserved_timeout_seconds = unserved_timeout_seconds
        self.deliver_timeout_seconds = deliver_timeout_seconds
        self.quality_tolerance = quality_tolerance
        self._loop_task: asyncio.Task | None = None
        self._work_to_do = asyncio.Event()
        self._forget_listeners: list[Callable[[str], None]] = []

    # ---- lifecycle ----------------------------------------------------

    def start(self) -> None:
        """Starts the sweep if it isn't already running."""
        if not self.is_running:
            self._work_to_do = asyncio.Event()
            self._loop_task = self._spawn(self.run_forever(), name="broker-sweep")

    @property
    def is_running(self) -> bool:
        return self._loop_task is not None and not self._loop_task.done()

    def stop(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
            self._loop_task = None

    async def run_forever(self) -> None:
        """Runs the two clocks funduq keeps — noting providers that have not delivered what they accepted, and giving up on queued runs whose agent has gone unserved for too long — and pokes every thread handler in case something it was blocked on has changed."""
        while True:
            try:
                self.note_undelivered(self.undelivered_window_seconds)
                self.expire_queued(self.unserved_timeout_seconds)
                self._work_to_do.clear()
                self._poke_threads()
                with contextlib.suppress(TimeoutError):
                    # Sleep no longer than the shortest window this loop observes.
                    async with asyncio.timeout(
                        min(self.unserved_timeout_seconds, self.undelivered_window_seconds)
                    ):
                        await self._work_to_do.wait()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("broker sweep failed; continuing")
                await asyncio.sleep(self.sweep_interval_seconds)

    def _spawn_unsupervised(self, coro, *, name: str | None = None) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._lane_tasks.add(task)
        task.add_done_callback(self._lane_tasks.discard)
        return task

    # ---- intake -------------------------------------------------------

    def enqueue_run(
        self,
        run_id: str,
        agent: AgentRef,
        thread_id: str,
        input_json: dict[str, Any],
        protocol: str,
        handlers: HandlerMap,
        seq: int = 0,
        addressed_run_id: str | None = None,
    ) -> Run | None:
        """Queues a new run for `agent` on its thread's inbox; None if nobody serves the agent."""
        if not self.is_running:
            raise RuntimeError(
                f"run {run_id}: this broker is not running, so nothing would ever be "
                "dispatched — call Funduq.start() (or RunBroker.start()) first"
            )
        if self.serving(agent) is None:
            return None
        run = Run(
            run_id=run_id,
            agent=agent,
            thread_id=thread_id,
            input_json=input_json,
            protocol=protocol,
            seq=seq,
            round_starting_seq=seq,
            addressed_run_id=addressed_run_id,
        )
        handler = self._thread_handler(thread_id, agent)
        self._runs[run_id] = run
        self._run_threads[run_id] = handler
        self._handlers[run_id] = handlers
        handler.inbox.put_nowait(_Queued(run))
        return run

    def _thread_handler(self, thread_id: str, agent: AgentRef) -> _ThreadHandler:
        handler = self._threads.get(thread_id)
        if handler is not None and handler.task is not None and not handler.task.done():
            return handler
        handler = _ThreadHandler(thread_id=thread_id, agent=agent)
        self._agent_threads.setdefault(agent, set()).add(handler)
        self._threads[thread_id] = handler
        handler.task = self._spawn(
            self._thread_main(handler), name=f"thread:{thread_id}"
        )
        return handler

    def _provider(self, public_key: str) -> _ProviderHandler:
        handler = self._providers.get(public_key)
        if handler is None:
            handler = _ProviderHandler(public_key=public_key)
            self._providers[public_key] = handler
        return handler

    # ---- the doors (attribution only; the owner judges) ----------------

    def answer_offer(self, run_id: str, accepted: Any, *, provider_key: str) -> bool:
        """Posts a provider's verdict on an outstanding offer; False for an unknown run. Judged by the run's owner in arrival order — everything the same connection reports afterwards lands behind it."""
        return self._post(run_id, _Answered(run_id, provider_key, accepted))

    def report_event(self, run_id: str, event: Any, *, origin: str) -> bool:
        """Posts a reported event, tagged with the reporting key; False for an unknown run."""
        return self._post(run_id, _Said(run_id, origin, RelayEvent(event)))

    def finish_stream(self, run_id: str, *, origin: str) -> bool:
        """Posts a reported end-of-stream, tagged with the reporting key; False for an unknown run."""
        return self._post(run_id, _Said(run_id, origin, FinishStream()))

    def push(self, run_id: str, command: Command) -> bool:
        """Puts a command on a run's record with funduq's own authority (no attribution to judge); False for an unknown run."""
        return self._post(run_id, _Trusted(run_id, command))

    def request_cancel(self, run_id: str) -> bool:
        """Marks the run cancel-requested and posts the request to its owner."""
        run = self._runs.get(run_id)
        if run is None:
            return False
        run.cancel_requested = True
        return self._post(run_id, _CancelAsked(run_id))

    def _post(self, run_id: str, message: _Message) -> bool:
        handler = self._run_threads.get(run_id)
        if handler is None:
            return False
        handler.inbox.put_nowait(message)
        return True

    # ---- the thread handler --------------------------------------------

    async def _thread_main(self, handler: _ThreadHandler) -> None:
        try:
            while True:
                message = await handler.inbox.get()
                try:
                    await self._on_message(handler, message)
                except Exception:
                    logger.exception(
                        "thread %s: handling %s failed",
                        handler.thread_id,
                        type(message).__name__,
                    )
                # Only leave when nothing is alive AND nothing is waiting to be
                # read — a _Queued already posted must not die in a dead inbox.
                if not handler.live and handler.inbox.empty():
                    break
        finally:
            bound = self._agent_threads.get(handler.agent)
            if bound is not None:
                bound.discard(handler)
                if not bound:
                    self._agent_threads.pop(handler.agent, None)
            if self._threads.get(handler.thread_id) is handler:
                self._threads.pop(handler.thread_id, None)

    async def _on_message(self, handler: _ThreadHandler, message: _Message) -> None:
        if isinstance(message, (_Queued, _Poke)):
            handler.resting = False
        if isinstance(message, _Queued):
            await self._on_queued(handler, message.run)
        elif isinstance(message, _Answered):
            await self._on_answered(handler, message)
        elif isinstance(message, _Said):
            await self._on_said(handler, message)
        elif isinstance(message, _Trusted):
            await self._on_trusted(handler, message)
        elif isinstance(message, _CancelAsked):
            await self._on_cancel_asked(handler, message.run_id)
        elif isinstance(message, _OfferLapsed):
            await self._on_offer_lapsed(handler, message)
        await self._advance(handler)

    async def _on_queued(self, handler: _ThreadHandler, run: Run) -> None:
        handler.live[run.run_id] = run
        head = handler.queue[0] if handler.queue else None
        if (
            head is not None
            and head.claimed_by is not None
            and run.addressed_run_id == head.run_id
        ):
            await self._offer(handler, run, interjection=True)
            return
        handler.queue.append(run)

    async def _on_answered(self, handler: _ThreadHandler, msg: _Answered) -> None:
        run = handler.live.get(msg.run_id)
        if run is None or not run.verdict_open or run.offered_to != msg.provider_key:
            logger.warning(
                "run %s: verdict from '%s' answers no outstanding offer; ignored",
                msg.run_id,
                msg.provider_key[:16],
            )
            return
        run.verdict_open = False
        if run.offer_timer is not None:
            run.offer_timer.cancel()
            run.offer_timer = None

        reason = getattr(msg.accepted, "reason", None)
        if isinstance(reason, str):
            logger.warning(
                "provider %s permanently refused run %s: %s",
                msg.provider_key[:16],
                run.run_id,
                reason,
            )
            self._release(run)
            await self._record(run, Fail(reason))
            await self._settle(handler, run)
            return

        if not msg.accepted:
            self._release(run)
            if run.cancel_requested:
                await self._record(run, RequestCancel())
                await self._settle(handler, run)
                return
            await self._record(run, Requeue())
            self._note_misdeclared(run, msg.provider_key)
            if run.is_interjection:
                self._requeue_interjection(handler, run)
            else:
                self._rest(handler)
            return

        # Accepted: the claim is written here, by the run's one owner, and it
        # was posted before anything the provider said next — order is the queue's.
        run.claimed_by = msg.provider_key
        run.claimed_at = datetime.now(timezone.utc)
        run.cancel_notify = (
            run.offered_conn.cancel if run.offered_conn is not None else None
        )
        await self._record(run, Claim())
        if self.serving(run.agent) is not run.offered_conn:
            # It answered from beyond the roster: the connection left while the
            # offer was out, and nothing will ever finish this run.
            self.push(run.run_id, Fail("provider_left_holding_it"))
            return
        if not run.is_interjection:
            await self._release_interjections(handler, run)
        if run.cancel_requested:
            await self._record(run, RequestCancel())

    async def _on_said(self, handler: _ThreadHandler, msg: _Said) -> None:
        run = handler.live.get(msg.run_id)
        if run is None:
            return
        if run.claimed_by is None:
            logger.warning(
                "report: '%s' spoke about run %s, which nobody holds",
                msg.origin[:16],
                msg.run_id,
            )
            return
        if run.claimed_by != msg.origin:
            logger.warning(
                "report: '%s' spoke about run %s, which is held by '%s'",
                msg.origin[:16],
                msg.run_id,
                run.claimed_by[:16],
            )
            return
        await self._record_and_maybe_settle(handler, run, msg.command)

    async def _on_trusted(self, handler: _ThreadHandler, msg: _Trusted) -> None:
        run = handler.live.get(msg.run_id)
        if run is None:
            return
        command = msg.command
        if isinstance(command, RequestCancel):
            await self._on_cancel_asked(handler, msg.run_id)
            return
        if isinstance(command, Fail):
            if run.claimed_by is not None and not run.noted_abnormal:
                run.noted_abnormal = True
                self._note_abnormal(run.claimed_by, "abandoned")
                logger.warning(
                    "provider %s abandoned run %s (%d so far): took it and never ended it",
                    run.claimed_by[:16],
                    run.run_id,
                    self._provider(run.claimed_by).counters["abandoned"],
                )
            await self._record(run, command)
            await self._settle(handler, run)
            return
        await self._record_and_maybe_settle(handler, run, command)

    async def _record_and_maybe_settle(
        self, handler: _ThreadHandler, run: Run, command: Command
    ) -> None:
        await self._record(run, command)
        if run.poison is not None:
            await self._record(run, Fail(run.poison))
            await self._settle(handler, run)
            return
        if isinstance(command, FinishStream):
            await self._settle(handler, run)

    async def _on_cancel_asked(self, handler: _ThreadHandler, run_id: str) -> None:
        run = handler.live.get(run_id)
        if run is None:
            return
        run.cancel_requested = True
        if run.verdict_open:
            # A verdict is pending; its arrival settles what the cancel means.
            return
        if run.claimed_by is not None:
            await self._record(run, RequestCancel())
            return
        await self._record(run, RequestCancel())
        await self._settle(handler, run)

    async def _on_offer_lapsed(self, handler: _ThreadHandler, msg: _OfferLapsed) -> None:
        run = handler.live.get(msg.run_id)
        if run is None or not run.verdict_open or run.offer_id != msg.offer_id:
            return
        run.verdict_open = False
        if run.offer_timer is not None:
            run.offer_timer.cancel()
            run.offer_timer = None
        if run.handover_task is not None and not run.handover_task.done():
            # The offer lapsed with the hand-over still in flight (a provider
            # that never answers): reclaim the task the way the old timeout did.
            run.handover_task.cancel()
        run.handover_task = None
        key = run.offered_to
        if key is not None:
            self._note_abnormal(key, "unanswered")
            logger.warning(
                "provider %s did not answer an offer of run %s within %ss (%d so far)",
                key[:16],
                run.run_id,
                self.deliver_timeout_seconds,
                self._provider(key).counters["unanswered"],
            )
        self._release(run)
        if run.cancel_requested:
            await self._record(run, RequestCancel())
            await self._settle(handler, run)
            return
        await self._record(run, Requeue())
        if run.is_interjection:
            self._requeue_interjection(handler, run)
        else:
            self._rest(handler)

    def _rest(self, handler: _ThreadHandler) -> None:
        """After a declined or unanswered offer: pause, then look again. The retry is the handler's own clock, not a broadcast it hopes to catch."""
        handler.resting = True
        self._spawn(
            self._retry_later(handler), name=f"retry:{handler.thread_id}"
        )

    async def _retry_later(self, handler: _ThreadHandler) -> None:
        await asyncio.sleep(self.sweep_interval_seconds)
        handler.inbox.put_nowait(_Poke())

    # ---- offers ---------------------------------------------------------

    async def _advance(self, handler: _ThreadHandler) -> None:
        """Offers the head of the queue if the turn is free and a connection with room is present."""
        while handler.queue and handler.queue[0].settled.is_set():
            handler.queue.popleft()
        if not handler.queue or handler.resting:
            return
        run = handler.queue[0]
        if run.claimed_by is not None or run.verdict_open or run.offered_to is not None:
            return
        await self._offer(handler, run, interjection=False)

    async def _offer(
        self, handler: _ThreadHandler, run: Run, *, interjection: bool
    ) -> None:
        connection = self.serving(run.agent)
        provider = (
            self._provider(connection.public_key) if connection is not None else None
        )
        if connection is None or not provider.has_room:
            if interjection:
                handler.queue.insert(min(1, len(handler.queue)), run)
            return
        try:
            delivered = DeliveredRun(
                run_id=run.run_id,
                agent_name=run.agent.name,
                run_input=RunAgentInput.model_validate(run.input_json),
                thread_id=run.thread_id,
            )
        except ValidationError as e:
            await self._record(run, Fail(f"input does not validate as RunAgentInput: {e}"))
            await self._settle(handler, run)
            return
        run.offered_to = provider.public_key
        run.offered_conn = connection
        run.is_interjection = interjection
        provider.in_flight += 1
        run.offer_id += 1
        run.verdict_open = True
        await self._record(run, Offer())
        run.handover_task = self._spawn(
            self._hand_over(handler, connection, delivered, run.run_id, run.offer_id),
            name=f"offer:{run.run_id}",
        )
        run.offer_timer = self._spawn(
            self._offer_clock(handler, run.run_id, run.offer_id),
            name=f"offer-clock:{run.run_id}",
        )

    async def _hand_over(
        self,
        handler: _ThreadHandler,
        connection: ConnectedProvider,
        delivered: DeliveredRun,
        run_id: str,
        offer_id: int,
    ) -> None:
        try:
            await connection.deliver(delivered)
        except Exception:
            logger.exception("run %s: delivering to its provider failed", run_id)
            handler.inbox.put_nowait(_OfferLapsed(run_id, offer_id))

    async def _offer_clock(
        self, handler: _ThreadHandler, run_id: str, offer_id: int
    ) -> None:
        await asyncio.sleep(self.deliver_timeout_seconds)
        handler.inbox.put_nowait(_OfferLapsed(run_id, offer_id))

    def _requeue_interjection(self, handler: _ThreadHandler, run: Run) -> None:
        """A declined or unanswered interjection simply becomes the thread's next turn."""
        if run.is_interjection:
            run.is_interjection = False
            handler.queue.insert(min(1, len(handler.queue)), run)

    async def _release_interjections(self, handler: _ThreadHandler, head: Run) -> None:
        """Pull every queued run addressed to the claimed head and offer it now, beside the turn it joins."""
        joining = [
            run
            for run in list(handler.queue)[1:]
            if run.addressed_run_id == head.run_id and not run.settled.is_set()
        ]
        for run in joining:
            handler.queue.remove(run)
            await self._offer(handler, run, interjection=True)

    def _note_misdeclared(self, run: Run, provider_key: str) -> None:
        provider = self._provider(provider_key)
        if provider.has_room:
            # Declining while claiming room is one abnormal event, and that is all it is.
            self._note_abnormal(provider_key, "misdeclared")
            logger.warning(
                "provider %s declined run %s while funduq believed it had room "
                "(%d/%s in flight); counted, not believed",
                provider_key[:16],
                run.run_id,
                provider.in_flight,
                provider.declared,
            )

    # ---- capacity ------------------------------------------------------

    def _release(self, run: Run) -> None:
        """Gives back the place an offer took."""
        key, run.offered_to = run.offered_to, None
        run.offered_conn = None
        provider = self._providers.get(key) if key is not None else None
        if provider is not None and provider.in_flight > 0:
            provider.in_flight -= 1

    # ---- the record ----------------------------------------------------

    async def _record(self, run: Run, command: Command) -> None:
        """Runs one command's handler."""
        handler = (self._handlers.get(run.run_id) or {}).get(type(command))
        if handler is None:
            logger.warning(
                "run %s: no handler registered for %s", run.run_id, type(command).__name__
            )
            return
        try:
            await handler(run, command)
        except Exception:
            logger.exception(
                "run %s: recording %s failed", run.run_id, type(command).__name__
            )

    async def _settle(self, handler: _ThreadHandler, run: Run) -> None:
        """Ends the run's stream and drops everything held for it."""
        run.settled.set()
        run.out_queue.put_nowait(END_OF_STREAM)
        if run.offer_timer is not None:
            run.offer_timer.cancel()
            run.offer_timer = None
        handler.live.pop(run.run_id, None)
        with contextlib.suppress(ValueError):
            handler.queue.remove(run)
        self.forget(run.run_id)

    def forget(self, run_id: str) -> None:
        """Drops a run's tracked state and handlers, gives back the place it was holding, and signals the sweep — a freed place is news."""
        run = self._runs.pop(run_id, None)
        self._run_threads.pop(run_id, None)
        self._handlers.pop(run_id, None)
        if run is not None:
            run.settled.set()
            if run.offered_to is not None:
                self._release(run)
            self._work_to_do.set()
            self._poke_threads()
        for listener in self._forget_listeners:
            listener(run_id)

    def add_forget_listener(self, listener: Callable[[str], None]) -> None:
        self._forget_listeners.append(listener)

    # ---- provider roster ----------------------------------------------

    def register_provider(self, mapping: dict[AgentRef, ConnectedProvider]) -> None:
        """Registers (or replaces) the connection serving each given agent and pokes the thread handlers bound to those agents."""
        for ref, connection in mapping.items():
            self._serving[ref] = connection.public_key
            provider = self._provider(connection.public_key)
            provider.connection = connection
            # A re-registration re-declares: the count survives, the limit is the new one.
            provider.declared = connection.max_concurrent_runs
            self._unserved_since.pop(ref, None)
        self._work_to_do.set()
        for ref in mapping:
            self._poke_agent(ref)

    def serving(self, agent: AgentRef) -> ConnectedProvider | None:
        key = self._serving.get(agent)
        if key is None:
            return None
        return self._providers[key].connection

    def agents_served_by(self, public_key: str) -> list[AgentRef]:
        return [ref for ref, key in self._serving.items() if key == public_key]

    def unregister_provider(self, agents: list[AgentRef]) -> None:
        """Takes `agents` out of service and fails every run their connection was holding."""
        now = datetime.now(timezone.utc)
        for ref in agents:
            if self._serving.pop(ref, None) is None:
                continue
            self._unserved_since[ref] = now
            for run in list(self._runs.values()):
                if run.agent != ref or run.claimed_by is None:
                    continue
                # Took work and will never end it — the same fact, and the same counter, as any other abandonment.
                self.push(run.run_id, Fail("provider_left_holding_it"))
            self._poke_agent(ref)

    def _poke_agent(self, agent: AgentRef) -> None:
        for handler in list(self._agent_threads.get(agent, ())):
            handler.inbox.put_nowait(_Poke())

    def _note_abnormal(self, public_key: str, event: str) -> None:
        """Records one abnormal event and applies the tolerance."""
        provider = self._provider(public_key)
        provider.counters[event] += 1
        tolerance = self.quality_tolerance
        if tolerance is None or provider.counters[event] < tolerance:
            return
        agents = self.agents_served_by(public_key)
        if agents:
            self.unregister_provider(agents)
            logger.warning(
                "provider %s reached the abnormality allowance (%s: %d of %d); "
                "withdrawn from service — re-registration is the way back",
                public_key[:16],
                event,
                provider.counters[event],
                tolerance,
            )

    # ---- observation ---------------------------------------------------

    def get(self, run_id: str) -> RunSnapshot | None:
        run = self._runs.get(run_id)
        return _snapshot(run) if run is not None else None

    def subscribe(self, run_id: str) -> AsyncIterator[Any]:
        """Returns an async iterator of whatever is pushed to `run_id`'s out_queue, ending when the run settles; an empty iterator if `run_id` is unknown."""
        run = self._runs.get(run_id)
        return _drain_run(run) if run is not None else _no_events()

    def _poke_threads(self) -> None:
        for handler in list(self._threads.values()):
            handler.inbox.put_nowait(_Poke())

    # ---- the two clocks ------------------------------------------------

    def note_undelivered(self, window_seconds: float) -> list[str]:
        """Counts one `undelivered` against every provider still holding a run it accepted `window_seconds` ago and has not delivered, and returns those run ids."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        noted: list[str] = []
        for run in list(self._runs.values()):
            if run.claimed_by is None or run.noted_abnormal or run.claimed_at is None:
                continue
            if run.claimed_at > cutoff:
                continue
            run.noted_abnormal = True
            noted.append(run.run_id)
            logger.warning(
                "provider %s has not delivered run %s within %ss (%d so far)",
                run.claimed_by[:16],
                run.run_id,
                window_seconds,
                self._provider(run.claimed_by).counters["undelivered"] + 1,
            )
            self._note_abnormal(run.claimed_by, "undelivered")
        return noted

    def expire_queued(self, timeout_seconds: float) -> list[str]:
        """Gives up on queued (unclaimed, unoffered) runs whose agent has had no serving provider for longer than `timeout_seconds`, failing each with `Fail("no_provider_took_it")`, and returns their run_ids."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        expired: list[str] = []
        for run in list(self._runs.values()):
            if run.claimed_by is not None or run.offered_to is not None:
                continue
            if self.serving(run.agent) is not None:
                continue
            unserved_since = self._unserved_since.get(run.agent)
            reference = (
                max(run.queued_at, unserved_since) if unserved_since else run.queued_at
            )
            if reference > cutoff:
                continue
            expired.append(run.run_id)
            self.push(run.run_id, Fail("no_provider_took_it"))
        return expired

    def active_run_ids(self) -> list[str]:
        return list(self._runs)

    def quality(self) -> dict[str, ProviderQuality]:
        return {
            key: ProviderQuality(
                in_flight=p.in_flight,
                declared=p.declared,
                **{name: p.counters[name] for name in _COUNTERS},
            )
            for key, p in self._providers.items()
        }
