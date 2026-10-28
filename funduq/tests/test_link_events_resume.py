"""What a provider can pull back off its own link, after a run paused.

The stream replayed here is not written by hand: `tests/real_deferring_stream.json`
was captured from a live model (Azure / DeepSeek-V4-Flash) driving a pydantic-ai
agent with three tools — one ordinary, one raising `CallDeferred`, one raising
`ApprovalRequired` — through pydantic-ai's own AG-UI adapter. One turn, three
tool calls, three fates. That shape is the whole question: the provider is
stateless between rounds, so whatever it can read back from funduq has to be
enough to resume, and nothing here proves it if the events were invented.
"""

from __future__ import annotations

import json
from pathlib import Path

from ag_ui.core import RunAgentInput, UserMessage

from funduq.pause import interrupts_of, open_asks, unanswered_tool_calls
from funduq.protocols.agui import AGUIAdapter, EventStream

REAL_STREAM = json.loads((Path(__file__).parent / "real_deferring_stream.json").read_text())


class ReplaysARealDeferringTurn:
    """Emits a captured live stream verbatim, rewriting only the ids funduq owns."""

    async def run_stream(self, agent_name: str, run_input):
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        for event in REAL_STREAM:
            event = dict(event)
            if "threadId" in event or "runId" in event:
                event.update(ids)
            yield event


def _tool_calls(events: list[dict]) -> tuple[dict[str, str], dict[str, str], set[str]]:
    """What a provider folds out of a run's events to resume it: each call's name, its arguments, and which calls already have a result."""
    names = {e["toolCallId"]: e["toolCallName"] for e in events if e["type"] == "TOOL_CALL_START"}
    arguments = {call: "" for call in names}
    for e in events:
        if e["type"] == "TOOL_CALL_ARGS":
            arguments[e["toolCallId"]] += e["delta"]
    answered = {e["toolCallId"] for e in events if e["type"] == "TOOL_CALL_RESULT"}
    return names, arguments, answered


def _body(text: str = "Weather, a flight, and a payment.") -> RunAgentInput:
    return RunAgentInput(
        thread_id="t-defer", run_id="caller-said-this", state={},
        messages=[UserMessage(id="m1", role="user", content=text)],
        tools=[], context=[], forwarded_props=None,
    )


async def test_the_link_hands_back_enough_to_resume_a_paused_turn(funduq, serve):
    served = await serve(ReplaysARealDeferringTurn(), "concierge")

    stream = await AGUIAdapter(funduq).run(served.agents["concierge"], _body())
    assert isinstance(stream, EventStream)
    [_ async for _ in stream.events]

    events = await funduq.get_run_events(stream.run_id)
    assert (await funduq.get_run(stream.run_id)).status == "completed"
    assert open_asks(events), "finished asking"

    # The provider knows its run id — the delivered run carries it — and
    # reads the run's events back, the record funduq keeps of what it said.
    announced, arguments, answered = _tool_calls(events)

    assert set(announced.values()) == {"get_weather", "book_flight", "send_money"}, (
        "the assistant turn comes back whole: every tool call the model made, with the "
        "name and arguments a resuming provider has to replay"
    )
    assert len(answered) == 1 and announced[next(iter(answered))] == "get_weather", (
        "and only the call the provider answered itself carries a result — the two it "
        "deferred are still open, which is what makes this a resumable turn rather than "
        "a finished one"
    )
    assert all(json.loads(args) for args in arguments.values()), (
        "the deltas join into parseable JSON"
    )


async def test_the_pull_agrees_with_what_funduq_recorded_as_pending(funduq, serve):
    """Two readings of one fact: the provider folds the events, funduq wrote the
    pause. They must name the same outstanding calls, or one of them is lying."""
    served = await serve(ReplaysARealDeferringTurn(), "concierge")

    stream = await AGUIAdapter(funduq).run(served.agents["concierge"], _body())
    [_ async for _ in stream.events]

    events = await funduq.get_run_events(stream.run_id)
    announced, _, answered = _tool_calls(events)
    outstanding = [c for c in announced if c not in answered]

    assert unanswered_tool_calls(events) == outstanding
    assert len(interrupts_of(events)) == 1, "the approval, which AG-UI does name"
