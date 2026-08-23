from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ag_ui.core import RunAgentInput

from funduq import repo
from funduq.models import AgentRef, LlmRef
from funduq.agui import rewrite_message_ids
from funduq.doors import (
    InboundRun,
    PendingAsk,
    dispatch,
    offline_events,
    open_run,
    resolve_kyok,
    verify_caller,
)
from funduq.errors import AgentNotFound
from funduq.kyok import strip_kyok_context
from funduq.pause import answered_asks, outstanding_asks

if TYPE_CHECKING:
    from funduq.core import Funduq


@dataclass
class EventStream:
    """A live run's AG-UI events, addressable by thread and run id before they are consumed.

    The events, not a framing of them. This used to carry an `encode()` that
    serialised each one to JSON while the serving layer added the `data:` and
    the blank line — half of SSE on each side of the boundary, with no
    principle deciding which half went where. Framing is now entirely the
    transport's.

    One rule constrains how a transport may frame these, and it is the
    unknown-event rule: an event whose `type` funduq does not recognise is
    relayed as **the original mapping**, so a serialiser that only accepts
    AG-UI's typed models (`ag_ui.encoder.EventEncoder` is one — it calls
    `model_dump_json` on what it is given) cannot be applied blindly. A
    provider on a newer AG-UI, or one marking its own absorption point with
    an event of its own naming, must survive the trip.
    """

    thread_id: str
    run_id: str
    events: AsyncIterator[dict[str, Any]]


@dataclass
class ThreadSnapshot:
    """Returned instead of a new run's `EventStream` when the target thread already has an
    active run that the incoming request isn't resuming; carries the thread's current state,
    including the in-flight run's id."""

    data: dict[str, Any]


class AGUIAdapter:

    def __init__(self, funduq: "Funduq") -> None:
        self._funduq = funduq

    async def run(self, agent: AgentRef, body: RunAgentInput) -> EventStream | ThreadSnapshot:
        """Starts (or resumes) an AG-UI run for `agent`. An unseen `body.thread_id` gets a new
        thread under a **funduq-minted id** — the caller's own id is deliberately not adopted, and
        the `threadId` on every returned event is the authoritative one to continue with (funduq
        owns its record's primary keys; a caller-chosen name has no caller identity to scope it
        to yet — see the design record on conversation naming rights). The caller-supplied
        `run_id` is likewise ignored in favour of funduq's own. A run on a thread
        that already has one in flight is accepted and offered to the provider in arrival
        order; whether the provider runs it immediately, holds it, or folds it into the turn
        in flight is the provider's own decision, and the returned stream stays silent until
        the provider starts producing. An AG-UI client normally holds one session per thread,
        so a second concurrent run is unusual but not refused. A resume with no surviving paused run to target (another caller answered first)
        gets a `ThreadSnapshot` instead of a stream. If the agent is registered but not currently
        served, the run is recorded as failed and the returned stream carries a `RUN_ERROR` event
        rather than hanging. Raises `AgentNotFound` if `agent` isn't registered,
        `LlmProviderNotFound` if a KYOK opt-in names an unknown LLM provider, and
        `InvalidRunInput` if the assembled AG-UI input is invalid."""
        funduq = self._funduq
        async with funduq.session() as session:
            if await repo.get_agent(session, agent) is None:
                raise AgentNotFound(f"agent '{agent}' is not registered")

            metadata = getattr(body, "metadata", None) or {}
            resume = [r.model_dump(mode="json", by_alias=True) for r in body.resume] if body.resume else None

            metadata, head_key, actor_chain = await verify_caller(session, metadata)
            metadata, kyok = await resolve_kyok(session, metadata)

            thread_id = await repo.ensure_thread(
                session,
                agent,
                body.thread_id,
                metadata=metadata,
                create_if_missing=True,
                head_key=head_key,
            )

            # AG-UI declares its entrance in the body, two ways, because it has
            # two carriers for the one thing. A `resume` payload declares a
            # result outright. A tool message declares one by naming the call
            # it answers — the same grammar as A2A's `taskId`, only finer: it
            # addresses the ask rather than the run. Neither is inferred from
            # the target's state; both are the caller saying what it sent.
            #
            # The difference is what happens when the addressing misses. A
            # `resume` that finds no ask is a result that lost its race, and
            # gets the thread as it stands. A tool message that answers
            # nothing pending is honestly just a message, so it enters as an
            # utterance — the rule the A2A lane already follows.
            #
            # Answering *some* of the asks is not answering: the provider must
            # hand its model a result for every call in the turn or it cannot
            # take a step, so a partial reply lands as an utterance and leaves
            # the ask standing rather than reopening a run that would fail.
            messages = [m.model_dump(mode="json", by_alias=True) for m in body.messages]
            answers_a_tool_call = any(m.get("role") == "tool" for m in messages)
            paused = (
                await repo.get_paused_run_for_thread(session, thread_id)
                if resume or answers_a_tool_call
                else None
            )
            outstanding = outstanding_asks(paused["metadata"]) if paused else set()
            completes_the_ask = bool(outstanding) and outstanding <= answered_asks(
                messages, resume, paused["metadata"]
            )
            is_result = bool(resume) or completes_the_ask

            input_dump = body.model_dump(mode="json", by_alias=True)
            if isinstance(input_dump.get("metadata"), dict):
                input_dump["metadata"] = strip_kyok_context(input_dump["metadata"])

            opened = await open_run(
                funduq, session,
                agent=agent,
                thread_id=thread_id,
                entrance="result" if is_result else "utterance",
                ask=(
                    PendingAsk(run_id=paused["run_id"], head_key=paused.get("head_key"))
                    if paused is not None and is_result
                    else None
                ),
                run_input=input_dump,
                metadata=metadata,
                head_key=head_key,
                protocol="ag-ui",
            )
            if opened is None:
                # A result with no ask to land on: there was none, or another
                # caller answered first. It must not enter dressed as an
                # utterance, so the caller gets the thread as it now stands.
                return ThreadSnapshot(await repo.get_thread_snapshot(session, thread_id))
            run_id, starting_seq = opened.run_id, opened.starting_seq

            inbound = InboundRun(
                agent=agent,
                messages=messages,
                metadata=metadata,
                head_key=head_key,
                actor_chain=actor_chain,
                kyok=kyok,
                state=body.state,
                tools=[t.model_dump(mode="json", by_alias=True) for t in body.tools],
                context=[c.model_dump(mode="json", by_alias=True) for c in body.context],
                resume=resume,
                # The caller's own parentRunId, relayed verbatim — AG-UI's
                # field for placing another run's id on this input; the
                # agent judges what the repetition means from its own loop.
                parent_run_id=body.parent_run_id,
                forwarded_props=body.forwarded_props,
                protocol="ag-ui",
            )
            live = await dispatch(
                funduq, session, inbound,
                thread_id=thread_id, run_id=run_id, starting_seq=starting_seq,
            )

        if not live:
            return EventStream(thread_id, run_id, offline_events(thread_id, run_id))
        return EventStream(thread_id, run_id, _relay(funduq.broker.subscribe(run_id)))


async def _relay(events: AsyncIterator[Any]) -> AsyncIterator[dict[str, Any]]:
    message_id_map: dict[str, str] = {}
    async for item in events:
        yield rewrite_message_ids(item, message_id_map)
