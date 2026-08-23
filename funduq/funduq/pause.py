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


def outstanding_asks(run_metadata: dict[str, Any]) -> set[str]:
    """Everything a paused run is still waiting on, in one id space.

    A pause has two carriers and they overlap: an approval is announced as a
    tool call *and* named again as an `Interrupt`, so the tool call id is the
    identity wherever there is one. An interrupt with no tool call behind it
    (AG-UI's `reason` is not limited to `tool_call`) falls back to its own id.
    """
    asks = set(run_metadata.get("pendingToolCalls") or [])
    for interrupt in run_metadata.get("interrupts") or []:
        asks.add(interrupt.get("toolCallId") or interrupt.get("id"))
    return {ask for ask in asks if ask}


def answered_asks(
    messages: list[dict[str, Any]],
    resume: list[dict[str, Any]] | None,
    run_metadata: dict[str, Any],
) -> set[str]:
    """The asks an inbound request answers, in the same id space.

    AG-UI answers the two kinds through two channels and they are not
    interchangeable. A deferred call is answered by a tool result in
    `messages`, naming its call directly. An approval is answered by a
    `ResumeEntry` in `resume`, naming the interrupt that wrapped the call —
    and *only* that way: a tool result carrying the approved call's id is
    dropped in silence, the turn stays incomplete, and the run ends
    `RUN_FINISHED`/`success` having done nothing at all. Measured against
    pydantic-ai, which needs a `ToolApproved`/`ToolDenied` for such a call and
    has no way to read one out of a tool result.

    So an ask an interrupt named is not answerable by tool result here, and
    counting one would reopen a run that then quietly did nothing.

    An interrupt's `id` is the provider's to choose (pydantic-ai prefixes
    `int-`, which is nothing the protocol says), so the mapping back to the
    tool call is read off the record rather than derived from the string.
    """
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
