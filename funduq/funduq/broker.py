from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol

from funduq.live_roster import LiveRoster
from funduq.models import AgentRef, ClaimedRun

logger = logging.getLogger("funduq.broker")

END_OF_STREAM = object()


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


Command = Offer | Requeue | Claim | RelayEvent | FinishStream | RequestCancel | Fail


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
    decline handling in `_offer`: the contradiction withdraws the provider
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
    feed its `_pipeline` task. Distinct from `ClaimedRun`, the read-only value
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
    claimed_by: str | None = None
    claimed_at: datetime | None = None
    pipeline_started: bool = False
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
    (put there when the run's pipeline finishes), then returns."""
    while True:
        item = await run.out_queue.get()
        if item is END_OF_STREAM:
            return
        yield item


async def _no_events() -> AsyncIterator[Any]:
    """An empty async iterator, returned by `subscribe` for an unknown run_id."""
    return
    yield  # pragma: no cover - what makes this an async generator


def _put_first(queue: "asyncio.Queue[Command]", command: Command) -> None:
    """Puts `command` ahead of whatever is already waiting in `queue`.

    The dispatch window is the reason this exists. A cancel that arrives
    while an offer is unanswered lands in the run's queue before funduq
    knows the run was claimed; processing it in arrival order would ask a
    provider to stop a run funduq had not yet recorded as running, and the
    status write would be refused as an illegal transition. The claim is the
    older fact — it is what the provider was answering — so it goes first
    and the cancel follows it. Safe to do without a lock because it does not
    await: nothing else can touch the queue in between.
    """
    waiting = []
    while not queue.empty():
        waiting.append(queue.get_nowait())
    queue.put_nowait(command)
    for item in waiting:
        queue.put_nowait(item)


# What a provider's answer to an offer comes back as. Three values because a
# provider has three honest things to say, and collapsing any two of them has
# cost a defect each time (see docs/mechanisms/requests.md).
_Outcome = Literal["accepted", "declined", "refused"]

HandlerMap = dict[type, Callable[[Run, Any], Awaitable[None]]]

async def _pipeline(run: Run, handlers: HandlerMap, owner: "RunBroker") -> None:
    """Drains `run.in_queue`, dispatching each command to its registered handler
    in order. Stops after a `FinishStream` or `Fail`, or after a `RequestCancel`
    for a run nobody has claimed; a `RequestCancel` for a claimed run is handled
    but the pipeline keeps running, waiting for the eventual terminal command.
    On exit it signals END_OF_STREAM on `run.out_queue` and calls `owner.forget`."""
    while True:
        cmd = await run.in_queue.get()
        handler = handlers.get(type(cmd))
        try:
            if handler is not None:
                await handler(run, cmd)
            else:
                logger.warning("run %s: no handler registered for %s", run.run_id, type(cmd).__name__)
        except Exception:
            logger.exception("run %s: error handling %s", run.run_id, type(cmd).__name__)
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
        self._pending_by_agent: dict[AgentRef, deque[str]] = defaultdict(deque)
        self._live = LiveRoster(
            ("misdeclared", "abandoned", "undelivered", "unanswered", "answered_late")
        )
        self._unserved_since: dict[AgentRef, datetime] = {}
        self._capacity: dict[str, _Capacity] = {}
        self._handlers: dict[str, HandlerMap] = {}
        self._draining: dict[AgentRef, asyncio.Task] = {}
        self._pipeline_tasks: set[asyncio.Task] = set()
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
        """Starts the sweep loop if it isn't already running. Recreates the
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
        """Repeatedly notes providers that have not delivered what they accepted, gives up on
        queued runs whose agent has gone unserved for too long, and makes sure every agent with
        pending runs has a lane draining it — sleeping until new work arrives (`enqueue_run`,
        `register_provider`) or the shortest window it observes elapses. Swallows and logs any exception other than
        cancellation so one bad sweep doesn't stop future ones.

        **This loop never waits for a provider's answer.** It starts lanes and
        goes back to sleep; the waiting happens in `_drain_agent`, one lane per
        agent. It used to offer inline, and one provider slow to answer then
        held up the handover of every other agent, provider and caller —
        measured at 3.1s for a trivial run that shared nothing with the one
        ahead of it but this loop (funduq#164).
        """
        while True:
            try:
                self.note_undelivered(self.undelivered_window_seconds)
                self.expire_queued(self.unserved_timeout_seconds)
                self._work_to_do.clear()
                for agent in list(self._pending_by_agent):
                    self._start_draining(agent)
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
        handlers: HandlerMap | None = None,
        seq: int = 0,
    ) -> Run:
        """Queues a new run for `agent` and wakes the sweep loop to offer it.
        Raises `RuntimeError` if the broker hasn't been `start()`-ed, since
        nothing would ever pick the run up."""
        if not self.is_running:
            raise RuntimeError(
                f"run {run_id}: this broker is not running, so nothing would ever be "
                "dispatched — call Funduq.start() (or RunBroker.start()) first"
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
        self._pending_by_agent[agent].append(run_id)
        self._work_to_do.set()
        if handlers is not None:
            self._handlers[run_id] = handlers
        return run


    def register_provider(self, mapping: dict[AgentRef, ConnectedProvider]) -> None:
        """Registers (or replaces) the provider serving each given agent and
        wakes the sweep loop. A provider re-registering under a key it already
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

    def serving(self, agent: AgentRef) -> ConnectedProvider | None:
        return self._live.serving(agent)

    def agents_served_by(self, public_key: str) -> list[AgentRef]:
        return self._live.served_by(public_key)

    def unregister_provider(self, agents: list[AgentRef]) -> None:
        """Takes `agents` off the live roster and fails every run their provider was still
        holding.

        A claimed run belongs to whoever claimed it, and how long they hold
        it is theirs to decide — funduq does not pace a provider's work and
        does not read silence as death. What it does read is the one fact it
        owns: whether the party holding a run is still here. When they are
        not, nobody is going to finish it, and that is settled now rather
        than inferred from a clock later.

        `push`ing a `Fail` for a claimed run is also what records
        `abandoned` against that provider — took a run and never ended it —
        so the judgment about the provider and the verdict about the work
        come from the same observed fact.
        """
        now = datetime.now(timezone.utc)
        self._live.withdraw(agents)
        for agent in agents:
            if self._live.serving(agent) is not None:
                continue
            self._unserved_since[agent] = now
            for run in list(self._runs.values()):
                if run.agent == agent and run.claimed_by is not None:
                    logger.warning(
                        "provider %s left holding run %s; failing it",
                        run.claimed_by[:16],
                        run.run_id,
                    )
                    self.push(run.run_id, Fail("provider_left_holding_it"))

    def _start_draining(self, agent: AgentRef) -> None:
        """Ensures `agent`'s queue has a lane draining it. One lane per agent,
        because the queue is per agent: the head must be answered before its
        successor is offered (see `_drain_agent`), and that is the only thing
        that has to be serial."""
        existing = self._draining.get(agent)
        if existing is not None and not existing.done():
            return
        self._draining[agent] = self._spawn(
            self._drain_agent(agent), name=f"dispatch:{agent.provider_key[:8]}/{agent.name}"
        )

    async def _drain_agent(self, agent: AgentRef) -> None:
        """Offers `agent`'s queued runs, head first, to its provider until the
        queue is empty, the provider has no room, or an offer is not accepted.

        The queue's own FIFO order is the only sequencing funduq imposes: a
        thread's utterances are offered in arrival order, and a sibling is
        offered as soon as it reaches the head — whether the provider runs it,
        holds it, or absorbs it into a turn already in flight is the
        provider's decision, not funduq's (funduq never paces a provider's
        conversation; see the queueing design record).

        That order is why the lane is serial and why the wait for an answer
        lives here rather than in the sweep loop. A declined head must not be
        overtaken by its own sibling, and nothing knows the head is declined
        until the provider says so — so this lane blocks on the answer, and
        only this lane does. Every other agent is draining at the same time,
        in a lane of its own.

        Exits with no work left to do; the sweep loop starts it again when
        anything changes (`enqueue_run`, `register_provider`, a freed
        capacity slot in `forget`). It removes itself from `_draining` on the
        way out, with no await between its last look at the queue and that
        removal, so a run enqueued at any moment is either seen by this lane
        or seen by the next one.
        """
        try:
            while True:
                provider = self._live.serving(agent)
                queue = self._pending_by_agent.get(agent)
                if provider is None or not queue:
                    return
                run_id = queue[0]
                run = self._runs.get(run_id)
                if run is None or run.cancel_requested:
                    queue.remove(run_id)
                    continue
                capacity = self._capacity.get(provider.public_key)
                if capacity is not None and not capacity.has_room:
                    return
                queue.popleft()
                outcome = await self._offer(run, provider)
                if outcome == "declined":
                    if run.cancel_requested:
                        # A cancel arrived while the offer was out and nobody
                        # took the run; it is funduq's again, so it is settled
                        # here rather than put back in the queue.
                        if not self._start_pipeline(run):
                            self._spawn(
                                self._cancel_queued(run), name=f"cancel:{run_id}"
                            )
                        continue
                    queue.appendleft(run_id)
                    return
        finally:
            self._draining.pop(agent, None)

    def _reserve(self, run: Run, provider: ConnectedProvider) -> None:
        """Takes `run`'s place on `provider` as the offer leaves.

        The slot is spent at dispatch, not at acceptance. With handovers
        running in parallel lanes, a provider that is slow to answer would
        otherwise be sent more runs than it declared — every lane would read
        the same unchanged in-flight count and conclude there was room.
        """
        run.offered_to = provider.public_key
        capacity = self._capacity.get(provider.public_key)
        if capacity is not None:
            capacity.in_flight += 1

    def _release(self, run: Run) -> None:
        """Gives back the place `_reserve` took. Deliberately does not wake the
        sweep loop: a declined offer freeing its own slot would have the loop
        re-offer the same run immediately, over and over. `forget` does the
        waking, because a slot freed by a finished run is news."""
        key, run.offered_to = run.offered_to, None
        capacity = self._capacity.get(key) if key is not None else None
        if capacity is not None and capacity.in_flight > 0:
            capacity.in_flight -= 1

    def _start_pipeline(self, run: Run) -> bool:
        """Starts the run's own lane, once, and reports whether it has one.
        Everything after dispatch happens there, in the order the commands
        arrived. A run enqueued without a handler map never gets a lane —
        there would be nothing for it to do."""
        if run.pipeline_started:
            return True
        handlers = self._handlers.get(run.run_id)
        if handlers is None:
            return False
        run.pipeline_started = True
        self._spawn(_pipeline(run, handlers, self), name=f"pipeline:{run.run_id}")
        return True

    async def _apply(self, run: Run, command: Command) -> None:
        """Runs one command's handler directly, without a pipeline and without
        ending the run. Used for the two ends of the dispatch window (`Offer`,
        `Requeue`), which happen while the run has no lane of its own yet."""
        handler = (self._handlers.get(run.run_id) or {}).get(type(command))
        if handler is None:
            return
        try:
            await handler(run, command)
        except Exception:
            logger.exception(
                "run %s: recording %s failed", run.run_id, type(command).__name__
            )

    async def _offer(self, run: Run, provider: ConnectedProvider) -> _Outcome:
        """Delivers `run` to `provider` within `deliver_timeout_seconds` and
        reports what came back, in the provider's own three values.

        - **"accepted"** — the run is claimed and its lane is running.
        - **"declined"** — nobody has it; a timeout, an exception and a
          "full right now" are all this, and each counts against the
          provider's quality counters (`unanswered` or `misdeclared`). The
          run's place and its recorded status are both handed back, and
          `_drain_agent` puts it at the head of the queue again.
        - **"refused"** — permanent. The run is failed with the provider's
          own reason recorded verbatim and never re-offered.

        The run is reserved on the provider and recorded "offering" before
        the offer leaves: for the length of this await the run is neither
        queued nor running, and both answers would be untrue to anyone
        reading the record."""
        capacity = self._capacity.get(provider.public_key)
        self._reserve(run, provider)
        await self._apply(run, Offer())
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
            return "declined"
        except Exception:
            await self._hand_back(run)
            self._note_abnormal(provider.public_key, "unanswered")
            logger.exception("run %s: delivering to its provider failed", run.run_id)
            return "declined"
        reason = getattr(accepted, "reason", None)
        if isinstance(reason, str):
            logger.warning(
                "provider %s permanently refused run %s: %s",
                provider.public_key[:16],
                run.run_id,
                reason,
            )
            # The reservation stands until the run is forgotten, which is what
            # _one_shot ends with — a refused run occupies its place for as
            # long as funduq is still settling it.
            self._spawn(self._one_shot(run, Fail(reason)), name=f"refused:{run.run_id}")
            return "refused"
        if not accepted:
            await self._hand_back(run)
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
            return "declined"
        run.claimed_by = provider.public_key
        run.claimed_at = datetime.now(timezone.utc)
        run.cancel_notify = provider.cancel
        self._start_pipeline(run)
        _put_first(run.in_queue, Claim())
        current = self._live.serving(run.agent)
        if current is None or current.public_key != provider.public_key:
            # The provider stopped serving this agent while its answer was in
            # flight. It believes it took the run, so this is the same fact
            # `unregister_provider` records for a run it was already holding:
            # took work, will never end it. Compared by key, not by object,
            # because a provider that merely re-attached is still the one that
            # accepted this run.
            logger.warning(
                "provider %s accepted run %s after it stopped serving %s; failing it",
                provider.public_key[:16],
                run.run_id,
                run.agent,
            )
            self.push(run.run_id, Fail("provider_left_holding_it"))
        return "accepted"

    async def _hand_back(self, run: Run) -> None:
        """Undoes a dispatch nobody accepted: gives the place back and puts the
        record where the run actually is."""
        self._release(run)
        await self._apply(run, Requeue())

    def _spawn_unsupervised(self, coro, *, name: str | None = None) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._pipeline_tasks.add(task)
        task.add_done_callback(self._pipeline_tasks.discard)
        return task

    def get(self, run_id: str) -> RunSnapshot | None:
        run = self._runs.get(run_id)
        return _snapshot(run) if run is not None else None

    def push(self, run_id: str, command: Command) -> bool:
        """Enqueues `command` on a claimed run's pipeline. Returns False if
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
        out_queue, ending when its pipeline finishes; an empty iterator if
        `run_id` is unknown."""
        run = self._runs.get(run_id)
        return _drain_run(run) if run is not None else _no_events()

    def request_cancel(self, run_id: str) -> bool:
        """Marks the run cancel-requested immediately, then either forwards a
        `RequestCancel` into the run's own lane (if it has been dispatched) or,
        if it is still sitting in the queue, runs the `RequestCancel` handler
        once directly so it still gets recorded and the run ends without ever
        being offered. Returns False if `run_id` is unknown.

        **Dispatched, not claimed, is the test.** A run whose offer is out has
        an owner already, even though no provider has answered for it yet. This
        used to read `claimed_by`, so a cancel arriving inside that window took
        the queued path: funduq recorded the run cancelled and handed it to the
        provider a moment later, which then worked on something nobody would
        collect and lost its capacity slot for good (funduq#164). Queued behind
        the pending answer, the same cancel is merely late rather than
        contradictory — if the provider took the run it is asked to stop, and
        if it did not the run ends here.
        """
        run = self._runs.get(run_id)
        if run is None:
            return False
        run.cancel_requested = True
        if run.offered_to is not None or run.claimed_by is not None:
            run.in_queue.put_nowait(RequestCancel())
            return True
        self._spawn(self._cancel_queued(run), name=f"cancel:{run_id}")
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
        for agent, queue in list(self._pending_by_agent.items()):
            if self._live.serving(agent) is not None:
                continue
            unserved_since = self._unserved_since.get(agent)
            for run_id in list(queue):
                run = self._runs.get(run_id)
                if run is None:
                    continue
                reference = (
                    max(run.queued_at, unserved_since) if unserved_since else run.queued_at
                )
                if reference > cutoff:
                    continue
                queue.remove(run_id)
                expired.append(run_id)
                self._spawn(
                    self._one_shot(run, Fail("no_provider_took_it")),
                    name=f"expire:{run_id}",
                )
        return expired

    async def _cancel_queued(self, run: Run) -> None:
        await self._one_shot(run, RequestCancel())

    async def _one_shot(self, run: Run, command: Command) -> None:
        """Runs a single command's handler directly (bypassing `_pipeline`) for
        a run that was never claimed, then ends the run the same way the
        pipeline would: signals END_OF_STREAM and forgets it. Used for expiring
        queued runs and for cancelling a run before any provider claimed it."""
        await self._apply(run, command)
        run.out_queue.put_nowait(END_OF_STREAM)
        self.forget(run.run_id)

    def active_run_ids(self) -> list[str]:
        return list(self._runs)

    def accept_late_ack(self, run_id: str, claimed_by: str) -> bool:
        """Lets a provider claim a run after funduq already gave up waiting for
        its answer (e.g. an unanswered offer timed out), as long as the run is
        not already dispatched — neither claimed nor out on a fresh offer — and
        `claimed_by` matches the provider currently registered for that agent.
        On success, removes the run from the pending queue if it's still
        sitting there, records an `answered_late` quality event, and starts
        its pipeline. Returns False (without changing anything) if the run is
        already dispatched or `claimed_by` doesn't match."""
        run = self._runs.get(run_id)
        if run is None or run.claimed_by is not None or run.offered_to is not None:
            return False
        provider = self._live.serving(run.agent)
        if provider is None or provider.public_key != claimed_by:
            return False

        queue = self._pending_by_agent.get(run.agent)
        if queue is not None and run_id in queue:
            queue.remove(run_id)

        self._reserve(run, provider)
        self._note_abnormal(claimed_by, "answered_late")
        logger.warning(
            "provider %s answered late for run %s (%d so far): already producing for "
            "a run funduq had put back in the queue",
            claimed_by[:16],
            run_id,
            self._live.count(claimed_by, "answered_late"),
        )
        run.claimed_by = claimed_by
        run.claimed_at = datetime.now(timezone.utc)
        run.cancel_notify = provider.cancel
        self._start_pipeline(run)
        _put_first(run.in_queue, Claim())
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
        """Drops a run's tracked state and handlers, gives back the place it
        was holding on its provider (if any, waking the sweep loop so the
        freed place can be offered again), and notifies forget listeners.
        Safe to call for a run that isn't tracked."""
        run = self._runs.pop(run_id, None)
        self._handlers.pop(run_id, None)
        if run is not None and run.offered_to is not None:
            self._release(run)
            self._work_to_do.set()
        for listener in self._forget_listeners:
            listener(run_id)

