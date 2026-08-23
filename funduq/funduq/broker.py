from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from funduq.live_roster import LiveRoster
from funduq.models import AgentRef, ClaimedRun

logger = logging.getLogger("funduq.broker")

END_OF_STREAM = object()


@dataclass
class TryDispatch:
    """Something changed that might let this run be handed over: it was just
    queued, the utterance ahead of it left, a place freed, a provider
    attached. The run's own lane decides whether any of that is true for it —
    nobody decides on its behalf and then acts."""
    pass


@dataclass
class ProviderGone:
    """The named provider stopped serving. Whether that means anything for
    this run is the run's own lane to say, reading its state in order: it may
    have been claimed by that provider a moment ago, or handed back a moment
    before that."""

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
    """Per-provider counters of protocol violations observed while dispatching:
    declining an offer after claiming to have room (misdeclared), taking a run and never
    ending it (abandoned), taking one and not delivering it inside the window
    (undelivered), not answering an offer within the delivery timeout (unanswered), and
    acking after funduq gave up waiting (answered_late).

    `abandoned` and `undelivered` are the same shape of wrong seen with
    different certainty, which is why they are two counters and not one.
    Abandonment is **certain**: the provider stopped serving while still
    holding the run, so it will never be delivered. Non-delivery is
    **observed**: the window elapsed and nothing came back, and the
    provider may yet deliver. Merged, a reader could not tell a provider
    that dropped three times from one that was slow three times.

    Each run contributes at most one count, whichever funduq observed
    first.
    """

    in_flight: int
    declared: int | None
    misdeclared: int
    abandoned: int
    undelivered: int
    unanswered: int
    answered_late: int


@dataclass
class _Capacity:
    """Tracks one provider's in-flight run count against its declared limit.
    `declared=None` means the provider accepts unlimited concurrent runs —
    a declaration like any other, and one a decline contradicts (see the
    decline handling in `_try_dispatch`: the contradiction withdraws the provider
    from service)."""

    declared: int | None
    in_flight: int = 0

    @property
    def has_room(self) -> bool:
        return self.declared is None or self.in_flight < self.declared


class Refusal(Protocol):
    """A permanent decline of an offer, read duck-typed off `deliver`'s return: any object with a `reason` string.

    The attribute name is the contract with `funduq_provider_sdk.provider.Refusal`,
    which builds these on the provider side — neither package imports the other.
    """

    reason: str


class ConnectedProvider(Protocol):

    public_key: str
    max_concurrent_runs: int | None

    async def deliver(self, run: ClaimedRun) -> bool | Refusal:
        ...

    def cancel(self, run_id: str) -> None:
        ...


