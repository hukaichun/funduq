from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ag_ui.core import RunAgentInput

from funduq import repo
from funduq.models import AgentRef, LlmRef
from funduq.doors import InboundRun, enter, read_caller
from funduq.errors import AgentNotFound, InvalidRunInput
from funduq.pause import open_asks

if TYPE_CHECKING:
    from funduq.core import Funduq


@dataclass
class EventStream:
    """A live run's AG-UI events, addressable by thread and run id before they are consumed."""

    thread_id: str
    run_id: str
    events: AsyncIterator[dict[str, Any]]


class AGUIAdapter:

    def __init__(self, funduq: "Funduq") -> None:
        self._funduq = funduq

    async def run(
        self,
        agent: AgentRef,
        body: RunAgentInput,
        *,
        presenter_key: str | None = None,
    ) -> EventStream:
        """Opens an AG-UI run for `agent`: every `RunAgentInput` is a run. It continues the run its `parentRunId` names, which must be on this thread and finished; without one it starts a lineage of its own."""
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

            messages = [m.model_dump(mode="json", by_alias=True) for m in body.messages]
            # Whether this run continues another is the caller's to say, with `parentRunId`; without it the run starts a lineage of its own. funduq checks only that the run it names is on this thread and has finished.
            parent = None
            if body.parent_run_id is not None:
                parent = await repo.get_run(session, body.parent_run_id)
                if parent is None or parent.thread_id != thread_id:
                    raise InvalidRunInput(f"parentRunId '{body.parent_run_id}' names no run on this thread")
                if parent.status in repo.ACTIVE_RUN_STATUSES:
                    raise InvalidRunInput(f"parentRunId '{body.parent_run_id}' names a run that has not finished")

            # Continuing a run that finished asking is answering it: on a bound thread the answer must carry a resolution proof.
            answers = parent if parent is not None and open_asks(await repo.get_run_events(session, parent.run_id)) else None

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
                parent_run_id=body.parent_run_id,
                forwarded_props=caller.forwarded_props,
            )
            entered = await enter(
                funduq, session, inbound,
                thread_id=thread_id,
                answers=answers,
            )

        return EventStream(entered.thread_id, entered.run_id, entered.events(funduq))

