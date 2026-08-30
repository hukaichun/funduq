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
    relayed_chain,
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
    """A live run's AG-UI events, addressable by thread and run id before they are consumed."""

    thread_id: str
    run_id: str
    events: AsyncIterator[dict[str, Any]]


@dataclass
class ThreadSnapshot:
    """Returned instead of a new run's `EventStream` when the target thread already has an active run that the incoming request isn't resuming; carries the thread's current state, including the in-flight run's id."""

    data: dict[str, Any]


class AGUIAdapter:

    def __init__(self, funduq: "Funduq") -> None:
        self._funduq = funduq

    async def run(
        self,
        agent: AgentRef,
        body: RunAgentInput,
        *,
        presenter_key: str | None = None,
    ) -> EventStream | ThreadSnapshot:
        """Starts (or resumes) an AG-UI run for `agent`."""
        funduq = self._funduq
        async with funduq.session() as session:
            if await repo.get_agent(session, agent) is None:
                raise AgentNotFound(f"agent '{agent}' is not registered")

            metadata = getattr(body, "metadata", None) or {}
            resume = [r.model_dump(mode="json", by_alias=True) for r in body.resume] if body.resume else None

            metadata, head_key, actor_chain = await verify_caller(session, metadata, presenter_key=presenter_key)
            metadata, kyok = await resolve_kyok(session, metadata)

            thread_id = await repo.ensure_thread(
                session,
                agent,
                body.thread_id,
                metadata=metadata,
                create_if_missing=True,
                head_key=head_key,
            )

            # AG-UI declares its entrance in the body, two ways, because it has two carriers for the one thing.
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

            # Signed before the run is created, so the record keeps exactly what the agent receives.
            chain = relayed_chain(funduq, actor_chain, agent)

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
                actor_chain=chain,
                protocol="ag-ui",
            )
            if opened is None:
                # A result with no ask to land on: there was none, or another caller answered first.
                return ThreadSnapshot(await repo.get_thread_snapshot(session, thread_id))
            run_id, starting_seq = opened.run_id, opened.starting_seq
            if opened.landed_on_ask:
                # The run's own chain and head, never the answering party's.
                landed = await repo.get_run(session, run_id)
                chain, head_key = landed.actor_chain, landed.head_key

            inbound = InboundRun(
                agent=agent,
                messages=messages,
                metadata=metadata,
                head_key=head_key,
                actor_chain=chain,
                kyok=kyok,
                state=body.state,
                tools=[t.model_dump(mode="json", by_alias=True) for t in body.tools],
                context=[c.model_dump(mode="json", by_alias=True) for c in body.context],
                resume=resume,
                # The caller's own parentRunId, relayed verbatim — AG-UI's field for placing another run's id on this input; the agent judges what the repetition means from its own loop.
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
