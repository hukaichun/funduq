"""Dispatch, shaped like the protocol.

One thread has one loop: offer the head, wait for the verdict, wait for the
finish, take the next. The gate at finish is not a rule anybody checks — it
is the loop standing on `await settled`. The only bypass is an interjection,
released exactly when the run it names becomes the thread's claimed head.

Each run keeps one inbound queue (`in_queue`) for what happens to it —
claim, relayed events, finish, cancel, failure — drained by one pump in
arrival order, so a run's record is ordered by construction.
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
from funduq.live_roster import LiveRoster
from funduq.models import AgentRef

logger = logging.getLogger("funduq.broker")

END_OF_STREAM = object()


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


@dataclass(frozen=True)
class ProviderQuality:
    """Per-provider counters of protocol violations observed while dispatching: declining an offer after claiming to have room (misdeclared), taking a run and never ending it (abandoned), taking one and not delivering it inside the window (undelivered), and not answering an offer within the delivery timeout (unanswered)."""

    in_flight: int
    declared: int | None
    misdeclared: int
    abandoned: int
    undelivered: int
    unanswered: int


@dataclass
class _Capacity:
    """Tracks one provider's in-flight run count against its declared limit."""

    declared: int | None
    in_flight: int = 0

    @property
    def has_room(self) -> bool:
        return self.declared is None or self.in_flight < self.declared


class Refusal(Protocol):
    """A permanent decline of an offer, read duck-typed off `deliver`'s return: any object with a `reason` string."""

    reason: str


class ConnectedProvider(Protocol):

    public_key: str
    max_concurrent_runs: int | None

    async def deliver(self, run: DeliveredRun) -> bool | Refusal:
        ...

    async def cancel(self, run_id: str) -> bool:
        ...


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
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    noted_abnormal: bool = False
    cancel_notify: Callable[[str], Awaitable[bool]] | None = None
    cancel_requested: bool = False
    saw_run_finished: bool = False
    saw_run_error: bool = False
    in_queue: asyncio.Queue[Command] = field(default_factory=asyncio.Queue)
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


HandlerMap = dict[type, Callable[[Run, Any], Awaitable[None]]]


