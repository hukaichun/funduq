from __future__ import annotations

import contextlib
import logging
from functools import partial
from typing import TYPE_CHECKING

from ag_ui.core import Event, EventType, RunErrorEvent
from pydantic import TypeAdapter, ValidationError

from funduq import repo
from funduq.agui_reduce import reduce_events_to_messages
from funduq.broker import (
    Claim,
    Fail,
    FinishStream,
    HandlerMap,
    Offer,
    RelayEvent,
    Requeue,
    RequestCancel,
    Run,
)
from funduq.pause import interrupt_outcome_of, unanswered_tool_calls

if TYPE_CHECKING:
    from funduq.core import Funduq

logger = logging.getLogger("funduq.handlers")

_EVENT = TypeAdapter(Event)
_KNOWN_EVENT_TYPES = frozenset(member.value for member in EventType)


def run_error(message: str, *, code: str | None = None) -> dict:
    """A `RUN_ERROR` funduq itself authors, built from AG-UI's own model rather than typed out
    as a dict.

    `exclude_none=True` for the reason the relay uses it: a default dump
    injects `timestamp: null` and `rawEvent: null` into a caller's stream.
    With the flag the result is exactly the two or three keys funduq means
    to say, which is also what makes this a drop-in for the literals it
    replaced.
    """
    return RunErrorEvent(message=message, code=code).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )


async def _handle_offer(funduq: "Funduq", run: Run, cmd: Offer) -> None:
    """Mark the run "offering" as it is handed to a provider that has not answered yet.

    Neither "queued" nor "running" is true for the length of that wait —
    nobody has the run, and nobody has accepted it — and a caller reading the
    record during it has to be told something.
    """
    async with funduq.session() as session:
        await funduq.mark_run_status(session, run.run_id, "offering")


async def _handle_requeue(funduq: "Funduq", run: Run, cmd: Requeue) -> None:
    """Put a run back to "queued" after an offer it was dispatched on was declined,
    went unanswered, or failed.

    Not `mark_run_status`: that function never writes "queued" on purpose.
    The guard is the same conditional UPDATE, so a hand-back racing an answer
    that arrived just in time cannot undo the claim that won the row.
    """
    async with funduq.session() as session:
        await funduq.return_run_to_queue(session, run.run_id)


async def _handle_claim(funduq: "Funduq", run: Run, cmd: Claim) -> None:
    """Mark the run "running" once a provider has claimed it."""
    async with funduq.session() as session:
        await funduq.mark_run_status(session, run.run_id, "running")


async def _handle_relay(funduq: "Funduq", run: Run, cmd: RelayEvent) -> None:
    """Validate, persist, and forward a provider event; fail the run on invalid AG-UI.

    Three-way rule. An event whose `type` is one funduq's pinned AG-UI knows is
    validated strictly, and a validation failure drains the run's queue and
    pushes a `Fail` — as does an event with no `type` string at all: both are
    malformation, not version skew. An event whose `type` is a string funduq
    does not recognise is a newer AG-UI's event, and it is relayed untouched:
    funduq stores and forwards it and never branches on its content — whether to
    skip it is the caller's decision (AG-UI's fail-open rule), never the
    relay's. A `RUN_FINISHED` carrying an interrupt outcome records it as the
    run's pause payload; a `RUN_ERROR` is remembered so `_handle_finish`
    doesn't synthesize a second one.
    """
    event = cmd.event
    type_tag = event.get("type") if isinstance(event, dict) else None
    if not isinstance(type_tag, str) or type_tag in _KNOWN_EVENT_TYPES:
        try:
            _EVENT.validate_python(event)
        except ValidationError as e:
            logger.warning(
                "run %s: provider sent an event that is not valid AG-UI, ending the run: %s",
                run.run_id,
                e,
            )
            while not run.in_queue.empty():
                run.in_queue.get_nowait()
            funduq.broker.push(run.run_id, Fail("provider sent a malformed AG-UI event"))
            return
    if event.get("type") == EventType.RUN_FINISHED:
        run.saw_run_finished = True
        interrupts = interrupt_outcome_of(event)
        if interrupts is not None:
            run.pause_payload = {"interrupts": interrupts}
    elif event.get("type") == EventType.RUN_ERROR:
        run.saw_run_error = True
    run.seq += 1
    async with funduq.session() as session:
        await repo.append_run_event(session, run.run_id, run.seq, event)
        await repo.touch_run_activity(session, run.run_id)
        await session.commit()
    await run.out_queue.put(event)


