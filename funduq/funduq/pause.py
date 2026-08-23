from typing import Any

from ag_ui.core import EventType


def interrupt_outcome_of(event: dict) -> list[dict[str, Any]] | None:
    """Returns the list of interrupts (possibly empty) if `event` is a
    RUN_FINISHED with an interrupt outcome, else None — including for a
    RUN_FINISHED with a plain success outcome or no outcome at all."""
    if event.get("type") != EventType.RUN_FINISHED:
        return None
    outcome = event.get("outcome")
    if not isinstance(outcome, dict) or outcome.get("type") != "interrupt":
        return None
    return outcome.get("interrupts") or []


def unanswered_tool_calls(events: list[dict[str, Any]]) -> list[str]:
    """The tool calls announced in `events` that never got a result, in the
    order they were announced.

    AG-UI has no "paused" event: a provider ends its stream with
    `RUN_FINISHED` whether the agent's loop is done or waiting, and the
    `outcome` field only distinguishes the waiting it knows how to name.
    `Interrupt` covers a call awaiting **approval**; a call the provider
    deferred for someone else to execute gets no interrupt at all and rides
    out under `outcome: success`, indistinguishable from a run that really
    finished. Measured against pydantic-ai's AG-UI adapter, whose
    `_build_outcome` reads `DeferredToolRequests.approvals` and nothing else.

    So the unanswered call is the only thing left to read, and it is a fact
    in funduq's own event log rather than a guess about the provider: a call
    that ran carries a `TOOL_CALL_RESULT`, including one whose tool raised
    (the error is the result, sent back to the model) and one abandoned after
    `ModelRetry` gave up. Nothing else in the stream is being interpreted.
    """
    announced: list[str] = []
    answered: set[str] = set()
    for event in events:
        etype = event.get("type")
        if etype == EventType.TOOL_CALL_START:
            announced.append(event["toolCallId"])
        elif etype == EventType.TOOL_CALL_RESULT:
            answered.add(event["toolCallId"])
    return [tool_call_id for tool_call_id in announced if tool_call_id not in answered]
