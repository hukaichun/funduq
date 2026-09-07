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
    dispatch,
    offline_events,
    open_run,
    relayed_chain,
    resolve_kyok,
    verify_caller,
)
from funduq.errors import AgentNotFound
from funduq.pause import answered_asks, open_asks

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
        """Opens an AG-UI run for `agent`: every `RunAgentInput` is a run. One that answers the thread's open asks — tool messages for its unanswered calls, `resume` entries for its interrupts — is the next run, with `parentRunId` naming the one that asked."""
        funduq = self._funduq
        async with funduq.session() as session:
            if await repo.get_agent(session, agent) is None:
                raise AgentNotFound(f"agent '{agent}' is not registered")

            # The caller's bag: declarations to funduq ride here, beside whatever it forwards to the agent.
            props = body.forwarded_props if isinstance(body.forwarded_props, dict) else {}
            resume = [r.model_dump(mode="json", by_alias=True) for r in body.resume] if body.resume else None

            props, head_key, actor_chain = await verify_caller(session, props, presenter_key=presenter_key)
            props, kyok = await resolve_kyok(session, props)

            thread_id = await repo.ensure_thread(
                session,
                agent,
                body.thread_id,
                metadata=props,
                create_if_missing=True,
                head_key=head_key,
            )

            # AG-UI declares its entrance in the body, two ways, because it has two carriers for the one thing.
            messages = [m.model_dump(mode="json", by_alias=True) for m in body.messages]
            answers_a_tool_call = any(m.get("role") == "tool" for m in messages)
            latest = (
                await repo.latest_run_for_thread(session, thread_id)
                if resume or answers_a_tool_call
                else None
            )
            asks: set[str] = set()
            events: list[dict] = []
            if latest is not None and latest.status == "completed" and latest.cancel_requested_by is None:
                events = await repo.get_run_events(session, latest.run_id)
                asks = open_asks(events)
            completes_the_ask = bool(asks) and asks <= answered_asks(messages, resume, events)
            if (resume or completes_the_ask) and not completes_the_ask:
                # A result with no ask to land on: there was none, or it was already answered.
                return ThreadSnapshot(await repo.get_thread_snapshot(session, thread_id))

            inbound = InboundRun(
                agent=agent,
                messages=messages,
                head_key=head_key,
                # Signed before the run is created, so the record keeps exactly what the agent receives.
                actor_chain=relayed_chain(funduq, actor_chain, agent),
                kyok=kyok,
                state=body.state,
                tools=[t.model_dump(mode="json", by_alias=True) for t in body.tools],
                context=[c.model_dump(mode="json", by_alias=True) for c in body.context],
                resume=resume,
                # The caller's own parentRunId, relayed verbatim unless this input answers the thread's asks — then funduq names the run that asked.
                parent_run_id=body.parent_run_id,
                forwarded_props=props if isinstance(body.forwarded_props, dict) else body.forwarded_props,
            )
            opened = await open_run(
                funduq, session, inbound,
                thread_id=thread_id,
                answers=latest if completes_the_ask else None,
            )
            run_id = opened.run_id
            live = await dispatch(funduq, session, inbound, opened)

        if not live:
            return EventStream(thread_id, run_id, offline_events(thread_id, run_id))
        return EventStream(thread_id, run_id, _relay(funduq.broker.subscribe(run_id)))


async def _relay(events: AsyncIterator[Any]) -> AsyncIterator[dict[str, Any]]:
    message_id_map: dict[str, str] = {}
    async for item in events:
        yield rewrite_message_ids(item, message_id_map)
