from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from a2a.server.events import Event
from a2a.types import a2a_pb2 as pb
from a2a.utils.constants import PROTOCOL_VERSION_CURRENT, TransportProtocol
from a2a.utils.errors import InvalidParamsError, TaskNotFoundError
from google.protobuf.json_format import ParseDict, ParseError

from funduq import repo
from funduq.doors import InboundRun, dispatch, resolve_kyok, verify_caller
from funduq.errors import (
    AgentNotFound,
    InvalidRunInput,
    LlmProviderNotFound,
    ThreadNotFound,
    ThreadOwnershipMismatch,
)
from funduq.identity import verify_resolution
from funduq.props import ADDRESSED_RUN_METADATA_KEY
from funduq.models import AgentRef
from funduq.protocols.a2a_translate import (
    a2a_message_to_agui_messages,
    agui_event_to_a2a_update,
    build_task,
    status_update_for_run_status,
)

if TYPE_CHECKING:
    from funduq.core import Funduq

logger = logging.getLogger("funduq.protocols.a2a")

PROTOCOL_VERSION = PROTOCOL_VERSION_CURRENT

_BINDINGS = frozenset(member.name for member in TransportProtocol)


@dataclass(frozen=True)
class ServedInterface:
    """A URL where an agent's A2A endpoint is reachable, together with the A2A transport
    binding it speaks (e.g. `"JSONRPC"`). Raises `ValueError` if `binding` is not a name A2A's
    `TransportProtocol` defines."""

    url: str
    binding: str

    def __post_init__(self) -> None:
        if self.binding not in _BINDINGS:
            raise ValueError(
                f"unknown A2A binding {self.binding!r} — A2A defines {sorted(_BINDINGS)}"
            )


# Caller mistakes funduq has its own words for, and the A2A word for each.
# Translating them here is what the rest of this module does for everything
# else: funduq's vocabulary in, A2A's out. A caller that names a context
# funduq does not have, one belonging to another agent, an offering that is
# not registered, or a message that will not build a run input has made the
# same kind of mistake — a bad parameter — and A2A has one word for that.
# The code the caller finally sees comes from the package's own table
# (`JSON_RPC_ERROR_CODE_MAP`), never from a literal here.
_BAD_PARAMETER = (
    ThreadNotFound,
    ThreadOwnershipMismatch,
    LlmProviderNotFound,
    InvalidRunInput,
)


