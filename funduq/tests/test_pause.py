from __future__ import annotations

from funduq.pause import interrupt_outcome_of, unanswered_tool_calls


def test_interrupt_outcome_of_extracts_interrupts_from_a_run_finished_event():
    event = {
        "type": "RUN_FINISHED",
        "outcome": {"type": "interrupt", "interrupts": [{"id": "int_1", "reason": "tool_call"}]},
    }
    assert interrupt_outcome_of(event) == [{"id": "int_1", "reason": "tool_call"}]


def test_interrupt_outcome_of_is_none_for_a_plain_success_finish():
    assert interrupt_outcome_of({"type": "RUN_FINISHED", "outcome": {"type": "success"}}) is None
    assert interrupt_outcome_of({"type": "RUN_FINISHED"}) is None


def test_interrupt_outcome_of_is_none_for_non_run_finished_events():
    assert interrupt_outcome_of({"type": "TEXT_MESSAGE_START"}) is None
    assert interrupt_outcome_of({"type": "CUSTOM", "name": "anything"}) is None


def test_unanswered_tool_calls_finds_a_call_that_never_got_a_result():
    events = [
        {"type": "TOOL_CALL_START", "toolCallId": "c1", "toolCallName": "get_weather"},
        {"type": "TOOL_CALL_START", "toolCallId": "c2", "toolCallName": "book_flight"},
        {"type": "TOOL_CALL_RESULT", "toolCallId": "c1", "content": "28C"},
        {"type": "RUN_FINISHED", "outcome": {"type": "success"}},
    ]
    assert unanswered_tool_calls(events) == ["c2"]


def test_unanswered_tool_calls_keeps_announcement_order():
    events = [
        {"type": "TOOL_CALL_START", "toolCallId": "c1"},
        {"type": "TOOL_CALL_START", "toolCallId": "c2"},
        {"type": "TOOL_CALL_START", "toolCallId": "c3"},
        {"type": "TOOL_CALL_RESULT", "toolCallId": "c2"},
    ]
    assert unanswered_tool_calls(events) == ["c1", "c3"]


def test_unanswered_tool_calls_is_empty_when_every_call_was_answered():
    events = [
        {"type": "TOOL_CALL_START", "toolCallId": "c1"},
        {"type": "TOOL_CALL_RESULT", "toolCallId": "c1", "content": "boom"},
        {"type": "RUN_ERROR", "message": "boom"},
    ]
    # A tool that raised still carries a result: the error IS the result, sent
    # back to the model. Measured against pydantic-ai — a raising tool and an
    # exhausted `ModelRetry` both leave `dangling` empty.
    assert unanswered_tool_calls(events) == []


def test_unanswered_tool_calls_ignores_a_result_for_a_call_it_never_saw():
    # A resumed round carries the deferred call's `TOOL_CALL_RESULT` without
    # re-announcing it, so results outnumbering starts is the normal shape.
    assert unanswered_tool_calls([{"type": "TOOL_CALL_RESULT", "toolCallId": "c9"}]) == []
