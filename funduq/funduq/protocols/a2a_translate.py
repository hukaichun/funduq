from __future__ import annotations

from datetime import datetime
from typing import Any

from a2a.types import a2a_pb2 as pb
from a2a.utils.errors import ContentTypeNotSupportedError
from google.protobuf.json_format import MessageToDict
from ag_ui.core import AssistantMessage, EventType, UserMessage

from funduq.pause import interrupt_outcome_of, open_asks
from funduq.props import OBSERVED_METADATA_KEY

_PLACEHOLDER_MESSAGE_ID = "unset"

RUN_STATUS_TO_A2A_STATE = {
    "queued": pb.TaskState.TASK_STATE_SUBMITTED,
    # Submitted, not working: funduq has offered the run to a provider and is waiting for an answer, so nothing is being worked on yet.
    "offering": pb.TaskState.TASK_STATE_SUBMITTED,
    "running": pb.TaskState.TASK_STATE_WORKING,
    # Working, plus a metadata marker (`CANCEL_REQUESTED_METADATA_KEY`).
    "cancelling": pb.TaskState.TASK_STATE_WORKING,
    "completed": pb.TaskState.TASK_STATE_COMPLETED,
    "failed": pb.TaskState.TASK_STATE_FAILED,
    "cancelled": pb.TaskState.TASK_STATE_CANCELED,
}

TERMINAL_STATES = frozenset(
    {pb.TaskState.TASK_STATE_COMPLETED, pb.TaskState.TASK_STATE_FAILED, pb.TaskState.TASK_STATE_CANCELED}
)

# The AG-UI event types this module projects onto A2A's own vocabulary.
LIFECYCLE_EVENT_TYPES = frozenset(
    {EventType.RUN_STARTED, EventType.RUN_FINISHED, EventType.RUN_ERROR}
)
TEXT_EVENT_TYPES = frozenset({EventType.TEXT_MESSAGE_CONTENT, EventType.TEXT_MESSAGE_CHUNK})
MAPPED_EVENT_TYPES = LIFECYCLE_EVENT_TYPES | TEXT_EVENT_TYPES

# Everything funduq itself writes into an A2A task's or status update's `metadata` sits under this one key (`OBSERVED_METADATA_KEY`, the same key as on a run's record and on `forwardedProps`). The keys below are its fields.
OVERFLOW_METADATA_KEY = "agui_event"
OVERFLOW_METADATA_LIST_KEY = "agui_events"
INTERRUPTS_METADATA_KEY = "interrupts"
# Set on a task funduq has been asked to cancel and is still relaying.
CANCEL_REQUESTED_METADATA_KEY = "cancelRequested"


def funduq_metadata_of(message: Any) -> dict[str, Any]:
    """What funduq wrote under an A2A task's or status update's `metadata`, as plain data, or `{}`."""
    return MessageToDict(message).get("metadata", {}).get(OBSERVED_METADATA_KEY, {})


def is_mapped(event: dict[str, Any]) -> bool:
    """True if `event`'s AG-UI type has an A2A representation this module emits."""
    return event.get("type") in MAPPED_EVENT_TYPES


def state_for_run_status(run_status: str):
    """Maps a funduq run status to its A2A `TaskState`, status alone: use `task_state_of` when the run's events are at hand, because a completed run that left asks open is a task waiting for input."""
    return RUN_STATUS_TO_A2A_STATE.get(run_status, pb.TaskState.TASK_STATE_UNSPECIFIED)


def task_state_of(run_status: str, run_events: list[dict[str, Any]], cancel_requested: bool = False):
    """The A2A state of a task whose tail run is in `run_status` with `run_events`: a completed run with open asks is `INPUT_REQUIRED` — or `CANCELED` once someone closed it — everything else is the status's own state."""
    if run_status == "completed" and open_asks(run_events):
        return pb.TaskState.TASK_STATE_CANCELED if cancel_requested else pb.TaskState.TASK_STATE_INPUT_REQUIRED
    return state_for_run_status(run_status)


def status_update_for_run_status(
    task_id: str, context_id: str, run_status: str
) -> pb.TaskStatusUpdateEvent:
    """Builds a `TaskStatusUpdateEvent` reflecting a run's persisted status, carrying the pending-cancel marker when there is one and nothing else."""
    return _status_update(
        task_id,
        context_id,
        state_for_run_status(run_status),
        metadata=_cancel_metadata(run_status),
    )


