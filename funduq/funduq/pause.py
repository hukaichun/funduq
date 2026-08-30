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


def outstanding_asks(run_metadata: dict[str, Any]) -> set[str]:
    """Everything a paused run is still waiting on, in one id space."""
    asks = set(run_metadata.get("pendingToolCalls") or [])
    for interrupt in run_metadata.get("interrupts") or []:
        asks.add(interrupt.get("toolCallId") or interrupt.get("id"))
    return {ask for ask in asks if ask}


def answered_asks(
    messages: list[dict[str, Any]],
    resume: list[dict[str, Any]] | None,
    run_metadata: dict[str, Any],
) -> set[str]:
    """The asks an inbound request answers, in the same id space."""
    tool_call_of = {
        interrupt["id"]: interrupt.get("toolCallId") or interrupt["id"]
        for interrupt in run_metadata.get("interrupts") or []
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
