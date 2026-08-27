from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import TYPE_CHECKING, Any

from funduq_provider_sdk.identity import ProviderIdentity
from funduq_provider_sdk.provider import DeliveredRun, Provider

if TYPE_CHECKING:
    from funduq_provider_sdk.link import FunduqLink

logger = logging.getLogger("funduq_provider_sdk.runtime")


class ProviderRuntime:
    """Runs a `Provider`'s agents locally: queues delivered runs, executes each as a task, and streams
    resulting events back through `link` (dropping them if no link is attached)."""

    def __init__(
        self,
        identity: ProviderIdentity,
        provider: Provider,
        *,
        max_queued_runs: int = 1,
        max_concurrent_runs: int | None = None,
        max_buffered_events: int = 1024,
    ) -> None:
        self.identity = identity
        self.provider = provider
        self.link: "FunduqLink | None" = None
        # Claiming no limit (max_concurrent_runs=None, the default) is a
        # declaration funduq takes at its word: a decline from an unlimited
        # provider is abnormal behaviour, counted against it, and stops
        # offers until it acts. So an unlimited runtime must never decline
        # by accident — its intake queue is unbounded, and pacing (if the
        # author wants any) is declared via max_concurrent_runs instead.
        self._jobs: asyncio.Queue = asyncio.Queue(
            maxsize=max_queued_runs if max_concurrent_runs is not None else 0
        )
        self._output: asyncio.Queue = asyncio.Queue()
        # What has been produced for each run, whether or not a link was there
        # to take it. **This used to be a `continue`**: an event produced while
        # no link was attached was taken off the queue and dropped, so a
        # provider that reconnected mid-run resumed a stream with a hole in
        # it — which is not resuming, it is delivering something broken.
        #
        # Bounded, because an unbounded buffer is a way to run out of memory
        # rather than a way to be correct. It only has to cover the window in
        # which a resume is possible at all, which is funduq's own provider
        # grace; a gap wider than the buffer abandons the run loudly instead
        # of resuming it with a hole (see `resume`).
        self._outbox: dict[str, deque[tuple[int, Any]]] = {}
        self._seq: dict[str, int] = {}
        self._sent_upto: dict[str, int] = {}
        self._stalled: set[str] = set()
        self.max_buffered_events = max_buffered_events
        self.max_concurrent_runs = max_concurrent_runs
        self._in_flight: dict[str, asyncio.Task] = {}
        self._tasks: set[asyncio.Task] = set()
        self._running = False

    @property
    def public_key(self) -> str:
        return self.identity.public_key


    async def deliver(self, run: DeliveredRun) -> bool:
        """Queues `run` for execution; returns False (without queuing) if not started, at `max_concurrent_runs`, or the queue is full.

        Every accepted run goes to the agent callable as it arrives — the
        runtime imposes no ordering of its own. A run whose
        `forwardedProps.addressedRunId` names another run is a declared
        *interjection*: the caller asks to join that run's turn in flight
        (distinct from `parentRunId`, which is plain continuation). Whether
        and how to honour it — absorb it into the named turn, treat it as
        the next turn, ignore it — is the agent author's decision, made in
        the agent's own code against its own live loop.
        `serialize_per_thread` is an off-the-shelf wrapper for authors who
        want one-turn-at-a-time per thread.
        """
        if not self._running:
            return False
        if self.max_concurrent_runs is not None and len(self._in_flight) >= self.max_concurrent_runs:
            return False
        try:
            self._jobs.put_nowait(run)
        except asyncio.QueueFull:
            return False
        return True

    def cancel(self, run_id: str) -> None:
        """Cancels the asyncio task executing `run_id`, if it is currently in flight; a no-op otherwise."""
        task = self._in_flight.get(run_id)
        if task is not None:
            task.cancel()


    def start(self) -> None:
        """Starts the background job-consuming and output-reporting loops; a no-op if already running."""
        if self._running:
            return
        self._running = True
        self._spawn(self._run_jobs(), name="provider-jobs")
        self._spawn(self._report_output(), name="provider-output")

    async def aclose(self, *, cancel_in_flight: bool = False) -> None:
        """Stops the runtime, optionally cancelling in-flight runs, and awaits its background tasks to finish."""
        self._running = False
        if cancel_in_flight:
            for task in list(self._in_flight.values()):
                task.cancel()
        for task in list(self._tasks):
            if task.get_name() in ("provider-jobs", "provider-output"):
                task.cancel()
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _spawn(self, coro, *, name: str) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task


    async def _run_jobs(self) -> None:
        while True:
            run = await self._jobs.get()
            task = self._spawn(self._execute(run), name=f"run:{run.run_id}")
            self._in_flight[run.run_id] = task
            task.add_done_callback(
                lambda _t, run_id=run.run_id: self._in_flight.pop(run_id, None)
            )

    async def _execute(self, run: DeliveredRun) -> None:
        """Streams the provider's events for `run` into the output queue, always enqueuing a terminal marker
        (triggering `finish_run`) even on cancellation or an unhandled exception."""
        name = run.agent_name
        try:
            async for event in self.provider.run_stream(name, run.run_input):
                self._output.put_nowait((run.run_id, event))
        except asyncio.CancelledError:
            logger.info("run %s: agent stopped", run.run_id)
            raise
        except Exception:
            logger.exception("run %s: agent failed", run.run_id)
        finally:
            self._output.put_nowait((run.run_id, _END))

    async def _report_output(self) -> None:
        while True:
            run_id, event = await self._output.get()
            seq = self._seq.get(run_id, 0) + 1
            self._seq[run_id] = seq
            outbox = self._outbox.setdefault(run_id, deque(maxlen=self.max_buffered_events))
            outbox.append((seq, event))
            await self._flush(run_id)

    async def _flush(self, run_id: str) -> None:
        """Hand over everything this run has produced and not yet handed over.

        A failure here leaves the buffer alone on purpose: the whole point of
        holding it is that a link which broke mid-send can be picked up, and
        dropping what it did not manage to carry would make the buffer
        decorative.
        """
        link = self.link
        if link is None:
            return
        outbox = self._outbox.get(run_id)
        if not outbox:
            return
        for seq, event in list(outbox):
            if seq <= self._sent_upto.get(run_id, 0):
                continue
            try:
                if event is _END:
                    await link.finish_run(run_id)
                else:
                    await link.report_event(run_id, event, seq=seq)
            except Exception:
                # Once per outage, not once per event. A link that has gone
                # away fails every buffered event in turn, and a traceback for
                # each of them buries the one line that matters under a
                # hundred copies of itself.
                if run_id not in self._stalled:
                    self._stalled.add(run_id)
                    logger.warning(
                        "run %s: cannot hand over from seq %s; holding %d event(s) "
                        "until a link is back",
                        run_id,
                        seq,
                        len(outbox),
                        exc_info=True,
                    )
                return
            self._sent_upto[run_id] = seq
            self._stalled.discard(run_id)

    def resuming(self) -> list[str]:
        """The runs this provider still holds output for — what a re-opened
        link asks funduq about."""
        return sorted(self._outbox)

    async def resume(self, watermarks: dict[str, int], unknown: list[str]) -> list[str]:
        """Pick up where the last link left off; returns the runs that could not be.

        `watermarks` is the last sequence funduq accepted per run: anything at
        or below it is already there and is dropped, everything above it goes
        again. `unknown` names runs funduq is no longer holding — settled while
        this provider was away — so producing for them is wasted and their
        buffers go.

        **A gap wider than the buffer is not resumed.** If the events funduq is
        missing have already fallen out of it, replaying what is left would
        hand the caller a stream with a hole in the middle, which is worse than
        the failure this is trying to avoid. Those runs are abandoned instead:
        this provider stops producing, funduq's grace runs out, and it records
        the `provider_left_holding_it` it actually observed.
        """
        for run_id in unknown:
            self.cancel(run_id)
            self._forget(run_id)
        lost: list[str] = []
        for run_id, watermark in watermarks.items():
            outbox = self._outbox.get(run_id)
            if outbox is None:
                continue
            held_from = outbox[0][0] if outbox else watermark + 1
            if held_from > watermark + 1:
                logger.error(
                    "run %s: funduq has up to seq %s and this provider no longer holds "
                    "seq %s — the buffer (max_buffered_events=%s) did not cover the "
                    "outage, so the run is abandoned rather than resumed with a hole",
                    run_id,
                    watermark,
                    watermark + 1,
                    self.max_buffered_events,
                )
                lost.append(run_id)
                self.cancel(run_id)
                self._forget(run_id)
                continue
            self._sent_upto[run_id] = watermark
            await self._flush(run_id)
        return lost

    def _forget(self, run_id: str) -> None:
        self._stalled.discard(run_id)
        self._outbox.pop(run_id, None)
        self._seq.pop(run_id, None)
        self._sent_upto.pop(run_id, None)


_END = object()
