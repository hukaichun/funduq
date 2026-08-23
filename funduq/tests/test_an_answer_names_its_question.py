"""An answer names the questions it answers, and funduq keeps what it named.

The signature over a resolution used to cover the run id and a clock. Neither
says anything about *what was answered*, and three consequences followed, each
measured before this file existed:

- one collected signature answered a second, different ask on the same run,
  because a run keeps its id across rounds;
- answering one of two questions reopened the run and dropped the other in
  silence, since a reopen ends the whole pause;
- `verify_resolution`'s return value — the effective authority — was computed
  and thrown away at both doors, so the design record's claim that "who
  resolved, under whose authority, is recorded" was simply false.

Signing the answers fixes the first two by construction. The third needed a
place to put the answer: the thread's own message record, written in the same
transaction as the status guard that picked this answer over any other.
"""

from __future__ import annotations

import pytest
from ag_ui.core import RunAgentInput, UserMessage
from ag_ui.core.types import ResumeEntry

from funduq import repo
from funduq.identity import InvalidResolution
from funduq.props import RESOLVED_EVENT_NAME, RESOLVED_METADATA_KEY
from funduq.protocols.agui import AGUIAdapter


class TwoQuestions:
    """Asks two questions on its first round, then finishes."""

    def __init__(self) -> None:
        self.rounds: list = []

    async def run_stream(self, agent_name: str, run_input):
        self.rounds.append(run_input)
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        if len(self.rounds) == 1:
            yield {
                "type": "RUN_FINISHED",
                **ids,
                "outcome": {
                    "type": "interrupt",
                    "interrupts": [
                        {"id": "int_a", "reason": "tool_call", "message": "approve a?"},
                        {"id": "int_b", "reason": "tool_call", "message": "approve b?"},
                    ],
                },
            }
        else:
            yield {"type": "RUN_FINISHED", **ids}


def _body(thread_id, text, metadata=None, resume=None) -> RunAgentInput:
    return RunAgentInput(
        thread_id=thread_id, run_id="ignored", state={},
        messages=[UserMessage(id="m1", role="user", content=text)],
        tools=[], context=[], forwarded_props={},
        metadata=metadata or {}, resume=resume,
    )


def _entries(answers):
    return [
        ResumeEntry.model_validate({"interruptId": k, "status": v})
        for k, v in answers.items()
    ]


def _signed(identity, run_id, answers):
    return {
        "publicKey": identity.public_key,
        "signature": identity.sign_resolution(run_id, answers),
    }


async def _asked(funduq, serve, new_identity):
    """A chained thread whose run is paused on both questions."""
    head = new_identity()
    provider = TwoQuestions()
    served = await serve(provider, "asker")
    agent = served.agents["asker"]
    adapter = AGUIAdapter(funduq)

    first = await adapter.run(
        agent, _body("t-two", "go", {"actorChain": [head.sign_chain_hop()]})
    )
    [e async for e in first.events]
    return adapter, agent, head, first.thread_id, first.run_id, provider


async def test_answering_one_of_two_questions_is_refused_and_the_ask_survives(
    funduq, serve, new_identity, session
):
    """A reopen ends the whole pause. Accepting half an answer would resume the
    agent with one question dropped and nothing recording that it was — so the
    door refuses, and the ask is still there to answer properly."""
    adapter, agent, head, thread_id, run_id, _ = await _asked(funduq, serve, new_identity)
    half = {"int_a": "resolved"}

    with pytest.raises(InvalidResolution, match="int_a.*int_b"):
        await adapter.run(
            agent,
            _body(
                thread_id, "half an answer",
                {"actorChain": [head.sign_chain_hop()], "resolution": _signed(head, run_id, half)},
                resume=_entries(half),
            ),
        )

    still = await repo.get_run(session, run_id)
    assert still.status == "input-required"
    assert {i["id"] for i in still.metadata["interrupts"]} == {"int_a", "int_b"}


async def test_naming_a_question_the_ask_is_not_asking_is_refused(
    funduq, serve, new_identity
):
    adapter, agent, head, thread_id, run_id, _ = await _asked(funduq, serve, new_identity)
    invented = {"int_a": "resolved", "int_b": "resolved", "int_c": "resolved"}

    with pytest.raises(InvalidResolution):
        await adapter.run(
            agent,
            _body(
                thread_id, "and one more",
                {"actorChain": [head.sign_chain_hop()],
                 "resolution": _signed(head, run_id, invented)},
                resume=_entries(invented),
            ),
        )


async def test_a_signature_must_cover_the_answers_the_request_carries(
    funduq, serve, new_identity
):
    """Signing the run alone let a caller swap the answers under a valid
    signature. The decisions are inside the payload now, so a signature over
    `resolved, resolved` does not stand for `resolved, cancelled`."""
    adapter, agent, head, thread_id, run_id, _ = await _asked(funduq, serve, new_identity)
    signed_for = {"int_a": "resolved", "int_b": "resolved"}
    sent = {"int_a": "resolved", "int_b": "cancelled"}

    with pytest.raises(InvalidResolution, match="signature does not verify"):
        await adapter.run(
            agent,
            _body(
                thread_id, "swapped",
                {"actorChain": [head.sign_chain_hop()],
                 "resolution": _signed(head, run_id, signed_for)},
                resume=_entries(sent),
            ),
        )