@dataclass
class Run:
    """A broker-side run's mutable dispatch state: its position in the pending
    queue, which provider (if any) has claimed it, and the in/out queues that
    feed its own lane. Distinct from `ClaimedRun`, the read-only value
    handed to a provider's `deliver`."""

    run_id: str
    agent: AgentRef
    thread_id: str
    input_json: dict[str, Any]
    protocol: str
    queued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    seq: int = 0
    round_starting_seq: int = 0
    pause_payload: dict[str, Any] | None = None
    # The provider this run is reserved on — set the moment the offer leaves,
    # cleared if it comes back unaccepted. Ownership is assigned at dispatch,
    # not at acceptance, which is what makes the capacity slot and the cancel
    # path agree about who holds the run during the window in between.
    offered_to: str | None = None
    # Whether an unanswered "can I be handed over now?" is already in this
    # run's queue. Several things can change at once — a place freed, a
    # provider attached, a sweep tick — and each would otherwise put its own
    # copy of the same question in, and the lane would hand the run over once
    # per copy: two offers for one dispatchable moment, two counts against
    # the provider for one decline.
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
    """Yields items placed on `run.out_queue` until the END_OF_STREAM sentinel
    (put there when the run's lane finishes), then returns."""
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
    """A run's own lane, from the moment it is queued until it is forgotten.

    **`run.in_queue` is the only thing this ever waits on**, and that is the
    whole design. Everything that can happen to a run arrives there — a
    chance to be handed over, a cancel, an event from the provider, a
    provider leaving, a verdict from a sweep — so everything about one run
    happens in one order, decided by the run itself. Nothing outside works
    out what a run's state means and then acts on it; it says what happened
    and this decides.

    The lane ends on a `FinishStream` or a `Fail`, and on a `RequestCancel`
    for a run no provider has taken — nobody is working on it, so there is
    nothing to ask and the cancel settles it. A cancel for a claimed run is
    relayed and the lane keeps going: funduq asks a provider to stop and does
    not decide the outcome on its behalf. On exit it signals END_OF_STREAM on
    `run.out_queue` and calls `owner.forget`.

    Two commands are answered here rather than recorded, because they are
    questions about this run's own state that only this lane can answer in
    order:

    - `TryDispatch` — is it my turn, is anyone serving, is there a place?
    - `ProviderGone` — was that *my* provider, as of now? The offer it is
      racing may have been accepted a moment ago or handed back a moment
      before that, and reading that state anywhere else means reading it at
      the wrong time.
    """
    while True:
        cmd = await run.in_queue.get()
        if isinstance(cmd, TryDispatch):
            run.dispatch_pending = False
            await owner._try_dispatch(run)
            continue
        if isinstance(cmd, ProviderGone):
            if run.claimed_by == cmd.public_key:
                # Took work and will never end it — the same fact, and the
                # same counter, as any other abandonment.
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
    """Matches queued runs to connected providers, one agent's pending runs at
    a time, respecting each provider's declared concurrency, and tracks
    per-provider quality-of-service counters (`ProviderQuality`). Must be
    `start()`-ed before `enqueue_run` will accept work; `start`/`stop` may be
    called across separate event loops as long as they don't overlap."""

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
        # Keyed by thread, because a thread is the pipe whose delivery order
        # funduq guarantees. An agent is not a pipe: two of its conversations
        # have no order between them, and making them share a queue only
        # made one wait for the other.
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
        """Records one abnormal event and applies the tolerance. The quality
        counters are the allowance: they say how much abnormality a provider
        is permitted, and a provider whose counter reaches the allowance is
        withdrawn from service — the same judgment for every event type, no
        provider getting a special seat. Queued runs are treated like
        anyone's (the agent is now unserved, so they travel the ordinary
        no-provider expiry road); runs in flight finish and report; the way
        back is the front door — reconnect and register again, the record
        intact and still counting."""
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
        """Starts the sweep if it isn't already running. Recreates the
        internal wakeup event each time, so a broker built outside a running
        event loop can still be started and stopped in successive loops."""
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
        """Runs the two clocks funduq keeps — noting providers that have not
        delivered what they accepted, and giving up on queued runs whose agent
        has gone unserved for too long — and nudges the head of every waiting
        conversation in case something it was blocked on has changed. Sleeps
        until new work arrives (`enqueue_run`, `register_provider`) or the
        shortest window it observes elapses. Swallows and logs any exception
        other than cancellation so one bad sweep doesn't stop future ones.

        **It dispatches nothing and settles nothing.** Both clocks say what
        they observed into the run's own lane and let the run decide; the
        nudge is a question, not an instruction. This loop used to hand runs
        over itself, one agent at a time, blocking on each provider's answer —
        which made one slow provider everyone's (funduq#164).
        """
        while True:
            try:
                self.note_undelivered(self.undelivered_window_seconds)
                self.expire_queued(self.unserved_timeout_seconds)
                self._work_to_do.clear()
                self._nudge_waiting()
                with contextlib.suppress(TimeoutError):
                    # Sleep no longer than the shortest window this loop is
                    # responsible for observing, or the observation misses it.
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
    ) -> Run:
        """Queues a new run for `agent`, gives it its own lane, and — if it is
        its conversation's turn — asks that lane to try handing it over.

        Two refusals, both because accepting would create a run nothing could
        ever finish. The broker must be `start()`-ed, or nothing runs the
        clocks. And **the agent must be served right now**: a run is only ever
        born with a provider online (the doors record `agent_offline` rather
        than queue one), and the lane is written to open by offering rather
        than by waiting for somebody to appear. A provider leaving afterwards
        is an ordinary thing that happens to a live run; never having had one
        is not.

        `handlers` is required. A run without one is a run whose lane could
        record nothing and whose end nobody would hear.
        """
        if not self.is_running:
            raise RuntimeError(
                f"run {run_id}: this broker is not running, so nothing would ever be "
                "dispatched — call Funduq.start() (or RunBroker.start()) first"
            )
        if self._live.serving(agent) is None:
            raise RuntimeError(
                f"run {run_id}: no provider is serving '{agent}', so nothing would ever "
                "be offered this run — a caller-facing door records agent_offline "
                "instead of queueing"
            )
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
        """Registers (or replaces) the provider serving each given agent and
        nudges every waiting conversation. A provider re-registering under a key it already
        has capacity tracking for keeps its existing in-flight count rather
        than resetting it."""
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
        """Takes `agents` off the live roster and tells every run that was in
        their provider's hands.

        A claimed run belongs to whoever claimed it, and how long they hold
        it is theirs to decide — funduq does not pace a provider's work and
        does not read silence as death. What it does read is the one fact it
        owns: whether the party holding a run is still here. When they are
        not, nobody is going to finish it.

        **This says the fact and does not draw the conclusion.** Whether a
        given run was in that provider's hands is only answerable at the
        moment the run itself gets to the question: an offer racing this call
        may have been accepted a moment ago, or handed back a moment before
        that, and reading `claimed_by` from here reads it at the wrong time —
        which is how a provider used to end up holding a run nothing would
        ever finish. So every run that was offered to or claimed by that key
        is told `ProviderGone`, and its own lane decides in its own order.
        The lane's conclusion, for a run still claimed, is the `Fail` that
        also records `abandoned` — took work, never ended it.
        """
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
        """Asks the head of every waiting conversation to try handing itself
        over. A nudge, not an instruction: each lane decides whether anything
        it was blocked on has actually changed. Sent whenever something might
        have — a provider attached, a place freed, the utterance ahead left —
        and on each sweep, so a run that was declined gets another turn."""
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
        """Takes `run` out of its conversation's queue and nudges whoever is
        now at the head. Called when the run stops waiting to be handed over —
        because it was claimed, or because it ended. **The run's own lane is
        the only thing that mutates that queue**, which is why the queue can
        never hold something that is already gone."""
        queue = self._pending_by_thread.get(run.thread_id)
        if queue is None or run.run_id not in queue:
            return
        queue.remove(run.run_id)
        if queue:
            self._nudge(queue[0])
        else:
            self._pending_by_thread.pop(run.thread_id, None)

    async def _try_dispatch(self, run: Run) -> None:
        """The run's own answer to "can I be handed over now?" — and, if yes,
        the handing over.

        Four conditions, each a plain reading of state this lane owns or can
        see: it is not already dispatched, it is its conversation's turn, its
        agent is served, and its provider has a place. Any of them false means
        wait; whatever changes will nudge this lane again. Nothing is
        recorded and nothing is given up on here — a run with no provider
        waits for the sweep's own clock to say `no_provider_took_it`.

        The place is taken **before the offer leaves**, in the same breath as
        the check that there was one (`_take_place`, which does not await), so
        two lanes cannot both find the last place. And for the length of the
        answer the run is recorded `offering`: it is neither queued nor
        running, and both would be untrue to anyone reading the record.
        """
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

        await self._record(run, Offer())
        try:
            async with asyncio.timeout(self.deliver_timeout_seconds):
                accepted = await provider.deliver(
                    ClaimedRun(
                        run_id=run.run_id,
                        agent=run.agent,
                        thread_id=run.thread_id,
                        run_input=run.input_json,
                    )
                )
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
            # Into its own queue like any other verdict: this lane reads it
            # next and ends the run, and the place goes back with `forget`.
            run.in_queue.put_nowait(Fail(reason))
            return
        if not accepted:
            await self._hand_back(run)
            capacity = self._capacity.get(provider.public_key)
            if capacity is not None and capacity.has_room:
                # Declining while claiming room is one abnormal event,
                # whatever the declaration was — the tolerance in
                # _note_abnormal decides when it adds up to withdrawal, the
                # same judgment every provider gets (funduq#128). A declared
                # limit is additionally treated as reached, that being the
                # provider's own figure; an unlimited declaration has no
                # figure to fall back to, so the run is simply re-offered
                # and each further decline spends more of the allowance.
                self._note_abnormal(provider.public_key, "misdeclared")
                if capacity.declared is not None:
                    capacity.in_flight = capacity.declared
                    logger.warning(
                        "provider %s declined a run while funduq believed it had room "
                        "(now %d/%s in flight); treating it as full",
                        provider.public_key[:16],
                        capacity.in_flight,
                        capacity.declared,
                    )
            return

        self._take_claim(run, provider)
        await self._record(run, Claim())

    def _take_place(self, run: Run, provider: ConnectedProvider) -> bool:
        """Takes `run`'s place on `provider` if there is one, and says whether
        it got it.

        Checking and taking are one function on purpose, and it does not
        await: with every run handing itself over in its own lane, two lanes
        reading the same unchanged in-flight count would both find room that
        is not there. The place is spent when the offer *leaves*, not when it
        is accepted — a provider slow to answer would otherwise be sent more
        runs than it declared.
        """
        capacity = self._capacity.get(provider.public_key)
        if capacity is not None and not capacity.has_room:
            return False
        run.offered_to = provider.public_key
        if capacity is not None:
            capacity.in_flight += 1
        return True

    def _release(self, run: Run) -> None:
        """Gives back the place `_take_place` took. Deliberately does not nudge
        anyone: a declined offer freeing its own place would have the same run
        try again immediately, over and over. `forget` does the nudging,
        because a place freed by a finished run is news."""
        key, run.offered_to = run.offered_to, None
        capacity = self._capacity.get(key) if key is not None else None
        if capacity is not None and capacity.in_flight > 0:
            capacity.in_flight -= 1

    def _take_claim(self, run: Run, provider: ConnectedProvider) -> None:
        """Records that `provider` accepted `run`: it is no longer waiting to be
        handed over, so it leaves its conversation's queue and the next
        utterance gets its turn."""
        run.claimed_by = provider.public_key
        run.claimed_at = datetime.now(timezone.utc)
        run.cancel_notify = provider.cancel
        self._leave_queue(run)

    async def _hand_back(self, run: Run) -> None:
        """Undoes a hand-over nobody accepted: gives the place back and puts
        the record where the run actually is. The run stays in its
        conversation's queue throughout — it never left."""
        self._release(run)
        await self._record(run, Requeue())

    async def _record(self, run: Run, command: Command) -> None:
        """Runs one command's handler. **The only place a command about a run is
        acted on**, whichever owner is holding the run at the time: the
        dispatcher, while it still has the run and no lane exists (`Offer`,
        `Requeue`); the run's own lane, for the claim and everything the lane
        drains, whether it read them or reached them itself. One step
        function means one order, and the owner changes hands only where there
        is nothing in flight to reorder."""
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
        """Enqueues `command` on a run's own lane. Returns False if
        `run_id` is unknown. Pushing a `Fail` for a run its provider had
        claimed is recorded as an abandoned run in that provider's quality
        counters."""
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
        """Returns an async iterator of whatever is pushed to `run_id`'s
        out_queue, ending when its lane finishes; an empty iterator if
        `run_id` is unknown."""
        run = self._runs.get(run_id)
        return _drain_run(run) if run is not None else _no_events()

    def request_cancel(self, run_id: str) -> bool:
        """Marks the run cancel-requested and puts the request in its own lane.
        Returns False if `run_id` is unknown.

        **One path, whatever state the run is in.** The lane reads the cancel
        in order with everything else and answers it from the state it has
        reached by then: a run some provider took gets the request relayed and
        keeps going, because funduq asks and does not decide; a run nobody
        took ends here, because there is nobody to ask. This used to be three
        paths — claimed, still queued, and handed back after an offer nobody
        accepted — each deciding for the run from outside, and the one that
        applied depended on which instant the cancel arrived in.
        """
        run = self._runs.get(run_id)
        if run is None:
            return False
        run.cancel_requested = True
        run.in_queue.put_nowait(RequestCancel())
        return True

    def note_undelivered(self, window_seconds: float) -> list[str]:
        """Counts one `undelivered` against every provider still holding a run it accepted
        `window_seconds` ago and has not delivered, and returns those run ids.

        **Whether a provider is working is read from what it delivers, not
        from whether it started.** A `RUN_STARTED`, a stream of tokens, any
        amount of visible motion — none of that is delivery, and none of it
        clears this. The only thing that does is the run actually ending,
        which is also why nothing here reads an event's content: a run the
        broker still holds, claimed, is by construction one that has not
        reached a terminal state.

        Accepting is the declaration this judges. A provider that does not
        want the work has two honest answers already in the protocol —
        decline (full right now) or refuse (never) — and choosing *accepted*
        instead says it has taken it. Holding it a long time is that
        provider's own business; taking it and delivering nothing is not
        the same thing, and it is what this counts.

        The count is per run, once, and no run contributes twice: a run
        counted here is not counted again as `abandoned` if the provider
        later leaves still holding it. There is no exemption for a run
        whose completion funduq is itself relaying — a provider that
        accepted work it could not turn around said yes when it could have
        said no.
        """
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
        """Gives up on queued (unclaimed) runs whose agent has had no serving
        provider for longer than `timeout_seconds`, failing each with
        `Fail("no_provider_took_it")`, and returns their run_ids. A run whose
        agent *is* served stays queued indefinitely — a declining-but-attached
        provider is a full stall, not a lost one. (A provider that spends its
        whole abnormality allowance — see `_note_abnormal` — stops being
        attached: withdrawal makes its agents unserved and starts exactly
        this clock.) The clock is the later of the
        run's own enqueue and the moment the agent last lost its provider, so
        every run gets the full grace period even if its agent was already
        unserved when it arrived."""
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        expired: list[str] = []
        for queue in list(self._pending_by_thread.values()):
            for run_id in list(queue):
                run = self._runs.get(run_id)
                if run is None:
                    continue
                # Read off the run rather than the queue's key: the clock this
                # gives up on is the agent's, and the queue is now the thread's.
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
        """Lets a provider claim a run after funduq already gave up waiting for
        its answer (e.g. an unanswered offer timed out), as long as the run is
        not already dispatched — neither claimed nor out on a fresh offer — and
        `claimed_by` matches the provider currently registered for that agent.
        On success it takes a place and the claim — which is what leaves the
        conversation's queue — records an `answered_late` quality event, and
        tells the run's lane. Returns False (without changing anything) if the
        run is already dispatched, has no place to take, or `claimed_by`
        doesn't match."""
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
        # Into the lane rather than applied here: the lane is idle and this is
        # the next thing that happened to the run.
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
        """Drops a run's tracked state and handlers, takes it out of its
        conversation's queue (nudging whoever is now at the head), and gives
        back the place it was holding — nudging every waiting conversation,
        because a freed place is news. Notifies forget listeners. Safe to call
        for a run that isn't tracked."""
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
