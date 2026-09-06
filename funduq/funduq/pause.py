"""What a run's events say about where its thread stands. A run that finished asking — an interrupt outcome, a tool call nobody answered — is `completed`, as AG-UI says; that it left the thread waiting is read here, from its own events, never stored."""

from typing import Any

from ag_ui.core import EventType


def interrupt_outcome_of(event: dict) -> list[dict[str, Any]] | None:
    """Returns the list of interrupts (possibly empty) if `event` is a RUN_FINISHED with an interrupt outcome, else None — including for a RUN_FINISHED with a plain success outcome or no outcome at all."""
    if event.get("type") != EventType.RUN_FINISHED:
        return None
    outcome = event.get("outcome")
    if not isinstance(outcome, dict) or outcome.get("type") != "interrupt":
        return None
    return outcome.get("interrupts") or []


def unanswered_tool_calls(events: list[dict[str, Any]]) -> list[str]:
    """The tool calls announced in `events` that never got a result, in the order they were announced."""
    announced: list[str] = []
    answered: set[str] = set()
    for event in events:
        etype = event.get("type")
        if etype == EventType.TOOL_CALL_START:
            announced.append(event["toolCallId"])
        elif etype == EventType.TOOL_CALL_RESULT:
            answered.add(event["toolCallId"])
    return [tool_call_id for tool_call_id in announced if tool_call_id not in answered]


def interrupts_of(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The interrupts the run finished on — the last RUN_FINISHED's interrupt outcome — or `[]`."""
    for event in reversed(events):
        if event.get("type") == EventType.RUN_FINISHED:
            return interrupt_outcome_of(event) or []
    return []


def finished(events: list[dict[str, Any]]) -> bool:
    return any(event.get("type") == EventType.RUN_FINISHED for event in events)


def open_asks(events: list[dict[str, Any]]) -> set[str]:
    """Everything a finished run left waiting on, in one id space: its interrupts (by tool call id where they have one) and its unanswered tool calls. Empty for a run that is not finished, or finished with nothing open."""
    if not finished(events):
        return set()
    asks = set(unanswered_tool_calls(events))
    for interrupt in interrupts_of(events):
        asks.add(interrupt.get("toolCallId") or interrupt.get("id"))
    return {ask for ask in asks if ask}


def answered_asks(
    messages: list[dict[str, Any]],
    resume: list[dict[str, Any]] | None,
    events: list[dict[str, Any]],
) -> set[str]:
    """The asks an inbound request answers, in the same id space as `open_asks`."""
    tool_call_of = {
        interrupt["id"]: interrupt.get("toolCallId") or interrupt["id"]
        for interrupt in interrupts_of(events)
        if interrupt.get("id")
    }
    only_by_resume = set(tool_call_of.values())
    answered = {
        message["toolCallId"]
        for message in messages
        if message.get("role") == "tool"
        and message.get("toolCallId")
        and message["toolCallId"] not in only_by_resume
    }
    for entry in resume or []:
        interrupt_id = entry.get("interruptId")
        if interrupt_id in tool_call_of:
            answered.add(tool_call_of[interrupt_id])
    return answered


def failure_reason_of(events: list[dict[str, Any]]) -> str | None:
    """Why the run failed, read from its terminal RUN_ERROR: the machine `code` if it carries one, else its `message`. None if no RUN_ERROR was recorded."""
    for event in reversed(events):
        if event.get("type") == EventType.RUN_ERROR:
            return event.get("code") or event.get("message")
    return None