async def _handle_finish(funduq: "Funduq", run: Run, cmd: FinishStream) -> None:
    """Settle the run's final status and, when it completed or paused, fold its events into thread messages.

    Status is "input-required" if the run paused, "completed" if it saw `RUN_FINISHED`,
    "cancelled" if a cancel was requested, else "failed". A run that ends failed without
    ever having reported its own `RUN_ERROR` gets one synthesized and appended.

    A run pauses two ways, and the provider's stream ends identically for both.
    An interrupt outcome is the provider saying so. An unanswered tool call is
    the provider *not* saying so — `RUN_FINISHED` with `outcome: success`, a
    call announced and never resulted (see `unanswered_tool_calls`). Both are
    the same event, and the second is why a run's end cannot be read off
    `RUN_FINISHED` alone: the provider's **stream** ended, which is all it
    ever claimed. Whether the **run** ended is funduq's to settle, because
    funduq is what holds the run's identity across a gap the provider's stream
    cannot span — the same reason `resume_run` keeps the run id.
    """
    async with funduq.session() as session:
        round_events = await repo.get_run_events(
            session, run.run_id, since_seq=run.round_starting_seq
        )
        pending_tool_calls = unanswered_tool_calls(round_events)

        if run.pause_payload is not None or (run.saw_run_finished and pending_tool_calls):
            status = "input-required"
            metadata = {
                "interrupts": (run.pause_payload or {}).get("interrupts", []),
                "pendingToolCalls": pending_tool_calls,
            }
        elif run.saw_run_finished:
            status, metadata = "completed", None
        elif run.cancel_requested:
            status, metadata = "cancelled", None
        else:
            status, metadata = "failed", {"failureReason": "provider_stream_ended_without_finishing"}

        failure_event = (
            run_error("the agent's stream ended without finishing",
                      code="provider_stream_ended_without_finishing")
            if status == "failed" and not run.saw_run_error
            else None
        )

        settled = await funduq.mark_run_status(session, run.run_id, status, metadata=metadata)
        if settled and status in ("completed", "input-required"):
            reply_messages = reduce_events_to_messages(round_events)
            if reply_messages:
                await repo.append_thread_messages(session, run.thread_id, run.run_id, reply_messages)
        if failure_event is not None:
            run.seq += 1
            await repo.append_run_event(session, run.run_id, run.seq, failure_event)
        await session.commit()
    if failure_event is not None:
        await run.out_queue.put(failure_event)


async def _handle_cancel(funduq: "Funduq", run: Run, cmd: RequestCancel) -> None:
    """Cancel immediately if no provider has claimed the run yet; otherwise ask the provider to stop.

    A claimed run is marked "cancelling" (not "cancelled") and its `cancel_notify`
    callback is invoked — funduq asks the provider to stop, it does not decide the outcome
    on its behalf.
    """
    if run.claimed_by is None:
        async with funduq.session() as session:
            await funduq.mark_run_status(session, run.run_id, "cancelled")
        return

    async with funduq.session() as session:
        await funduq.mark_run_status(session, run.run_id, "cancelling")
    if run.cancel_notify is not None:
        with contextlib.suppress(Exception):
            run.cancel_notify(run.run_id)


async def _handle_fail(funduq: "Funduq", run: Run, cmd: Fail) -> None:
    """Append a `RUN_ERROR` event carrying `cmd.reason` and mark the run failed with that reason."""
    event = run_error(cmd.reason)
    run.seq += 1
    async with funduq.session() as session:
        await repo.append_run_event(session, run.run_id, run.seq, event)
        await funduq.mark_run_status(session, run.run_id, "failed", metadata={"failureReason": cmd.reason})
    await run.out_queue.put(event)


def make_handlers(funduq: "Funduq") -> HandlerMap:
    """Build the broker's command-type-to-handler map, bound to this `funduq` instance."""
    return {
        Offer: partial(_handle_offer, funduq),
        Requeue: partial(_handle_requeue, funduq),
        Claim: partial(_handle_claim, funduq),
        RelayEvent: partial(_handle_relay, funduq),
        FinishStream: partial(_handle_finish, funduq),
        RequestCancel: partial(_handle_cancel, funduq),
        Fail: partial(_handle_fail, funduq),
    }


async def close_with_terminal_event(funduq: "Funduq", run_id: str, failure_reason: str) -> None:
    """Give a run funduq has just failed its terminal `RUN_ERROR`, whether or not
    the broker still tracks it.

    A live run gets a `Fail` pushed into its own lane, which appends the event
    and relays it to any subscriber. A run the broker has already forgotten —
    an orphan reaped at startup is the one that reaches this — has no lane
    and no subscriber left, but the record still owes the verdict: the
    same event is appended directly, so the event stream ends the way the
    database says the run did. A run that already carries its own `RUN_ERROR`
    is left alone, same as everywhere else."""
    if funduq.broker.push(run_id, Fail(failure_reason)):
        return
    async with funduq.session() as session:
        events = await repo.get_run_events(session, run_id)
        if any(e.get("type") == EventType.RUN_ERROR for e in events):
            return
        seq = await repo.get_last_event_seq(session, run_id) + 1
        await repo.append_run_event(
            session, run_id, seq, run_error(failure_reason)
        )
        await session.commit()
