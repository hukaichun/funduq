from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from funduq_contract import DeliveredRun, Refusal

from funduq_provider_sdk.identity import ProviderIdentity
from funduq_provider_sdk.provider import Provider

if TYPE_CHECKING:
    from funduq_provider_sdk.link import FunduqLink

logger = logging.getLogger("funduq_provider_sdk.runtime")


def _addressed_run_id(run: DeliveredRun) -> str | None:
    """The run this one declared it wants to join, read off the caller's forwarded props."""
    props = run.run_input.forwarded_props
    if isinstance(props, dict):
        value = props.get("addressedRunId")
        return value if isinstance(value, str) else None
    return None


@dataclass
class _Lane:
    """One thread's turn-taking: a queue of accepted runs and the one active now."""

    queue: deque[DeliveredRun] = field(default_factory=deque)
    active_run_id: str | None = None


class ProviderRuntime:
    """Runs a `Provider`'s agents locally, one active run per thread by construction: accepted runs queue on their thread's lane, execute one at a time, and stream events back through `link`. An interjection — a run addressed to the lane's active run — goes to the provider's `interject_stream` hook instead, or is refused if the provider has none."""

    def __init__(
        self,
        identity: ProviderIdentity,
        provider: Provider,
        *,
        max_queued_runs: int = 1,
        max_concurrent_runs: int | None = None,
    ) -> None:
        self.identity = identity
        self.provider = provider
        self.link: "FunduqLink | None" = None
        # Claiming no limit (max_concurrent_runs=None, the default) is a declaration funduq takes at its word: a decline from an unlimited provider is abnormal behaviour, counted against it.
        self.max_concurrent_runs = max_concurrent_runs
        self.max_queued_runs = max_queued_runs
        self._output: asyncio.Queue = asyncio.Queue()
        self._lanes: dict[str, _Lane] = {}
        self._in_flight: dict[str, asyncio.Task] = {}
        self._queued: dict[str, _Lane] = {}
        self._dropped: set[str] = set()
        self._tasks: set[asyncio.Task] = set()
        self._running = False

    @property
    def public_key(self) -> str:
        return self.identity.public_key

    async def deliver(self, run: DeliveredRun) -> bool | Refusal:
        """The intake decision, answered from state already held — never gated on running anything."""
        if not self._running:
            return False
        key = run.thread_id or run.run_id
        lane = self._lanes.get(key)
        addressed = _addressed_run_id(run)
        if addressed is not None and lane is not None and lane.active_run_id == addressed:
            hook = getattr(self.provider, "interject_stream", None)
            if hook is None:
                return Refusal(
                    reason=f"agent '{run.agent_name}' takes no interjections"
                )
            if not self._has_room():
                return False
            self._start_run(
                run, stream=hook(run.agent_name, run.run_input, addressed), lane_key=None
            )
            return True
        if not self._has_room():
            return False
        if lane is None:
            lane = _Lane()
            self._lanes[key] = lane
            lane.queue.append(run)
            self._queued[run.run_id] = lane
            self._lane_next(key)
        else:
            lane.queue.append(run)
            self._queued[run.run_id] = lane
        return True

    def _has_room(self) -> bool:
        if self.max_concurrent_runs is None:
            return True
        if len(self._in_flight) < self.max_concurrent_runs:
            return True
        return len(self._queued) < self.max_queued_runs

    def cancel(self, run_id: str) -> None:
        """Stop the run if it is executing; a run still queued on its lane is dropped and finished at once."""
        task = self._in_flight.get(run_id)
        if task is not None:
            task.cancel()
            return
        lane = self._queued.pop(run_id, None)
        if lane is not None:
            self._dropped.add(run_id)
            self._output.put_nowait((run_id, _END))

    def start(self) -> None:
        """Starts the output-reporting loop; a no-op if already running."""
        if self._running:
            return
        self._running = True
        self._spawn(self._report_output(), name="provider-output")

    async def aclose(self, *, cancel_in_flight: bool = False) -> None:
        """Stops the runtime, optionally cancelling in-flight runs, and awaits its background tasks to finish."""
        self._running = False
        if cancel_in_flight:
            for task in list(self._in_flight.values()):
                task.cancel()
        for task in list(self._tasks):
            if task.get_name() == "provider-output":
                task.cancel()
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _spawn(self, coro, *, name: str) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def _lane_next(self, key: str) -> None:
        """Advance one lane: start its next queued run, or retire the lane when nothing waits. Every transition here is synchronous, so the one-active-run invariant holds by construction rather than by timing."""
        lane = self._lanes.get(key)
        if lane is None:
            return
        while lane.queue:
            run = lane.queue.popleft()
            self._queued.pop(run.run_id, None)
            if run.run_id in self._dropped:
                self._dropped.discard(run.run_id)
                continue
            lane.active_run_id = run.run_id
            self._start_run(run, stream=None, lane_key=key)
            return
        self._lanes.pop(key, None)

    def _start_run(self, run: DeliveredRun, *, stream, lane_key: str | None) -> None:
        task = self._spawn(self._execute(run, stream), name=f"run:{run.run_id}")
        self._in_flight[run.run_id] = task

        def _done(_task, run_id=run.run_id, key=lane_key) -> None:
            self._in_flight.pop(run_id, None)
            if key is None:
                return
            lane = self._lanes.get(key)
            if lane is not None and lane.active_run_id == run_id:
                lane.active_run_id = None
                self._lane_next(key)

        task.add_done_callback(_done)

    async def _execute(self, run: DeliveredRun, stream) -> None:
        """Streams the run's events into the output queue, always enqueuing a terminal marker (triggering `finish_run`) even on cancellation or an unhandled exception."""
        if stream is None:
            stream = self.provider.run_stream(run.agent_name, run.run_input)
        try:
            async for event in stream:
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
            try:
                if self.link is None:
                    continue
                if event is _END:
                    await self.link.finish_run(run_id)
                else:
                    await self.link.report_event(run_id, event)
            except Exception:
                logger.exception("run %s: reporting failed", run_id)


_END = object()
