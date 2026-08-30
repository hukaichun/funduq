from __future__ import annotations

from typing import Any

from a2a.types import a2a_pb2 as pb
from ag_ui.core import AssistantMessage, EventType, UserMessage

from funduq.pause import interrupt_outcome_of

_PLACEHOLDER_MESSAGE_ID = "unset"

RUN_STATUS_TO_A2A_STATE = {
    "queued": pb.TaskState.TASK_STATE_SUBMITTED,
    # Submitted, not working: funduq has offered the run to a provider and is waiting for an answer, so nothing is being worked on yet.
    "offering": pb.TaskState.TASK_STATE_SUBMITTED,
    "running": pb.TaskState.TASK_STATE_WORKING,
    "input-required": pb.TaskState.TASK_STATE_INPUT_REQUIRED,
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

OVERFLOW_METADATA_KEY = "agui_event"
OVERFLOW_METADATA_LIST_KEY = "agui_events"

# Set on a task funduq has been asked to cancel and is still relaying.
CANCEL_REQUESTED_METADATA_KEY = "funduq/cancelRequested"


def is_mapped(event: dict[str, Any]) -> bool:
    """True if `event`'s AG-UI type has an A2A representation this module emits."""
    return event.get("type") in MAPPED_EVENT_TYPES


def state_for_run_status(run_status: str):
    """Maps a funduq run status to its A2A `TaskState`."""
    return RUN_STATUS_TO_A2A_STATE.get(run_status, pb.TaskState.TASK_STATE_UNSPECIFIED)


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
    """Converts one inbound A2A `Message` into a one-element list of AG-UI message dicts, reading its text parts under any A2A spec version's part shape (`text`/`kind: text`/ `type: text`) and mapping an agent-authored message to an assistant role, otherwise user."""
    raw_role = str(a2a_message.get("role", "")).upper()
    text = "".join(
        part["text"] for part in a2a_message.get("parts", []) if isinstance(part.get("text"), str)
    )
    message = (
        AssistantMessage(id=_PLACEHOLDER_MESSAGE_ID, content=text)
        if raw_role in ("ROLE_AGENT", "AGENT")
        else UserMessage(id=_PLACEHOLDER_MESSAGE_ID, content=text)
    )
    return [message.model_dump(mode="json", by_alias=True, exclude_none=True)]


def text_delta_of(event: dict[str, Any]) -> tuple[str, str] | None:
    """Returns `(messageId, text)` if `event` is a text-content AG-UI event, else None."""
    if event.get("type") not in TEXT_EVENT_TYPES:
        return None
    return event.get("messageId") or "text", event.get("delta") or event.get("content") or ""


def agui_event_to_a2a_update(
    event: dict[str, Any], task_id: str, context_id: str, *, opened: set[str]
) -> pb.TaskStatusUpdateEvent | pb.TaskArtifactUpdateEvent:
    """Translates one AG-UI run event into the A2A stream event it projects onto: run lifecycle events become status updates (`RUN_STARTED`->working, `RUN_FINISHED`->completed or, when it carries an interrupt outcome, input-required with the interrupts attached, `RUN_ERROR`->failed with the error message attached), text-content events become appending artifact updates keyed by message id, and anything else falls back to a working status update carrying the raw AG-UI event under `metadata.agui_event` so it isn't silently dropped."""
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
                metadata={"interrupts": interrupts},
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
    if metadata:
        update.metadata.update(metadata)
    if agui_event is not None:
        update.metadata.update({OVERFLOW_METADATA_KEY: agui_event})
    return update


def build_task(
    task_id: str,
    context_id: str,
    agent_name: str,
    run_status: str,
    run_events: list[dict[str, Any]],
    *,
    cancel_requested: bool = False,
) -> pb.Task:
    """Builds an A2A `Task` from a run's stored status and event history, merging each message's text-content deltas (in event order) into one artifact per `messageId`, and carrying every unmapped event, in order, under `metadata.agui_events`."""
    merged: dict[str, list[str]] = {}
    overflow: list[dict[str, Any]] = []
    for event in run_events:
        delta = text_delta_of(event)
        if delta is not None:
            artifact_id, text = delta
            merged.setdefault(artifact_id, []).append(text)
        elif not is_mapped(event):
            overflow.append(event)

    task = pb.Task(
        id=task_id,
        context_id=context_id,
        status=pb.TaskStatus(state=state_for_run_status(run_status)),
        artifacts=[
            pb.Artifact(artifact_id=artifact_id, parts=[pb.Part(text="".join(chunks))])
            for artifact_id, chunks in merged.items()
        ],
    )
    if overflow:
        task.metadata.update({OVERFLOW_METADATA_LIST_KEY: overflow})
    pending_cancel = _cancel_metadata(run_status, cancel_requested)
    if pending_cancel:
        task.metadata.update(pending_cancel)
    return task
