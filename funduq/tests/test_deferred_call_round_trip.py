"""The whole chain, on one run id: the agent defers a tool call, funduq parks
the run, the caller sends the result back, the same run continues.

Round one replays `tests/real_deferring_stream.json` — a live model's actual
output, one turn with three tool calls the agent resolved three different ways.
Round two is scripted, because what it must prove is not what a model says but
what the provider *received*: the tool result, on the input funduq handed it.
"""

from __future__ import annotations

import json
from pathlib import Path

from ag_ui.core import ResumeEntry, RunAgentInput, ToolMessage, UserMessage

from funduq.protocols.agui import AGUIAdapter, EventStream, ThreadSnapshot

REAL_STREAM = json.loads((Path(__file__).parent / "real_deferring_stream.json").read_text())


class DefersThenFinishes:
    """Replays a real deferring turn, then — once the results come back —
    finishes. Records the input of every round it was handed."""

    def __init__(self) -> None:
        self.rounds: list[dict] = []

    async def run_stream(self, agent_name: str, run_input):
        self.rounds.append(
            {
                "messages": [
                    m.model_dump(mode="json", by_alias=True, exclude_none=True)
                    for m in (run_input.messages or [])
                ],
                "resume": run_input.resume,
            }
        )
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        if len(self.rounds) == 1:
            for event in REAL_STREAM:
                event = dict(event)
                if "threadId" in event or "runId" in event:
                    event.update(ids)
                yield event
            return
        yield {"type": "RUN_STARTED", **ids}
        yield {"type": "TEXT_MESSAGE_START", "messageId": "done", "role": "assistant"}
        yield {"type": "TEXT_MESSAGE_CONTENT", "messageId": "done", "delta": "All three are handled."}
        yield {"type": "TEXT_MESSAGE_END", "messageId": "done"}
        yield {"type": "RUN_FINISHED", **ids}


def _utterance(thread_id: str = "t-chain") -> RunAgentInput:
    return RunAgentInput(
        thread_id=thread_id, run_id="caller-said-this", state={},
        messages=[UserMessage(id="m1", role="user",
                              content="Weather, a flight, and a payment.")],
        tools=[], context=[], forwarded_props=None,
    )


def _tool_results(thread_id: str, answers: dict[str, str], resume=None) -> RunAgentInput:
    return RunAgentInput(
        thread_id=thread_id, run_id="caller-said-this-too", state={},
        messages=[
            ToolMessage(id=f"r-{i}", role="tool", tool_call_id=call_id, content=content)
            for i, (call_id, content) in enumerate(answers.items())
        ],
        tools=[], context=[], forwarded_props=None, resume=resume,
    )


def _answers(paused) -> tuple[dict[str, str], list[ResumeEntry]]:
    """One answer per ask, each through the carrier its kind requires: the
    deferred call by tool result, the approval by `ResumeEntry`."""
    by_interrupt = {i["toolCallId"]: i["id"] for i in paused.metadata["interrupts"]}
    tool_results, resume = {}, []
    for call_id in paused.metadata["pendingToolCalls"]:
        if call_id in by_interrupt:
            resume.append(ResumeEntry(interrupt_id=by_interrupt[call_id],
                                      status="resolved", payload={"approved": True}))
        else:
            tool_results[call_id] = "Booked JL802, seat 14A"
    return tool_results, resume


async def _pause(funduq, serve):
    provider = DefersThenFinishes()
    served = await serve(provider, "concierge")
    agent = served.agents["concierge"]
    first = await AGUIAdapter(funduq).run(agent, _utterance())
    assert isinstance(first, EventStream)
    [_ async for _ in first.events]
    paused = await funduq.get_run(first.run_id)
    assert paused.status == "input-required"
    return provider, served, agent, first, paused


async def test_a_tool_result_lands_on_the_run_that_asked_for_it(funduq, serve):
    provider, served, agent, first, paused = await _pause(funduq, serve)
    tool_results, resume = _answers(paused)
    assert len(tool_results) == 1 and len(resume) == 1, (
        "one deferred call and one awaiting approval, each answered its own way"
    )

    second = await AGUIAdapter(funduq).run(
        agent, _tool_results(first.thread_id, tool_results, resume=resume)
    )

    assert isinstance(second, EventStream)
    assert second.run_id == first.run_id, (
        "a deferred call's result continues the run that asked; a new id would make "
        "the answer a different conversation turn than the question"
    )
    [_ async for _ in second.events]
    assert (await funduq.get_run(first.run_id)).status == "completed"


