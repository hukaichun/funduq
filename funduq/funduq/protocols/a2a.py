from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from a2a.server.context import ServerCallContext
from a2a.server.events import Event
from a2a.server.request_handlers.request_handler import (
    RequestHandler,
    validate_request_params,
)
from a2a.types import a2a_pb2 as pb
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol
from a2a.utils.errors import (
    InvalidParamsError,
    TaskNotCancelableError,
    TaskNotFoundError,
    UnsupportedOperationError,
)
from google.protobuf.json_format import MessageToDict, ParseDict, ParseError

from funduq import repo
from funduq.doors import (
    InboundRun,
    authorize_view,
    dispatch,
    open_run,
    relayed_chain,
    resolve_kyok,
    verify_caller,
)
from funduq.errors import (
    AgentNotFound,
    InvalidRunInput,
    LlmProviderNotFound,
    RunNotCancellable,
    ThreadNotFound,
    ThreadOwnershipMismatch,
)
from funduq.identity import InvalidView
from funduq.pause import open_asks
from funduq.props import ADDRESSED_RUN_METADATA_KEY
from funduq.models import AgentRef
from funduq.protocols.a2a_translate import (
    TERMINAL_STATES,
    a2a_message_to_agui_messages,
    agui_event_to_a2a_update,
    build_task,
    state_for_run_status,
    status_update_for_run_status,
)

if TYPE_CHECKING:
    from funduq.core import Funduq

logger = logging.getLogger("funduq.protocols.a2a")

PROTOCOL_VERSION = PROTOCOL_VERSION_CURRENT

_BINDINGS = frozenset(member.name for member in TransportProtocol)


@dataclass(frozen=True)
class ServedInterface:
    """A URL where an agent's A2A endpoint is reachable, together with the A2A transport binding it speaks (e.g."""

    url: str
    binding: str

    def __post_init__(self) -> None:
        if self.binding not in _BINDINGS:
            raise ValueError(
                f"unknown A2A binding {self.binding!r} — A2A defines {sorted(_BINDINGS)}"
            )


# Caller mistakes funduq has its own words for, and the A2A word for each.
_BAD_PARAMETER = (
    ThreadNotFound,
    ThreadOwnershipMismatch,
    LlmProviderNotFound,
    InvalidRunInput,
)


@contextlib.contextmanager
def _in_a2as_words():
    """Re-raises funduq's caller-caused errors as A2A's own, so a transport can answer without a translation table of funduq's."""
    try:
        yield
    except _BAD_PARAMETER as e:
        raise InvalidParamsError(str(e)) from e


