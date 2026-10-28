from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ag_ui.core import RunAgentInput

from funduq import repo
from funduq.models import AgentRef, LlmRef
from funduq.doors import InboundRun, enter, read_caller, waiting_on
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
    """Returned instead of a new run's `EventStream` when the input answers no open ask — there was none, or it was already answered — so no run is opened; carries the thread id and the run in flight, if any."""

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
            caller = await read_caller(session, body.forwarded_props, presenter_key=presenter_key)
            resume = [r.model_dump(mode="json", by_alias=True) for r in body.resume] if body.resume else None

            thread_id = await repo.ensure_thread(
                session,
                agent,
                body.thread_id,
                metadata=caller.props,
                create_if_missing=True,
                head_key=caller.head_key,
            )

            # AG-UI declares its entrance in the body, two ways, because it has two carriers for the one thing.
            messages = [m.model_dump(mode="json", by_alias=True) for m in body.messages]
            answers_a_tool_call = any(m.get("role") == "tool" for m in messages)
            latest = (
                await repo.latest_run_for_thread(session, thread_id)
                if resume or answers_a_tool_call
                else None
            )
            events = (await waiting_on(session, latest) if latest is not None else None) or []
            asks = open_asks(events)
            completes_the_ask = bool(asks) and asks <= answered_asks(messages, resume, events)
            if resume and not completes_the_ask:
                # A result with no ask to land on: there was none, or it was already answered.
                return ThreadSnapshot(await repo.get_thread_snapshot(session, thread_id))

            inbound = InboundRun(
                agent=agent,
                messages=messages,
                head_key=caller.head_key,
                actor_chain=caller.actor_chain,
                kyok=caller.kyok,
                state=body.state,
                tools=[t.model_dump(mode="json", by_alias=True) for t in body.tools],
                context=[c.model_dump(mode="json", by_alias=True) for c in body.context],
                resume=resume,
                # The caller's own parentRunId, relayed verbatim unless this input answers the thread's asks — then funduq names the run that asked.
                parent_run_id=body.parent_run_id,
                forwarded_props=caller.forwarded_props,
            )
            entered = await enter(
                funduq, session, inbound,
                thread_id=thread_id,
                answers=latest if completes_the_ask else None,
            )

        return EventStream(entered.thread_id, entered.run_id, entered.events(funduq))