async def test_the_provider_is_handed_the_results_it_was_waiting_on(funduq, serve):
    provider, served, agent, first, paused = await _pause(funduq, serve)
    tool_results, resume = _answers(paused)

    second = await AGUIAdapter(funduq).run(
        agent, _tool_results(first.thread_id, tool_results, resume=resume)
    )
    [_ async for _ in second.events]

    assert len(provider.rounds) == 2, "the same provider ran both rounds"
    handed = {
        m["toolCallId"]: m["content"]
        for m in provider.rounds[1]["messages"]
        if m.get("role") == "tool"
    }
    assert handed == tool_results, "the deferred call's result, on the messages"
    assert [r.interrupt_id for r in provider.rounds[1]["resume"]] == [
        r.interrupt_id for r in resume
    ], "and the approval, on `resume`, because a tool result cannot carry one"


async def test_a_tool_result_for_nothing_pending_is_an_utterance(funduq, serve):
    """Addressing that lands on no ask is honestly an utterance — the same rule
    the A2A lane already follows for a message whose `taskId` names no pending
    task."""
    provider, served, agent, first, paused = await _pause(funduq, serve)

    stray = await AGUIAdapter(funduq).run(
        agent, _tool_results(first.thread_id, {"call-nobody-made": "here you go"})
    )

    assert isinstance(stray, EventStream)
    assert stray.run_id != first.run_id, "it opens its own run"
    assert (await funduq.get_run(first.run_id)).status == "input-required", (
        "and the real ask is still waiting"
    )


async def test_a_partial_answer_leaves_the_ask_standing(funduq, serve):
    """A provider cannot take a step with one of two results in hand — the model
    it is driving needs one per call in the turn. So half an answer is not an
    answer: it enters as an utterance and the ask survives, rather than
    reopening a run the provider would only fail."""
    provider, served, agent, first, paused = await _pause(funduq, serve)
    pending = paused.metadata["pendingToolCalls"]
    tool_results, _resume = _answers(paused)

    half = await AGUIAdapter(funduq).run(
        agent, _tool_results(first.thread_id, tool_results)
    )

    assert isinstance(half, EventStream)
    assert half.run_id != first.run_id
    assert (await funduq.get_run(first.run_id)).status == "input-required"
    assert (await funduq.get_run(first.run_id)).metadata["pendingToolCalls"] == pending


async def test_after_the_round_trip_the_link_holds_the_whole_resumable_turn(funduq, serve):
    """The provider is handed only what is new; everything else it pulls. This
    is the join: `dispatch` writes the inbound messages to the thread before it
    builds the provider's input, so by the time the resumed round runs, the
    link holds the assistant turn *and* every result — the complete set a
    stateless provider needs to take its next step."""
    provider, served, agent, first, paused = await _pause(funduq, serve)
    pending = paused.metadata["pendingToolCalls"]
    tool_results, resume = _answers(paused)

    second = await AGUIAdapter(funduq).run(
        agent, _tool_results(first.thread_id, tool_results, resume=resume)
    )
    [_ async for _ in second.events]

    handed = {m["toolCallId"] for m in provider.rounds[1]["messages"] if m.get("role") == "tool"}
    assert handed == set(tool_results), "handed: only the new results"

    pulled = [
        m.model_dump(mode="json", by_alias=True, exclude_none=True)
        for m in await served.link.thread_messages(first.thread_id)
    ]
    announced = {c["id"] for m in pulled for c in (m.get("toolCalls") or [])}
    answered = {m["toolCallId"] for m in pulled if m.get("role") == "tool"}
    assert len(announced) == 3, "pulled: the assistant turn, whole"
    assert announced - answered == {p for p in pending if p not in tool_results}, (
        "pulled: a result for every call except the approved one, whose answer rides "
        "on `resume` and is not a message"
    )


async def test_a_tool_result_cannot_answer_an_approval(funduq, serve):
    """An approved call's result has to arrive as a `ResumeEntry`. Handed the
    same id as a tool result, pydantic-ai drops it without a word: the turn
    stays incomplete and the run ends `RUN_FINISHED`/`success` having executed
    nothing. Measured. So funduq does not count one — reopening the run on it
    would trade a waiting run for a silently empty one."""
    provider, served, agent, first, paused = await _pause(funduq, serve)
    pending = paused.metadata["pendingToolCalls"]

    wrong_carrier = await AGUIAdapter(funduq).run(
        agent,
        _tool_results(first.thread_id, {call_id: "done, trust me" for call_id in pending}),
    )

    assert isinstance(wrong_carrier, EventStream)
    assert wrong_carrier.run_id != first.run_id
    assert (await funduq.get_run(first.run_id)).status == "input-required", (
        "the approval is still outstanding, because nothing answered it"
    )