class A2AAdapter:

    def __init__(self, funduq: "Funduq") -> None:
        self._funduq = funduq

    async def agent_card(
        self, agent: AgentRef, interfaces: "list[ServedInterface] | None" = None
    ) -> pb.AgentCard:
        """Builds the A2A agent card for `agent`, listing `interfaces` as its supported interfaces (omitted from the card entirely if none are given)."""
        record = await self._funduq.get_agent(agent)
        if record is None:
            raise AgentNotFound(f"agent '{agent}' is not registered")
        card = dict(record.agent_card)
        return pb.AgentCard(
            name=card.get("name", record.name),
            description=card.get("description", ""),
            version=card.get("version", "0.1.0"),
            supported_interfaces=[
                pb.AgentInterface(
                    url=served.url,
                    protocol_binding=TransportProtocol[served.binding].value,
                    protocol_version=PROTOCOL_VERSION,
                )
                for served in (interfaces or [])
            ],
            capabilities=pb.AgentCapabilities(
                streaming=True,
                extensions=[
                    pb.AgentExtension(uri=uri) for uri in card.get("extensions", [])
                ],
            ),
            default_input_modes=["text/plain"],
            default_output_modes=["text/plain"],
            skills=_skills(card.get("skills", [])),
        )

    async def _task(
        self,
        agent: AgentRef,
        task_id: str,
        *,
        history_length: int | None = None,
        cancel_requested: bool = False,
    ) -> pb.Task:
        """The task named `task_id` as it stands: its lineage's events in order, its tail's status, the thread's messages as history."""
        lineage = await self._funduq.lineage(task_id)
        tail = lineage[-1]
        events: list[dict[str, Any]] = []
        tail_events: list[dict[str, Any]] = []
        for run in lineage:
            tail_events = await self._funduq.get_run_events(run.run_id)
            events.extend(tail_events)
        return build_task(
            task_id,
            tail.thread_id,
            await self._display_name(agent),
            tail.status,
            events,
            thread_messages=await self._funduq.get_thread_messages(tail.thread_id),
            history_length=history_length,
            cancel_requested=cancel_requested or tail.cancel_requested_by is not None,
            tail_events=tail_events,
        )

    async def send_task(
        self,
        agent: AgentRef,
        message: dict[str, Any],
        *,
        actor_chain: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        presenter_key: str | None = None,
        return_immediately: bool = False,
        history_length: int | None = None,
    ) -> pb.Task:
        """Sends `message` to `agent` — a new task, or the answer a waiting task asked for (via `taskId`) — waits for the run it opened to settle, and returns the `Task`. With `return_immediately` it answers with the Task as it stands instead — funduq's queued lane makes `submitted` a state with real duration, and this is how a polling caller learns that is where its run is."""
        with _in_a2as_words():
            run_id, task_id, is_live = await self._start_run(
                agent, _params(message, actor_chain, metadata), presenter_key=presenter_key
            )
        if not return_immediately and is_live and self._funduq.broker.get(run_id) is not None:
            async for _ in self._funduq.broker.subscribe(run_id):
                pass
        return await self._task(agent, task_id, history_length=history_length)

    async def send_task_streaming(
        self,
        agent: AgentRef,
        message: dict[str, Any],
        *,
        actor_chain: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        presenter_key: str | None = None,
    ) -> AsyncIterator[Event]:
        """Like `send_task` but yields A2A stream events as the run progresses instead of waiting for it to settle. Every event carries the task's id — the lineage's root — whichever run in it produced the event."""
        with _in_a2as_words():
            run_id, task_id, is_live = await self._start_run(
                agent, _params(message, actor_chain, metadata), presenter_key=presenter_key
            )
        live = is_live and self._funduq.broker.get(run_id) is not None
        events = self._funduq.broker.subscribe(run_id) if live else None

        async def results() -> AsyncIterator[Event]:
            opening = await self._task(agent, task_id)
            yield opening
            if not live:
                stored = await self._funduq.get_run(run_id)
                yield status_update_for_run_status(task_id, opening.context_id, stored.status if stored else "completed")
                return
            opened: set[str] = {a.artifact_id for a in opening.artifacts}
            async for item in events:
                yield agui_event_to_a2a_update(item, task_id, opening.context_id, opened=opened)
            stored = await self._funduq.get_run(run_id)
            if stored is not None and stored.status != "completed":
                yield status_update_for_run_status(task_id, opening.context_id, stored.status)

        return results()

    async def resubscribe_task(
        self,
        agent: AgentRef,
        task_id: str,
        *,
        view_metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[Event]:
        """Reattaches to a task's event stream: the Task as it stands, then whatever its tail run still produces. A bound run demands a view proof, exactly as `get_task` does, and answers its absence the same way; a task in a terminal state has nothing left to stream and is refused, as A2A requires (§3.1.6)."""
        run = await self._run_of(agent, task_id)
        if run is None or not self._may_view(run, view_metadata):
            raise TaskNotFoundError(f"no task '{task_id}' for agent '{agent}'")
        opening = await self._task(agent, task_id)
        if opening.status.state in TERMINAL_STATES:
            raise UnsupportedOperationError(f"task {task_id} has ended; there is nothing to subscribe to")
        tail = (await self._funduq.lineage(task_id))[-1]
        events = self._funduq.broker.subscribe(tail.run_id) if self._funduq.broker.get(tail.run_id) else None

        async def results() -> AsyncIterator[Event]:
            yield opening
            if events is None:
                yield status_update_for_run_status(task_id, opening.context_id, tail.status)
                return
            # The opening snapshot already carries whatever the task had produced, so those artifacts exist for the receiver already.
            opened: set[str] = {a.artifact_id for a in opening.artifacts}
            async for item in events:
                yield agui_event_to_a2a_update(item, task_id, opening.context_id, opened=opened)
            stored = await self._funduq.get_run(tail.run_id)
            if stored is not None and stored.status != "completed":
                yield status_update_for_run_status(task_id, opening.context_id, stored.status)

        return results()

    async def get_task(
        self,
        agent: AgentRef,
        task_id: str,
        *,
        history_length: int | None = None,
        view_metadata: dict[str, Any] | None = None,
    ) -> pb.Task | None:
        """Returns the current `Task` for `task_id`, or None if it doesn't belong to `agent` — or if the run is bound to a chain and `view_metadata` carries no valid view proof from one of its parties. An unauthorized read looks like absence: existence is part of what is guarded."""
        run = await self._run_of(agent, task_id)
        if run is None or not self._may_view(run, view_metadata):
            return None
        return await self._task(agent, task_id, history_length=history_length)

    async def cancel_task(
        self, agent: AgentRef, task_id: str, *, metadata: dict[str, Any] | None = None
    ) -> pb.Task | None:
        """Asks the task's tail run to stop and returns the task as it stands, marked with the pending request. A task waiting for input has no provider to ask: cancelling it closes the wait."""
        run = await self._run_of(agent, task_id)
        if run is None:
            return None
        current = await self._task(agent, task_id)
        if current.status.state in TERMINAL_STATES:
            raise TaskNotCancelableError(
                f"task {task_id} has already ended and cannot be cancelled"
            )
        tail = (await self._funduq.lineage(task_id))[-1]
        try:
            asked = await self._funduq.cancel_run(tail.run_id, metadata=metadata or {})
        except RunNotCancellable as e:
            raise TaskNotCancelableError(str(e)) from e
        return await self._task(agent, task_id, cancel_requested=asked)

    async def _run_of(self, agent: AgentRef, task_id: str):
        """The run for `task_id`, or None if it doesn't exist or belongs to a different agent."""
        run = await self._funduq.get_run(task_id) if task_id else None
        if run is None or AgentRef(provider_key=run.provider_key, name=run.agent_name) != agent:
            return None
        return run

    @staticmethod
    def _may_view(run: Any, view_metadata: dict[str, Any] | None) -> bool:
        """Whether this read carries the authority a bound run demands; always true for an unbound one."""
        try:
            authorize_view(run, view_metadata or {})
        except InvalidView:
            return False
        return True

    async def _display_name(self, agent: AgentRef) -> str:
        record = await self._funduq.get_agent(agent)
        return record.name if record else agent.name

    async def _start_run(
        self, agent: AgentRef, params: dict, *, presenter_key: str | None = None
    ) -> tuple[str, str, bool]:
        """Resolves `params` (a `contextId`/`taskId`/message envelope) to the run it opens and the task that run belongs to, and returns `(run_id, task_id, is_live)`.

        Every message is a run. A message naming a task that is waiting for
        input answers it: the new run's `parentRunId` is the task's tail and
        the task id is unchanged. A message naming a task in any other state
        is refused — the one follow-up A2A defines is the answer (§3.1.1,
        §3.4.3) — and a `contextId` that disagrees with the task's is
        rejected.
        """
        funduq = self._funduq
        async with funduq.session() as session:
            record = await repo.get_agent(session, agent)
            if record is None:
                raise AgentNotFound(f"agent '{agent}' is not registered")

            # The caller's bag: the message's metadata (plus the request's), where its declarations to funduq ride.
            props = dict(params.get("metadata") or {})
            props, kyok = await resolve_kyok(session, props)
            parent_thread_id = await _lineage_parent(session, params)

            task_id = params.get("taskId")
            root = None
            answers = None
            if task_id:
                root = await repo.get_run(session, task_id)
                if root is None or root.agent != agent:
                    raise TaskNotFoundError(f"no task '{task_id}'")
                if params.get("contextId") and params["contextId"] != root.thread_id:
                    raise InvalidParamsError(
                        f"contextId '{params['contextId']}' is not the context of task '{task_id}'"
                    )
                tail = await repo.lineage_tail(session, task_id)
                if (
                    tail.status != "completed"
                    or tail.cancel_requested_by is not None
                    or not open_asks(await repo.get_run_events(session, tail.run_id))
                ):
                    raise UnsupportedOperationError(
                        f"task '{task_id}' is not waiting for input; a message naming a task is its answer"
                    )
                answers = tail
            context_id = params.get("contextId") or (root.thread_id if root is not None else None)

            props, head_key, actor_chain = await verify_caller(session, props, presenter_key=presenter_key)

            thread_id = await repo.ensure_thread(
                session, agent, context_id, parent_thread_id,
                metadata=props, head_key=head_key,
            )

            messages = a2a_message_to_agui_messages(params.get("message", {}))
            inbound = InboundRun(
                agent=agent,
                messages=messages,
                head_key=head_key,
                # Signed before the run is created, so the record keeps exactly what the agent receives.
                actor_chain=relayed_chain(funduq, actor_chain, agent),
                kyok=kyok,
                # The extension convention puts the key in the Message's own metadata map, which is in the bag.
                addressed_run_id=props.get(ADDRESSED_RUN_METADATA_KEY),
                forwarded_props=props,
            )
            opened = await open_run(funduq, session, inbound, thread_id=thread_id, answers=answers)
            live = await dispatch(funduq, session, inbound, opened)

        return opened.run_id, (root.run_id if root is not None else opened.run_id), live


class A2ARequestHandler(RequestHandler):
    """The A2A door as `a2a.server`'s own `RequestHandler`, bound to one agent.

    How far to support the protocol is the transport's decision, not funduq's:
    it mounts the package's dispatchers for whichever bindings and spec
    versions it chooses to serve, and method names, envelopes, error codes and
    version negotiation all come from the package that defines them. Every
    choice arrives here as the same protobuf-typed calls, forwarded to
    `A2AAdapter`. What funduq decides is which operations are offered — the
    six that are not answer `UnsupportedOperationError`.
    """

    def __init__(
        self,
        funduq: "Funduq",
        agent: AgentRef,
        *,
        presenter_key_of: Callable[[ServerCallContext], str | None] | None = None,
        view_metadata_of: Callable[[ServerCallContext], dict | None] | None = None,
    ) -> None:
        self._adapter = A2AAdapter(funduq)
        self._agent = agent
        # The transport is the party that authenticates whoever presents a
        # request; this hook is where it hands that identity down.
        self._presenter_key_of = presenter_key_of
        # A2A's read requests carry no caller data, so a view proof for a
        # bound run rides the transport (a header, typically); this hook is
        # where the transport hands it down as `{"view": …}`.
        self._view_metadata_of = view_metadata_of

    def _presenter_key(self, context: ServerCallContext) -> str | None:
        return self._presenter_key_of(context) if self._presenter_key_of else None

    def _view_metadata(self, context: ServerCallContext) -> dict | None:
        return self._view_metadata_of(context) if self._view_metadata_of else None

    @validate_request_params
    async def on_message_send(
        self, params: pb.SendMessageRequest, context: ServerCallContext
    ) -> pb.Task:
        # Of the configuration's four fields, two are honoured here and two
        # deliberately not — the stance is pinned by
        # test_every_send_configuration_field_is_either_honoured_or_deliberately_not.
        wire = MessageToDict(params)
        return await self._adapter.send_task(
            self._agent,
            wire.get("message", {}),
            metadata=wire.get("metadata"),
            presenter_key=self._presenter_key(context),
            return_immediately=params.configuration.return_immediately,
            history_length=(
                params.configuration.history_length
                if params.configuration.HasField("history_length")
                else None
            ),
        )

    @validate_request_params
    async def on_message_send_stream(
        self, params: pb.SendMessageRequest, context: ServerCallContext
    ) -> AsyncGenerator[Event]:
        wire = MessageToDict(params)
        stream = await self._adapter.send_task_streaming(
            self._agent,
            wire.get("message", {}),
            metadata=wire.get("metadata"),
            presenter_key=self._presenter_key(context),
        )
        async for event in stream:
            yield event

    @validate_request_params
    async def on_get_task(
        self, params: pb.GetTaskRequest, context: ServerCallContext
    ) -> pb.Task | None:
        return await self._adapter.get_task(
            self._agent,
            params.id,
            history_length=params.history_length if params.HasField("history_length") else None,
            view_metadata=self._view_metadata(context),
        )

    @validate_request_params
    async def on_cancel_task(
        self, params: pb.CancelTaskRequest, context: ServerCallContext
    ) -> pb.Task | None:
        wire = MessageToDict(params)
        return await self._adapter.cancel_task(
            self._agent, params.id, metadata=wire.get("metadata")
        )

    @validate_request_params
    async def on_subscribe_to_task(
        self, params: pb.SubscribeToTaskRequest, context: ServerCallContext
    ) -> AsyncGenerator[Event]:
        stream = await self._adapter.resubscribe_task(
            self._agent, params.id, view_metadata=self._view_metadata(context)
        )
        async for event in stream:
            yield event

    # Push notifications: funduq pushes nothing outward on a caller's behalf.

    async def on_create_task_push_notification_config(
        self, params: pb.TaskPushNotificationConfig, context: ServerCallContext
    ) -> pb.TaskPushNotificationConfig:
        raise UnsupportedOperationError(_PUSHES_NOTHING)

    async def on_get_task_push_notification_config(
        self, params: pb.GetTaskPushNotificationConfigRequest, context: ServerCallContext
    ) -> pb.TaskPushNotificationConfig:
        raise UnsupportedOperationError(_PUSHES_NOTHING)

    async def on_list_task_push_notification_configs(
        self,
        params: pb.ListTaskPushNotificationConfigsRequest,
        context: ServerCallContext,
    ) -> pb.ListTaskPushNotificationConfigsResponse:
        raise UnsupportedOperationError(_PUSHES_NOTHING)

    async def on_delete_task_push_notification_config(
        self,
        params: pb.DeleteTaskPushNotificationConfigRequest,
        context: ServerCallContext,
    ) -> None:
        raise UnsupportedOperationError(_PUSHES_NOTHING)

    # Listing tasks and the extended card are the transport's to answer if it
    # wants them; core exposes the roster its own way.

    async def on_list_tasks(
        self, params: pb.ListTasksRequest, context: ServerCallContext
    ) -> pb.ListTasksResponse:
        raise UnsupportedOperationError("listing tasks is not offered through the A2A door")

    async def on_get_extended_agent_card(
        self, params: pb.GetExtendedAgentCardRequest, context: ServerCallContext
    ) -> pb.AgentCard:
        raise UnsupportedOperationError("funduq has no extended agent card")


_PUSHES_NOTHING = "funduq pushes nothing outward on a caller's behalf"


def _skills(raw_skills: list[dict[str, Any]]) -> list[pb.AgentSkill]:
    skills = []
    for raw in raw_skills:
        try:
            skills.append(ParseDict(raw, pb.AgentSkill(), ignore_unknown_fields=True))
        except ParseError:
            logger.warning("agent card: skipping a skill that is not an A2A AgentSkill: %r", raw)
    return skills


async def _lineage_parent(session, params: dict) -> str | None:
    reference_task_ids = params.get("message", {}).get("referenceTaskIds") or []
    if not reference_task_ids:
        return None
    referenced = await repo.get_run(session, reference_task_ids[0])
    return referenced.thread_id if referenced is not None else None


def _params(
    message: dict[str, Any],
    actor_chain: list[str] | None,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    """Lifts the fields `_start_run` addresses by name out of the A2A message they live on. The caller's bag is the message's `metadata` with the request's underneath it; a chain handed in by name lands in the same bag."""
    combined = {**(metadata or {}), **(message.get("metadata") or {})}
    if actor_chain:
        combined["actorChain"] = actor_chain
    return {
        "message": dict(message),
        "contextId": message.get("contextId"),
        "taskId": message.get("taskId"),
        "metadata": combined,
    }