def _cancel_metadata(run_status: str, cancel_requested: bool = False) -> dict[str, Any] | None:
    """`{CANCEL_REQUESTED_METADATA_KEY: True}` when funduq has been asked to cancel this run and has not seen it end, else None."""
    if run_status == "cancelling" or cancel_requested:
        return {CANCEL_REQUESTED_METADATA_KEY: True}
    return None


def a2a_message_to_agui_messages(a2a_message: dict[str, Any]) -> list[dict[str, Any]]:
    """Converts one inbound A2A `Message` into a one-element list of AG-UI message dicts, reading its text parts under any A2A spec version's part shape (`text`/`kind: text`/ `type: text`) and refusing any other kind with `ContentTypeNotSupportedError`, mapping an agent-authored message to an assistant role (otherwise user), and carrying the message's own `metadata` across as the AG-UI message's `metadata`."""
    raw_role = str(a2a_message.get("role", "")).upper()
    parts = a2a_message.get("parts", [])
    # The card accepts text/plain and nothing else (A2A §3.1.1): a part funduq cannot carry is refused, never dropped on the way to the agent.
    unsupported = [part for part in parts if not isinstance(part.get("text"), str)]
    if unsupported:
        kinds = sorted({str(part.get("mediaType") or next((k for k in ("data", "url", "raw", "file") if k in part), part.get("kind") or part.get("type") or "unknown")) for part in unsupported})
        raise ContentTypeNotSupportedError(
            f"this agent accepts text/plain parts only; the message carries {', '.join(str(k) for k in kinds)} part(s)"
        )
    text = "".join(part["text"] for part in parts)
    message = (
        AssistantMessage(id=_PLACEHOLDER_MESSAGE_ID, content=text)
        if raw_role in ("ROLE_AGENT", "AGENT")
        else UserMessage(id=_PLACEHOLDER_MESSAGE_ID, content=text)
    )
    dumped = message.model_dump(mode="json", by_alias=True, exclude_none=True)
    # Message-level stays message-level: A2A's `Message.metadata` becomes the AG-UI message's `metadata` (the field AG-UI's newer revisions define; the model keeps it as an extra today). funduq reads nothing from it.
    if isinstance(a2a_message.get("metadata"), dict) and a2a_message["metadata"]:
        dumped["metadata"] = a2a_message["metadata"]
    return [dumped]


def text_delta_of(event: dict[str, Any]) -> tuple[str, str] | None:
    """Returns `(messageId, text)` if `event` is a text-content AG-UI event, else None."""
    if event.get("type") not in TEXT_EVENT_TYPES:
        return None
    return event.get("messageId") or "text", event.get("delta") or event.get("content") or ""


def agui_event_to_a2a_update(
    event: dict[str, Any], task_id: str, context_id: str, *, opened: set[str]
) -> pb.TaskStatusUpdateEvent | pb.TaskArtifactUpdateEvent:
    """Translates one AG-UI run event into the A2A stream event it projects onto: run lifecycle events become status updates (`RUN_STARTED`->working, `RUN_FINISHED`->completed or, when it carries an interrupt outcome, input-required with the interrupts attached, `RUN_ERROR`->failed with the error message attached), text-content events become appending artifact updates keyed by message id, and anything else falls back to a working status update carrying the raw AG-UI event under `metadata.funduq.agui_event` so it isn't silently dropped."""
    event_type = event.get("type")

    if event_type == EventType.RUN_STARTED:
        return _status_update(task_id, context_id, pb.TaskState.TASK_STATE_WORKING)

    if event_type == EventType.RUN_FINISHED:
        # A run that finished on an interrupt is asking, not done.
        interrupts = interrupt_outcome_of(event)
        if interrupts is not None:
            return _status_update(
                task_id,
                context_id,
                pb.TaskState.TASK_STATE_INPUT_REQUIRED,
                metadata={INTERRUPTS_METADATA_KEY: interrupts},
            )
        return _status_update(task_id, context_id, pb.TaskState.TASK_STATE_COMPLETED)

    if event_type == EventType.RUN_ERROR:
        return _status_update(
            task_id, context_id, pb.TaskState.TASK_STATE_FAILED, message=event.get("message")
        )

    delta = text_delta_of(event)
    if delta is not None:
        artifact_id, text = delta
        already_open = artifact_id in opened
        opened.add(artifact_id)
        return pb.TaskArtifactUpdateEvent(
            task_id=task_id,
            context_id=context_id,
            artifact=pb.Artifact(artifact_id=artifact_id, parts=[pb.Part(text=text)]),
            append=already_open,
        )

    return _status_update(task_id, context_id, pb.TaskState.TASK_STATE_WORKING, agui_event=event)