@dataclass
class _Thread:
    """One thread's turn-taking: the queue of runs and the loop that walks it."""

    queue: deque[Run] = field(default_factory=deque)
    wake: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None


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
        self._threads: dict[str, _Thread] = {}
        self._live = LiveRoster(("misdeclared", "abandoned", "undelivered", "unanswered"))
        self._unserved_since: dict[AgentRef, datetime] = {}
        self._capacity: dict[str, _Capacity] = {}
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
        """Runs the two clocks funduq keeps — noting providers that have not delivered what they accepted, and giving up on queued runs whose agent has gone unserved for too long — and wakes every waiting thread in case something it was blocked on has changed."""
        while True:
            try:
                self.note_undelivered(self.undelivered_window_seconds)
                self.expire_queued(self.unserved_timeout_seconds)
                self._work_to_do.clear()
                self._wake_threads()
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
        """Queues a new run for `agent` on its thread's loop; None if nobody serves the agent."""
        if not self.is_running:
            raise RuntimeError(
                f"run {run_id}: this broker is not running, so nothing would ever be "
                "dispatched — call Funduq.start() (or RunBroker.start()) first"
            )
        if self._live.serving(agent) is None:
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
        self._runs[run_id] = run
        self._handlers[run_id] = handlers
        self._spawn(self._record_pump(run), name=f"run:{run_id}")
        thread = self._threads.get(thread_id)
        if thread is None or thread.task is None or thread.task.done():
            thread = _Thread()
            self._threads[thread_id] = thread
            thread.queue.append(run)
            thread.task = self._spawn(
                self._thread_loop(thread_id, thread), name=f"thread:{thread_id}"
            )
        else:
            thread.queue.append(run)
            thread.wake.set()
            head = thread.queue[0]
            if head.claimed_by is not None:
                self._release_interjections(thread, head)
        return run

    # ---- the thread loop ----------------------------------------------

    async def _thread_loop(self, thread_id: str, thread: _Thread) -> None:
        """One thread's whole life: offer the head, wait for the verdict, wait for the finish, take the next."""
        while True:
            while thread.queue and thread.queue[0].settled.is_set():
                thread.queue.popleft()
            if not thread.queue:
                break
            run = thread.queue[0]
            provider = self._live.serving(run.agent)
            if provider is None or not self._take_place(run, provider):
                await self._wait(thread)
                continue

            verdict = await self._offer_one(run, provider)

            if verdict == "accepted":
                self._claim(run, provider)
                if self._live.serving(run.agent) is not provider:
                    # It answered from beyond the roster: the provider left while
                    # the offer was out, and nothing will ever finish this run.
                    self.push(run.run_id, Fail("provider_left_holding_it"))
                else:
                    self._release_interjections(thread, run)
                await run.settled.wait()
                continue

            self._release(run)
            if verdict == "settled":
                await run.settled.wait()
                continue
            if run.cancel_requested:
                # The offer came back unaccepted and someone asked to stop:
                # nothing holds the run any more, so the ask lands now.
                run.in_queue.put_nowait(RequestCancel())
                await run.settled.wait()
                continue
            await self._record(run, Requeue())
            if verdict == "declined":
                self._note_misdeclared(run, provider)
            await self._wait(thread)
        if self._threads.get(thread_id) is thread:
            self._threads.pop(thread_id, None)

    def _claim(self, run: Run, provider: ConnectedProvider) -> None:
        """Records that `provider` accepted `run`. The claim rides the run's own pump so it lands before any event the provider reports."""
        run.claimed_by = provider.public_key
        run.claimed_at = datetime.now(timezone.utc)
        run.cancel_notify = provider.cancel
        run.in_queue.put_nowait(Claim())
        if run.cancel_requested:
            run.in_queue.put_nowait(RequestCancel())

    def _note_misdeclared(self, run: Run, provider: ConnectedProvider) -> None:
        capacity = self._capacity.get(provider.public_key)
        if capacity is not None and capacity.has_room:
            # Declining while claiming room is one abnormal event, and that is all it is.
            self._note_abnormal(provider.public_key, "misdeclared")
            logger.warning(
                "provider %s declined run %s while funduq believed it had room "
                "(%d/%s in flight); counted, not believed",
                provider.public_key[:16],
                run.run_id,
                capacity.in_flight,
                capacity.declared,
            )

    async def _offer_one(self, run: Run, provider: ConnectedProvider) -> str:
        """One offer, one verdict: 'accepted', 'declined', 'unanswered', or 'settled' (the run died here)."""
        try:
            delivered = DeliveredRun(
                run_id=run.run_id,
                agent_name=run.agent.name,
                run_input=RunAgentInput.model_validate(run.input_json),
                thread_id=run.thread_id,
            )
        except ValidationError as e:
            run.in_queue.put_nowait(Fail(f"input does not validate as RunAgentInput: {e}"))
            return "settled"

        await self._record(run, Offer())
        try:
            async with asyncio.timeout(self.deliver_timeout_seconds):
                answer = await provider.deliver(delivered)
        except TimeoutError:
            self._note_abnormal(provider.public_key, "unanswered")
            logger.warning(
                "provider %s did not answer an offer of run %s within %ss (%d so far)",
                provider.public_key[:16],
                run.run_id,
                self.deliver_timeout_seconds,
                self._live.count(provider.public_key, "unanswered"),
            )
            return "unanswered"
        except Exception:
            self._note_abnormal(provider.public_key, "unanswered")
            logger.exception("run %s: delivering to its provider failed", run.run_id)
            return "unanswered"

        reason = getattr(answer, "reason", None)
        if isinstance(reason, str):
            logger.warning(
                "provider %s permanently refused run %s: %s",
                provider.public_key[:16],
                run.run_id,
                reason,
            )
            run.in_queue.put_nowait(Fail(reason))
            return "settled"
        return "accepted" if answer else "declined"

    async def _wait(self, thread: _Thread) -> None:
        thread.wake.clear()
        await thread.wake.wait()

    def _wake_threads(self) -> None:
        for thread in list(self._threads.values()):
            thread.wake.set()

    # ---- interjections -------------------------------------------------

    def _release_interjections(self, thread: _Thread, head: Run) -> None:
        """Pull every queued run addressed to the claimed head and offer it now, beside the turn it joins."""
        joining = [
            run
            for run in list(thread.queue)[1:]
            if run.addressed_run_id == head.run_id and not run.settled.is_set()
        ]
        for run in joining:
            thread.queue.remove(run)
            self._spawn(self._interject(run, thread), name=f"interject:{run.run_id}")

    async def _interject(self, run: Run, thread: _Thread) -> None:
        """Offer an interjection beside the running turn. Declined or unanswered, it rejoins the queue right behind the head and simply becomes the thread's next turn."""
        provider = self._live.serving(run.agent)
        if provider is None or not self._take_place(run, provider):
            thread.queue.insert(min(1, len(thread.queue)), run)
            return
        verdict = await self._offer_one(run, provider)
        if verdict == "accepted":
            self._claim(run, provider)
            if self._live.serving(run.agent) is not provider:
                self.push(run.run_id, Fail("provider_left_holding_it"))
            return
        self._release(run)
        if verdict == "settled":
            return
        await self._record(run, Requeue())
        thread.queue.insert(min(1, len(thread.queue)), run)

    # ---- capacity ------------------------------------------------------

    def _take_place(self, run: Run, provider: ConnectedProvider) -> bool:
        """Takes `run`'s place on `provider` if there is one, and says whether it got it."""
        capacity = self._capacity.get(provider.public_key)
        if capacity is not None and not capacity.has_room:
            return False
        run.offered_to = provider.public_key
        if capacity is not None:
            capacity.in_flight += 1
        return True

    def _release(self, run: Run) -> None:
        """Gives back the place `_take_place` took."""
        key, run.offered_to = run.offered_to, None
        capacity = self._capacity.get(key) if key is not None else None
        if capacity is not None and capacity.in_flight > 0:
            capacity.in_flight -= 1

    # ---- the record pump -----------------------------------------------

    async def _record_pump(self, run: Run) -> None:
        """Drains a run's inbound commands in arrival order, from queued until forgotten."""
        while True:
            cmd = await run.in_queue.get()
            if isinstance(cmd, RequestCancel):
                if run.claimed_by is None and run.offered_to is not None:
                    # A verdict is pending; the thread loop settles this after it lands.
                    continue
                await self._record(run, cmd)
                if run.claimed_by is None:
                    break
                continue
            await self._record(run, cmd)
            if isinstance(cmd, (FinishStream, Fail)):
                break
        run.out_queue.put_nowait(END_OF_STREAM)
        self.forget(run.run_id)

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

    # ---- provider roster ----------------------------------------------

    def register_provider(self, mapping: dict[AgentRef, ConnectedProvider]) -> None:
        """Registers (or replaces) the provider serving each given agent and wakes every waiting thread."""
        self._live.attach(mapping)
        for agent in mapping:
            self._unserved_since.pop(agent, None)
        for provider in mapping.values():
            capacity = self._capacity.setdefault(
                provider.public_key, _Capacity(declared=provider.max_concurrent_runs)
            )
            # A re-registration re-declares: the count survives, the limit is the new one.
            capacity.declared = provider.max_concurrent_runs
        self._work_to_do.set()
        self._wake_threads()

    def serving(self, agent: AgentRef) -> ConnectedProvider | None:
        return self._live.serving(agent)

    def agents_served_by(self, public_key: str) -> list[AgentRef]:
        return self._live.served_by(public_key)

    def unregister_provider(self, agents: list[AgentRef]) -> None:
        """Takes `agents` off the live roster and fails every run that was in their provider's hands."""
        now = datetime.now(timezone.utc)
        self._live.withdraw(agents)
        for agent in agents:
            if self._live.serving(agent) is not None:
                continue
            self._unserved_since[agent] = now
            for run in list(self._runs.values()):
                if run.agent != agent or run.claimed_by is None:
                    continue
                # Took work and will never end it — the same fact, and the same counter, as any other abandonment.
                self.push(run.run_id, Fail("provider_left_holding_it"))
        self._wake_threads()

    def _note_abnormal(self, public_key: str, event: str) -> None:
        """Records one abnormal event and applies the tolerance."""
        self._live.note(public_key, event)
        tolerance = self.quality_tolerance
        if tolerance is None or self._live.count(public_key, event) < tolerance:
            return
        agents = self.agents_served_by(public_key)
        if agents:
            self.unregister_provider(agents)
            logger.warning(
                "provider %s reached the abnormality allowance (%s: %d of %d); "
                "withdrawn from service — re-registration is the way back",
                public_key[:16],
                event,
                self._live.count(public_key, event),
                tolerance,
            )

    # ---- observation and control --------------------------------------

    def get(self, run_id: str) -> RunSnapshot | None:
        run = self._runs.get(run_id)
        return _snapshot(run) if run is not None else None

    def push(self, run_id: str, command: Command) -> bool:
        """Enqueues `command` on a run's own record pump."""
        run = self._runs.get(run_id)
        if run is None:
            return False
        if isinstance(command, Fail) and run.claimed_by is not None and not run.noted_abnormal:
            run.noted_abnormal = True
            self._note_abnormal(run.claimed_by, "abandoned")
            logger.warning(
                "provider %s abandoned run %s (%d so far): took it and never ended it",
                run.claimed_by[:16],
                run_id,
                self._live.count(run.claimed_by, "abandoned"),
            )
        run.in_queue.put_nowait(command)
        return True

    def subscribe(self, run_id: str) -> AsyncIterator[Any]:
        """Returns an async iterator of whatever is pushed to `run_id`'s out_queue, ending when the run settles; an empty iterator if `run_id` is unknown."""
        run = self._runs.get(run_id)
        return _drain_run(run) if run is not None else _no_events()

    def request_cancel(self, run_id: str) -> bool:
        """Marks the run cancel-requested and puts the request on its pump."""
        run = self._runs.get(run_id)
        if run is None:
            return False
        run.cancel_requested = True
        run.in_queue.put_nowait(RequestCancel())
        return True

    def forget(self, run_id: str) -> None:
        """Drops a run's tracked state and handlers, gives back the place it was holding, and wakes every waiting thread — a freed place is news."""
        run = self._runs.pop(run_id, None)
        self._handlers.pop(run_id, None)
        if run is not None:
            run.settled.set()
            if run.offered_to is not None:
                self._release(run)
            self._work_to_do.set()
            self._wake_threads()
        for listener in self._forget_listeners:
            listener(run_id)

    def add_forget_listener(self, listener: Callable[[str], None]) -> None:
        self._forget_listeners.append(listener)

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
                self._live.count(run.claimed_by, "undelivered") + 1,
            )
            self._note_abnormal(run.claimed_by, "undelivered")
        return noted

    def expire_queued(self, timeout_seconds: float) -> list[str]:
        """Gives up on queued (unclaimed, unoffered) runs whose agent has had no serving provider for longer than `timeout_seconds`, failing each with `Fail("no_provider_took_it")`, and returns their run_ids."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        expired: list[str] = []
        for thread in list(self._threads.values()):
            for run in list(thread.queue):
                if run.claimed_by is not None or run.offered_to is not None:
                    continue
                if self._live.serving(run.agent) is not None:
                    continue
                unserved_since = self._unserved_since.get(run.agent)
                reference = (
                    max(run.queued_at, unserved_since) if unserved_since else run.queued_at
                )
                if reference > cutoff:
                    continue
                expired.append(run.run_id)
                run.in_queue.put_nowait(Fail("no_provider_took_it"))
        return expired

    def active_run_ids(self) -> list[str]:
        return list(self._runs)

    def quality(self) -> dict[str, ProviderQuality]:
        counters = self._live.counters()
        return {
            key: ProviderQuality(
                in_flight=c.in_flight,
                declared=c.declared,
                **{
                    name: counters.get(key, {}).get(name, 0)
                    for name in (
                        "misdeclared",
                        "abandoned",
                        "undelivered",
                        "unanswered",
                    )
                },
            )
            for key, c in self._capacity.items()
        }