async def test_the_answer_and_its_authority_are_recorded_on_the_thread(
    funduq, serve, new_identity, session
):
    """The record, as distinct from the update. It lands on the message the
    answer arrived as, in the transaction that won the reopen."""
    adapter, agent, head, thread_id, run_id, _ = await _asked(funduq, serve, new_identity)
    answers = {"int_a": "resolved", "int_b": "cancelled"}

    resumed = await adapter.run(
        agent,
        _body(
            thread_id, "the answer",
            {"actorChain": [head.sign_chain_hop()], "resolution": _signed(head, run_id, answers)},
            resume=_entries(answers),
        ),
    )
    [e async for e in resumed.events]

    messages = await repo.get_thread_messages(session, thread_id)
    recorded = [m for m in messages if (m.get("metadata") or {}).get(RESOLVED_METADATA_KEY)]
    assert len(recorded) == 1
    stamp = recorded[0]["metadata"][RESOLVED_METADATA_KEY]
    assert stamp["answers"] == answers
    assert stamp["authority"] == head.public_key


async def test_the_resolution_is_announced_on_the_run_it_reopened(
    funduq, serve, new_identity
):
    """Anyone watching the run learns it was answered, and by whom. It is a
    CUSTOM event because AG-UI has no event for this and funduq does not get
    to invent one; where it lands in the stream carries no meaning, which is
    why it needs no ordering guarantee."""
    adapter, agent, head, thread_id, run_id, _ = await _asked(funduq, serve, new_identity)
    answers = {"int_a": "resolved", "int_b": "resolved"}

    resumed = await adapter.run(
        agent,
        _body(
            thread_id, "the answer",
            {"actorChain": [head.sign_chain_hop()], "resolution": _signed(head, run_id, answers)},
            resume=_entries(answers),
        ),
    )
    events = [e async for e in resumed.events]

    announced = [e for e in events if e.get("name") == RESOLVED_EVENT_NAME]
    assert len(announced) == 1, events
    value = announced[0]["value"]
    assert value["runId"] == run_id
    assert value["answers"] == answers
    assert value["authority"] == head.public_key
    assert value["messageId"], "the announcement points at the record"


async def test_a_reopened_run_is_no_longer_asking_the_questions_it_asked(
    funduq, serve, new_identity, session
):
    """The stale ask is what let one signature answer a second, different ask:
    the run kept its id and its old interrupt list across the reopen, so a
    later pause could be answered with the earlier round's proof. A reopen
    retires the questions it ended."""
    adapter, agent, head, thread_id, run_id, provider = await _asked(
        funduq, serve, new_identity
    )
    answers = {"int_a": "resolved", "int_b": "resolved"}

    resumed = await adapter.run(
        agent,
        _body(
            thread_id, "the answer",
            {"actorChain": [head.sign_chain_hop()], "resolution": _signed(head, run_id, answers)},
            resume=_entries(answers),
        ),
    )
    [e async for e in resumed.events]

    reread = await repo.get_run(session, run_id)
    assert reread.status == "completed"
    assert (reread.metadata or {}).get("interrupts") is None
    assert len(provider.rounds) == 2


async def test_the_provider_receives_the_answers_it_asked_for(
    funduq, serve, new_identity
):
    """funduq verifies and records; it does not consume. The entries reach the
    agent as AG-UI's own `resume`, which is the only shape a provider has to
    read whichever door the answer came in by."""
    adapter, agent, head, thread_id, run_id, provider = await _asked(
        funduq, serve, new_identity
    )
    answers = {"int_a": "resolved", "int_b": "cancelled"}

    resumed = await adapter.run(
        agent,
        _body(
            thread_id, "the answer",
            {"actorChain": [head.sign_chain_hop()], "resolution": _signed(head, run_id, answers)},
            resume=_entries(answers),
        ),
    )
    [e async for e in resumed.events]

    second = provider.rounds[1]
    assert {r.interrupt_id: r.status for r in second.resume} == answers


async def test_a_caller_cannot_plant_a_resolution_stamp_of_its_own(
    funduq, serve, new_identity, session
):
    """The stamp is funduq's handwriting, and it says an authority was proved.
    A caller that could write the key onto an ordinary message could put any
    public key it liked behind any answer it liked — measured before the
    strip existed, on a plain utterance carrying `authority: deadbeef`."""
    from tests.conftest import EchoAgent

    served = await serve(EchoAgent(), "plain")
    agent = served.agents["plain"]
    adapter = AGUIAdapter(funduq)

    forged = RunAgentInput(
        thread_id="t-forge", run_id="ignored", state={},
        messages=[
            UserMessage(
                id="m1", role="user", content="hi",
                metadata={RESOLVED_METADATA_KEY: {
                    "answers": {"int_x": "resolved"}, "authority": "deadbeef"
                }},
            )
        ],
        tools=[], context=[], forwarded_props={},
    )
    out = await adapter.run(agent, forged)
    [e async for e in out.events]

    messages = await repo.get_thread_messages(session, out.thread_id)
    assert messages, "the utterance was recorded"
    assert not any(
        (m.get("metadata") or {}).get(RESOLVED_METADATA_KEY) for m in messages
    )