def _status_update(
    task_id: str,
    context_id: str,
    state,
    *,
    message: Any = None,
    agui_event: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> pb.TaskStatusUpdateEvent:
    status = pb.TaskStatus(state=state)
    if message is not None:
        status.message.CopyFrom(
            pb.Message(
                message_id=f"{task_id}-error",
                role=pb.Role.ROLE_AGENT,
                parts=[pb.Part(text=str(message))],
            )
        )
    update = pb.TaskStatusUpdateEvent(task_id=task_id, context_id=context_id, status=status)
    ours: dict[str, Any] = dict(metadata or {})
    if agui_event is not None:
        ours[OVERFLOW_METADATA_KEY] = agui_event
    if ours:
        update.metadata.update({OBSERVED_METADATA_KEY: ours})
    return update


def history_of(
    thread_messages: list[dict[str, Any]], context_id: str, *, limit: int | None = None
) -> list[pb.Message]:
    """The Task's `history`: each stored user/assistant thread message becomes one A2A `Message` — the reverse of `a2a_message_to_agui_messages`. Other roles are funduq-internal machinery, not the conversation, and stay out. `limit` keeps the last N after that filter — `0` keeps none, which is what §3.2.4 says an explicit `historyLength: 0` asks for, and only an absent field (`None`) keeps all."""
    history = [
        pb.Message(
            message_id=str(message.get("id") or ""),
            context_id=context_id,
            role=pb.Role.ROLE_AGENT if message.get("role") == "assistant" else pb.Role.ROLE_USER,
            parts=[pb.Part(text=str(message.get("content") or ""))],
        )
        for message in thread_messages
        if message.get("role") in ("user", "assistant")
    ]
    if limit is None:
        return history
    return history[-limit:] if limit else []


def build_task(
    task_id: str,
    context_id: str,
    agent_name: str,
    run_status: str,
    run_events: list[dict[str, Any]],
    *,
    thread_messages: list[dict[str, Any]] | None = None,
    history_length: int | None = None,
    cancel_requested: bool = False,
    tail_events: list[dict[str, Any]] | None = None,
    status_at: "datetime | None" = None,
) -> pb.Task:
    """Builds an A2A `Task` from a task's tail status and event history (`tail_events`, when the task is a lineage and `run_events` spans it), merging each message's text-content deltas (in event order) into one artifact per `messageId`, filling `history` from the thread's stored messages, and carrying every unmapped event, in order, under `metadata.funduq.agui_events`."""
    merged: dict[str, list[str]] = {}
    overflow: list[dict[str, Any]] = []
    for event in run_events:
        delta = text_delta_of(event)
        if delta is not None:
            artifact_id, text = delta
            merged.setdefault(artifact_id, []).append(text)
        elif not is_mapped(event):
            overflow.append(event)

    status = pb.TaskStatus(
        # The task's state is its tail run's; `run_events` may span the whole lineage for the artifacts.
        state=task_state_of(run_status, run_events if tail_events is None else tail_events, cancel_requested)
    )
    if status_at is not None:
        status.timestamp.FromDatetime(status_at)
    task = pb.Task(
        id=task_id,
        context_id=context_id,
        status=status,
        history=history_of(thread_messages or [], context_id, limit=history_length),
        artifacts=[
            pb.Artifact(artifact_id=artifact_id, parts=[pb.Part(text="".join(chunks))])
            for artifact_id, chunks in merged.items()
        ],
    )
    ours: dict[str, Any] = {}
    if overflow:
        ours[OVERFLOW_METADATA_LIST_KEY] = overflow
    ours.update(_cancel_metadata(run_status, cancel_requested) or {})
    if ours:
        task.metadata.update({OBSERVED_METADATA_KEY: ours})
    return task
