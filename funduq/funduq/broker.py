from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from ag_ui.core import RunAgentInput
from funduq_contract import DeliveredRun
from pydantic import ValidationError

from funduq.live_roster import LiveRoster
from funduq.models import AgentRef

logger = logging.getLogger("funduq.broker")

END_OF_STREAM = object()


@dataclass
class TryDispatch:
    """Something changed that might let this run be handed over: it was just queued, the utterance ahead of it left, a place freed, a provider attached."""
    pass


@dataclass
class ProviderGone:
    """The named provider stopped serving."""

    public_key: str


@dataclass
class Offer:
    """The run has been handed to a provider and funduq is waiting for an answer."""
    pass


@dataclass
class Requeue:
    """The offer was not accepted, so the run goes back where it came from."""
    pass


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


Command = (
    TryDispatch | ProviderGone | Offer | Requeue | Claim | RelayEvent
    | FinishStream | RequestCancel | Fail
)


@dataclass(frozen=True)
class ProviderQuality:
    """Per-provider counters of protocol violations observed while dispatching: declining an offer after claiming to have room (misdeclared), taking a run and never ending it (abandoned), taking one and not delivering it inside the window (undelivered), not answering an offer within the delivery timeout (unanswered), and acking after funduq gave up waiting (answered_late)."""

    in_flight: int
    declared: int | None
    misdeclared: int
    abandoned: int
    undelivered: int
    unanswered: int
    answered_late: int


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

    def cancel(self, run_id: str) -> None:
        ...


@dataclass
class Run:
    """A broker-side run's mutable dispatch state: its position in the pending queue, which provider (if any) has claimed it, and the in/out queues that feed its own lane."""

    run_id: str
    agent: AgentRef
    thread_id: str
    input_json: dict[str, Any]
    protocol: str
    queued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    seq: int = 0
    round_starting_seq: int = 0
    pause_payload: dict[str, Any] | None = None
    # The provider this run is reserved on — set the moment the offer leaves, cleared if it comes back unaccepted.
    offered_to: str | None = None
    # Whether an unanswered "can I be handed over now?" is already in this run's queue.
    dispatch_pending: bool = False
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    noted_abnormal: bool = False
    cancel_notify: Callable[[str], None] | None = None
    cancel_requested: bool = False
    saw_run_finished: bool = False
    saw_run_error: bool = False
    in_queue: asyncio.Queue[Command] = field(default_factory=asyncio.Queue)
    out_queue: asyncio.Queue[Any] = field(default_factory=asyncio.Queue)


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
    """Yields items placed on `run.out_queue` until the END_OF_STREAM sentinel (put there when the run's lane finishes), then returns."""
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

async def _lane(run: Run, owner: "RunBroker") -> None:
    """A run's own lane, from the moment it is queued until it is forgotten."""
    while True:
        cmd = await run.in_queue.get()
        if isinstance(cmd, TryDispatch):
            run.dispatch_pending = False
            await owner._try_dispatch(run)
            continue
        if isinstance(cmd, ProviderGone):
            if run.claimed_by == cmd.public_key:
                # Took work and will never end it — the same fact, and the same counter, as any other abandonment.
                owner.push(run.run_id, Fail("provider_left_holding_it"))
            continue
        await owner._record(run, cmd)
        if isinstance(cmd, (FinishStream, Fail)):
            break
        if isinstance(cmd, RequestCancel) and run.claimed_by is None:
            break
    run.out_queue.put_nowait(END_OF_STREAM)
    owner.forget(run.run_id)