@contextlib.contextmanager
def _in_a2as_words():
    """Re-raises funduq's caller-caused errors as A2A's own, so a transport can answer without
    a translation table of funduq's.

    Two deliberately stay funduq's, because A2A has no word for either and
    inventing one would be worse than passing them on:

    - `AgentNotFound` is not a bad *parameter*. The agent is the endpoint,
      resolved from the route before this adapter is called at all, so an
      unknown one means the address does not exist — a routing-layer
      answer (404), not a JSON-RPC error inside a 200.
    - `ThreadQueueFull` is backpressure: funduq telling a caller to come
      back, with the thread's buffer full and the request **not** accepted.
      A2A has no code for "slow down" because pacing is a transport
      concern; the gateway's answer is 429.

    Both are documented in `docs/writing-a-transport.md` rather than
    mapped reflexively onto a word that means something else.
    """
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
        """Builds the A2A agent card for `agent`, listing `interfaces` as its supported
        interfaces (omitted from the card entirely if none are given). Raises `AgentNotFound`
        if `agent` isn't registered."""
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
            capabilities=pb.AgentCapabilities(streaming=True),
            default_input_modes=["text/plain"],
            default_output_modes=["text/plain"],
            skills=_skills(card.get("skills", [])),
        )

    async def send_task(
        self,
        agent: AgentRef,
        message: dict[str, Any],
        *,
        actor_chain: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> pb.Task:
        """Sends `message` to `agent` as a new (or continuing, via `context_id`/`task_id`) A2A
        task, waits for it to settle, and returns the resulting `Task`. Behind A2A's
        send-a-message operation, whatever the transport calls it.

        The task is built from the run's **stored** events, always. A live
        run's stream is drained only to wait for it — the events were
        persisted before they reached that stream, so by the time it ends
        the log is complete, and reading one source rather than two is what
        keeps a task fetched afterwards from disagreeing with the one
        returned here.
        """
        with _in_a2as_words():
            run_id, thread_id, is_live = await self._start_run(
                agent, _params(message, actor_chain, metadata)
            )
        if is_live and self._funduq.broker.get(run_id) is not None:
            async for _ in self._funduq.broker.subscribe(run_id):
                pass
        stored = await self._funduq.get_run(run_id)
        return build_task(
            run_id,
            thread_id,
            await self._display_name(agent),
            stored.status if stored else "completed",
            await self._funduq.get_run_events(run_id),
        )

    async def send_task_streaming(
        self,
        agent: AgentRef,
        message: dict[str, Any],
        *,
        actor_chain: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[Event]:
        """Like `send_task` but yields A2A stream events as the run progresses instead of
        waiting for it to settle. If the run turns out not to be live (e.g. it was already
        finished), yields a single status update reflecting its stored status.

        The events are A2A's own, and the stream opens with the **`Task`
        itself**: A2A carries a task as a snapshot followed by increments
        layered onto it, so a receiver that gets a status update first has
        nothing to layer onto — the package's own aggregator refuses that
        stream rather than tolerating it. Wrapping any of it for a wire is
        the transport's job, not this one's.
        """
        with _in_a2as_words():
            run_id, thread_id, is_live = await self._start_run(
                agent, _params(message, actor_chain, metadata)
            )
        live = is_live and self._funduq.broker.get(run_id) is not None
        events = self._funduq.broker.subscribe(run_id) if live else None

        async def results() -> AsyncIterator[Event]:
            stored = await self._funduq.get_run(run_id)
            yield build_task(
                run_id,
                thread_id,
                await self._display_name(agent),
                stored.status if stored else "queued",
                [],
            )
            if not live:
                status = stored.status if stored else "completed"
                yield status_update_for_run_status(run_id, thread_id, status)
                return
            opened: set[str] = set()
            async for item in events:
                yield agui_event_to_a2a_update(item, run_id, thread_id, opened=opened)
            stored = await self._funduq.get_run(run_id)
            if stored is not None and stored.status != "completed":
                yield status_update_for_run_status(run_id, thread_id, stored.status)

        return results()

    async def resubscribe_task(self, agent: AgentRef, task_id: str) -> AsyncIterator[Event]:
        """Reattaches to an existing task's event stream. If the task is no longer live, yields
        its final stored-status update instead of hanging. Raises A2A's own `TaskNotFoundError`
        if `task_id` doesn't belong to `agent`."""
        run = await self._run_of(agent, task_id)
        if run is None:
            raise TaskNotFoundError(f"no task '{task_id}' for agent '{agent}'")
        thread_id = run.thread_id
        events = self._funduq.broker.subscribe(task_id) if self._funduq.broker.get(task_id) else None
        opening = build_task(
            task_id,
            thread_id,
            await self._display_name(agent),
            run.status,
            await self._funduq.get_run_events(task_id),
        )

        async def results() -> AsyncIterator[Event]:
            yield opening
            if events is None:
                yield status_update_for_run_status(task_id, thread_id, run.status)
                return
            # The opening snapshot already carries whatever this run had
            # produced, so those artifacts exist for the receiver already.
            opened: set[str] = {a.artifact_id for a in opening.artifacts}
            async for item in events:
                yield agui_event_to_a2a_update(item, task_id, thread_id, opened=opened)
            stored = await self._funduq.get_run(task_id)
            if stored is not None and stored.status != "completed":
                yield status_update_for_run_status(task_id, thread_id, stored.status)

        return results()

    async def get_task(self, agent: AgentRef, task_id: str) -> pb.Task | None:
        """Returns the current `Task` for `task_id`, or None if it doesn't belong to `agent`.

        None rather than an exception, because that is what A2A's own
        request-handler interface means by not-found; the transport turns it
        into the error its binding defines.
        """
        run = await self._run_of(agent, task_id)
        if run is None:
            return None
        return build_task(
            task_id,
            run.thread_id,
            await self._display_name(agent),
            run.status,
            await self._funduq.get_run_events(task_id),
        )

    async def cancel_task(self, agent: AgentRef, task_id: str) -> pb.Task | None:
        """Requests cancellation of the running task and returns its resulting `Task` (funduq
        can only ask the provider to stop, not force it, so the returned status reflects
        whatever the provider actually did). None if `task_id` doesn't belong to `agent`."""
        run = await self._run_of(agent, task_id)
        if run is None:
            return None
        self._funduq.cancel_run(task_id)
        current = await self._funduq.get_run(task_id) or run
        return build_task(
            task_id,
            run.thread_id,
            await self._display_name(agent),
            current.status,
            await self._funduq.get_run_events(task_id),
        )


    async def _run_of(self, agent: AgentRef, task_id: str):
        """The run for `task_id`, or None if it doesn't exist or belongs to a different agent."""
        run = await self._funduq.get_run(task_id) if task_id else None
        if run is None or AgentRef(provider_key=run.provider_key, name=run.agent_name) != agent:
            return None
        return run

    async def _display_name(self, agent: AgentRef) -> str:
        record = await self._funduq.get_agent(agent)
        return record.name if record else agent.name

    async def _start_run(self, agent: AgentRef, params: dict) -> tuple[str, str, bool]:
        """Resolves `params` (a `contextId`/`taskId`/message envelope) to a thread and run,
        creating or reopening whichever is needed, and returns `(run_id, thread_id, is_live)`.
        A message addressed (via `taskId`) to the thread's paused `input-required` task resumes
        it; any other message becomes a new queued run, offered to the provider in arrival
        order — a message sent while a run is active is delivered alongside it, never merged
        or dropped; how the provider sequences its turns is the provider's own business. `is_live` is False
        only if the agent isn't currently served (in which case the run is
        recorded as failed). A `metadata.kyok` opt-in binds the run to the named LLM offering
        (raising `LlmProviderNotFound` for an unknown one), the same road AG-UI callers use.
        A `referenceTaskIds` entry anchors thread lineage to the referenced task's thread, and
        that is **all** it does: it is A2A's word for "this came from that", not a grant. A run
        spends against the opt-in its own caller submitted, and nothing propagates."""
        funduq = self._funduq
        async with funduq.session() as session:
            record = await repo.get_agent(session, agent)
            if record is None:
                raise AgentNotFound(f"agent '{agent}' is not registered")

            metadata, kyok = await resolve_kyok(session, params.get("metadata", {}))
            parent_thread_id = await _lineage_parent(session, params)
            context_id = params.get("contextId") or await _context_of_task(session, params.get("taskId"))

            metadata, head_key, actor_chain = await verify_caller(session, metadata)

            thread_id = await repo.ensure_thread(
                session, agent, context_id, parent_thread_id,
                metadata=metadata, head_key=head_key,
            )

            messages = a2a_message_to_agui_messages(params.get("message", {}))
            run_input = {"thread_id": thread_id, "messages": messages}

            # Two lanes. A message whose taskId names this thread's paused
            # (input-required) task resumes that run with whatever it says —
            # funduq never checks that it answers the question; the provider
            # judges answer-vs-redirect from the thread's shape (the reopen
            # is status-guarded so two concurrent resumes resolve to one;
            # the loser lands in the queue lane like any other utterance).
            # Every other message becomes a new queued run on the thread.
            # taskId carries no further meaning here — v1.0 defines none for
            # a task that isn't asking, and funduq doesn't invent one.
            # Asking to join a turn already in flight is a different verb and
            # an explicit one: the interjection extension
            # (ADDRESSED_RUN_METADATA_KEY, copied into forwardedProps below).
            # Intent is declared by the caller, never inferred from the
            # target's state.
            task_id = params.get("taskId")
            addressed = await repo.get_run(session, task_id) if task_id else None
            if (
                addressed is not None
                and addressed.thread_id == thread_id
                and addressed.status == "input-required"
                and addressed.head_key is not None
            ):
                # A chained ask names its authorities; the resolution must be
                # signed by one of them. Raises InvalidResolution otherwise.
                verify_resolution(
                    metadata.get("resolution") or {},
                    task_id,
                    {addressed.head_key, agent.provider_key},
                    metadata.get("delegation"),
                )
            reopened = (
                addressed is not None
                and addressed.thread_id == thread_id
                and addressed.status == "input-required"
                and await repo.reopen_run(
                    session,
                    task_id,
                    run_input,
                    metadata=metadata,
                    expected_status="input-required",
                )
            )
            if reopened:
                run_id = task_id
                starting_seq = await repo.get_last_event_seq(session, run_id)
            else:
                await repo.ensure_queue_room(
                    session, thread_id, funduq.settings.thread_queue_limit
                )
                created = await repo.create_run(
                    session, thread_id, agent, "a2a", run_input,
                    metadata=metadata, head_key=head_key,
                )
                run_id = created["run_id"]
                starting_seq = 0

            inbound = InboundRun(
                agent=agent,
                messages=messages,
                metadata=metadata,
                head_key=head_key,
                actor_chain=actor_chain,
                kyok=kyok,
                # The extension convention puts the key in the Message's own
                # metadata map; the request-level map is accepted too.
                addressed_run_id=(
                    (params.get("message", {}).get("metadata") or {}).get(
                        ADDRESSED_RUN_METADATA_KEY
                    )
                    or metadata.get(ADDRESSED_RUN_METADATA_KEY)
                ),
                protocol="a2a",
            )
            live = await dispatch(
                funduq, session, inbound,
                thread_id=thread_id, run_id=run_id, starting_seq=starting_seq,
            )

        return run_id, thread_id, live


def _skills(raw_skills: list[dict[str, Any]]) -> list[pb.AgentSkill]:
    skills = []
    for raw in raw_skills:
        try:
            skills.append(ParseDict(raw, pb.AgentSkill(), ignore_unknown_fields=True))
        except ParseError:
            logger.warning("agent card: skipping a skill that is not an A2A AgentSkill: %r", raw)
    return skills


async def _context_of_task(session, task_id: str | None) -> str | None:
    """The thread a named task belongs to, raising A2A's own `TaskNotFoundError` for an unknown
    one — an id the caller sent that names nothing is A2A's error to report, and reporting it
    in A2A's vocabulary is what lets the transport map it without a table of funduq's own."""
    if not task_id:
        return None
    run = await repo.get_run(session, task_id)
    if run is None:
        raise TaskNotFoundError(f"no task '{task_id}'")
    return run.thread_id


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
    """Lifts the fields `_start_run` addresses by name out of the A2A message they live on.

    `contextId`, `taskId` and `referenceTaskIds` are **the message's own
    fields** — A2A v1.0's `SendMessageRequest` carries only `message` and
    `metadata`, so there is nowhere else for them to be, and reading them
    off anything else would be funduq inventing a second address.
    """
    combined = dict(metadata or {})
    if actor_chain:
        combined["actorChain"] = actor_chain
    return {
        "message": dict(message),
        "contextId": message.get("contextId"),
        "taskId": message.get("taskId"),
        "metadata": combined,
    }