class RunBroker:
    """Matches queued runs to connected providers, one agent's pending runs at a time, respecting each provider's declared concurrency, and tracks per-provider quality-of-service counters (`ProviderQuality`)."""

    def __init__(
        self,
        spawn=None,
        *,
        sweep_interval_seconds: float = 1.0,
        unserved_timeout_seconds: float = 45.0,
        deliver_timeout_seconds: float = 5.0,
        undelivered_window_seconds: float = 1800.0,
        quality_tolerance: int | None = None,
    ) -> None:
        self._spawn = spawn or self._spawn_unsupervised
        self._runs: dict[str, Run] = {}
        # Keyed by thread, because a thread is the pipe whose delivery order funduq guarantees.
        self._pending_by_thread: dict[str, deque[str]] = defaultdict(deque)
        self._live = LiveRoster(
            ("misdeclared", "abandoned", "undelivered", "unanswered", "answered_late")
        )
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

    def add_forget_listener(self, listener: Callable[[str], None]) -> None:
        self._forget_listeners.append(listener)

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
        """Runs the two clocks funduq keeps — noting providers that have not delivered what they accepted, and giving up on queued runs whose agent has gone unserved for too long — and nudges the head of every waiting conversation in case something it was blocked on has changed."""
        while True:
            try:
                self.note_undelivered(self.undelivered_window_seconds)
                self.expire_queued(self.unserved_timeout_seconds)
                self._work_to_do.clear()
                self._nudge_waiting()
                with contextlib.suppress(TimeoutError):
                    # Sleep no longer than the shortest window this loop is responsible for observing, or the observation misses it.
                    async with asyncio.timeout(
                        min(self.unserved_timeout_seconds, self.undelivered_window_seconds)
                    ):
                        await self._work_to_do.wait()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("broker sweep failed; continuing")
                await asyncio.sleep(self.sweep_interval_seconds)

    def enqueue_run(
        self,
        run_id: str,
        agent: AgentRef,
        thread_id: str,
        input_json: dict[str, Any],
        protocol: str,
        handlers: HandlerMap,
        seq: int = 0,
    ) -> Run | None:
        """Queues a new run for `agent`, gives it its own lane, and — if it is its conversation's turn — asks that lane to try handing it over."""
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
        )
        self._runs[run_id] = run
        self._handlers[run_id] = handlers
        queue = self._pending_by_thread[thread_id]
        queue.append(run_id)
        self._spawn(_lane(run, self), name=f"run:{run_id}")
        if queue[0] == run_id:
            self._nudge(run_id)
        return run

    def register_provider(self, mapping: dict[AgentRef, ConnectedProvider]) -> None:
        """Registers (or replaces) the provider serving each given agent and nudges every waiting conversation."""
        self._live.attach(mapping)
        for agent in mapping:
            self._unserved_since.pop(agent, None)
        for provider in mapping.values():
            self._capacity.setdefault(
                provider.public_key, _Capacity(declared=provider.max_concurrent_runs)
            )
        self._work_to_do.set()
        self._nudge_waiting()

    def serving(self, agent: AgentRef) -> ConnectedProvider | None:
        return self._live.serving(agent)

    def agents_served_by(self, public_key: str) -> list[AgentRef]:
        return self._live.served_by(public_key)

    def unregister_provider(self, agents: list[AgentRef]) -> None:
        """Takes `agents` off the live roster and tells every run that was in their provider's hands."""
        now = datetime.now(timezone.utc)
        self._live.withdraw(agents)
        for agent in agents:
            if self._live.serving(agent) is not None:
                continue
            self._unserved_since[agent] = now
            for run in list(self._runs.values()):
                if run.agent != agent:
                    continue
                key = run.claimed_by or run.offered_to
                if key is not None:
                    run.in_queue.put_nowait(ProviderGone(key))

    def _nudge_waiting(self) -> None:
        """Asks the head of every waiting conversation to try handing itself over."""
        for queue in list(self._pending_by_thread.values()):
            if queue:
                self._nudge(queue[0])

    def _nudge(self, run_id: str) -> None:
        run = self._runs.get(run_id)
        if run is None or run.dispatch_pending:
            return
        run.dispatch_pending = True
        run.in_queue.put_nowait(TryDispatch())

    def _leave_queue(self, run: Run) -> None:
        """Takes `run` out of its conversation's queue and nudges whoever is now at the head."""
        queue = self._pending_by_thread.get(run.thread_id)
        if queue is None or run.run_id not in queue:
            return
        queue.remove(run.run_id)
        if queue:
            self._nudge(queue[0])
        else:
            self._pending_by_thread.pop(run.thread_id, None)

    async def _try_dispatch(self, run: Run) -> None:
        """The run's own answer to "can I be handed over now?" — and, if yes, the handing over."""
        if run.claimed_by is not None or run.offered_to is not None:
            return
        queue = self._pending_by_thread.get(run.thread_id)
        if not queue or queue[0] != run.run_id:
            return
        provider = self._live.serving(run.agent)
        if provider is None:
            return
        if not self._take_place(run, provider):
            return

        try:
            delivered = DeliveredRun(
                run_id=run.run_id,
                agent_name=run.agent.name,
                run_input=RunAgentInput.model_validate(run.input_json),
                thread_id=run.thread_id,
            )
        except ValidationError as e:
            self._release(run)
            run.in_queue.put_nowait(Fail(f"input does not validate as RunAgentInput: {e}"))
            return

        await self._record(run, Offer())
        try:
            async with asyncio.timeout(self.deliver_timeout_seconds):
                accepted = await provider.deliver(delivered)
        except TimeoutError:
            await self._hand_back(run)
            self._note_abnormal(provider.public_key, "unanswered")
            logger.warning(
                "provider %s did not answer an offer of run %s within %ss (%d so far)",
                provider.public_key[:16],
                run.run_id,
                self.deliver_timeout_seconds,
                self._live.count(provider.public_key, "unanswered"),
            )
            return
        except Exception:
            await self._hand_back(run)
            self._note_abnormal(provider.public_key, "unanswered")
            logger.exception("run %s: delivering to its provider failed", run.run_id)
            return

        reason = getattr(accepted, "reason", None)
        if isinstance(reason, str):
            logger.warning(
                "provider %s permanently refused run %s: %s",
                provider.public_key[:16],
                run.run_id,
                reason,
            )
            # Into its own queue like any other verdict: this lane reads it next and ends the run, and the place goes back with `forget`.
            run.in_queue.put_nowait(Fail(reason))
            return
        if not accepted:
            await self._hand_back(run)
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
            return

        self._take_claim(run, provider)
        await self._record(run, Claim())

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

    def _take_claim(self, run: Run, provider: ConnectedProvider) -> None:
        """Records that `provider` accepted `run`: it is no longer waiting to be handed over, so it leaves its conversation's queue and the next utterance gets its turn."""
        run.claimed_by = provider.public_key
        run.claimed_at = datetime.now(timezone.utc)
        run.cancel_notify = provider.cancel
        self._leave_queue(run)

    async def _hand_back(self, run: Run) -> None:
        """Undoes a hand-over nobody accepted: gives the place back and puts the record where the run actually is."""
        self._release(run)
        await self._record(run, Requeue())

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

    def _spawn_unsupervised(self, coro, *, name: str | None = None) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._lane_tasks.add(task)
        task.add_done_callback(self._lane_tasks.discard)
        return task

    def get(self, run_id: str) -> RunSnapshot | None:
        run = self._runs.get(run_id)
        return _snapshot(run) if run is not None else None

    def push(self, run_id: str, command: Command) -> bool:
        """Enqueues `command` on a run's own lane."""
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
        """Returns an async iterator of whatever is pushed to `run_id`'s out_queue, ending when its lane finishes; an empty iterator if `run_id` is unknown."""
        run = self._runs.get(run_id)
        return _drain_run(run) if run is not None else _no_events()

    def request_cancel(self, run_id: str) -> bool:
        """Marks the run cancel-requested and puts the request in its own lane."""
        run = self._runs.get(run_id)
        if run is None:
            return False
        run.cancel_requested = True
        run.in_queue.put_nowait(RequestCancel())
        return True

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
        """Gives up on queued (unclaimed) runs whose agent has had no serving provider for longer than `timeout_seconds`, failing each with `Fail("no_provider_took_it")`, and returns their run_ids."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        expired: list[str] = []
        for queue in list(self._pending_by_thread.values()):
            for run_id in list(queue):
                run = self._runs.get(run_id)
                if run is None:
                    continue
                # Read off the run rather than the queue's key: the clock this gives up on is the agent's, and the queue is now the thread's.
                if self._live.serving(run.agent) is not None:
                    continue
                unserved_since = self._unserved_since.get(run.agent)
                reference = (
                    max(run.queued_at, unserved_since) if unserved_since else run.queued_at
                )
                if reference > cutoff:
                    continue
                expired.append(run_id)
                run.in_queue.put_nowait(Fail("no_provider_took_it"))
        return expired

    def active_run_ids(self) -> list[str]:
        return list(self._runs)

    def accept_late_ack(self, run_id: str, claimed_by: str) -> bool:
        """Lets a provider claim a run after funduq already gave up waiting for its answer (e.g."""
        run = self._runs.get(run_id)
        if run is None or run.claimed_by is not None or run.offered_to is not None:
            return False
        provider = self._live.serving(run.agent)
        if provider is None or provider.public_key != claimed_by:
            return False
        if not self._take_place(run, provider):
            return False
        self._note_abnormal(claimed_by, "answered_late")
        logger.warning(
            "provider %s answered late for run %s (%d so far): already producing for "
            "a run funduq had put back in the queue",
            claimed_by[:16],
            run_id,
            self._live.count(claimed_by, "answered_late"),
        )
        self._take_claim(run, provider)
        # Into the lane rather than applied here: the lane is idle and this is the next thing that happened to the run.
        run.in_queue.put_nowait(Claim())
        return True

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
                        "answered_late",
                    )
                },
            )
            for key, c in self._capacity.items()
        }

    def forget(self, run_id: str) -> None:
        """Drops a run's tracked state and handlers, takes it out of its conversation's queue (nudging whoever is now at the head), and gives back the place it was holding — nudging every waiting conversation, because a freed place is news."""
        run = self._runs.pop(run_id, None)
        self._handlers.pop(run_id, None)
        if run is not None:
            self._leave_queue(run)
            if run.offered_to is not None:
                self._release(run)
                self._work_to_do.set()
                self._nudge_waiting()
        for listener in self._forget_listeners:
            listener(run_id)
