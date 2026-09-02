"""Who answered a paused run, and who asked one to stop, are in the record.

funduq's whole product is the record. It already checked that a resolution
came from an authority the run answers to — and then discarded the answer,
keeping only the proof as presented.

The case that makes it matter is the provider resolving its own agent's ask.
Nothing stops it and nothing should — it could have taken the step without
pausing at all. But a pause that is raised and then answered reads, to
anyone auditing later, as *an approval was obtained*, and until this landed
the record could not say the approver was the party that asked.
"""

from __future__ import annotations

import pytest

from funduq import repo
from funduq.errors import RunNotCancellable
from funduq.props import OBSERVED_METADATA_KEY
from funduq.protocols.a2a import A2AAdapter

from tests.conftest import EchoAgent
from tests.test_responsibility_chains import AskingAgent, _message, _proof

from a2a.types import a2a_pb2 as pb

COMPLETED = pb.TaskState.TASK_STATE_COMPLETED


class _PausesTwice:
    """Two interrupts on two separate rounds, so an appended record has
    something to append to."""

    def __init__(self) -> None:
        self.rounds: list = []

    async def run_stream(self, agent_name: str, run_input):
        self.rounds.append(run_input)
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        if len(self.rounds) <= 2:
            yield {
                "type": "RUN_FINISHED",
                **ids,
                "outcome": {
                    "type": "interrupt",
                    "interrupts": [{"id": f"int_{len(self.rounds)}", "reason": "question"}],
                },
            }
        else:
            yield {"type": "RUN_FINISHED", **ids}


async def _observed(funduq, run_id: str) -> dict:
    async with funduq.session() as session:
        run = await repo.get_run(session, run_id)
    return (run.metadata or {}).get(OBSERVED_METADATA_KEY) or {}


def _answer(identity, run_id: str, ask_ids: tuple[str, ...] = ("int_1",)) -> dict:
    return {
        "resolution": {
            "publicKey": identity.public_key,
            "signature": identity.sign_resolution(run_id, ask_ids),
        }
    }


async def test_the_head_that_answered_is_named(funduq, serve, new_identity):
    agent = (await serve(AskingAgent(), "asker")).agents["asker"]
    head = new_identity()

    first = await A2AAdapter(funduq).send_task(
        agent, _message("go"), actor_chain=[head.sign_chain_hop()]
    )
    answered = await A2AAdapter(funduq).send_task(
        agent,
        _message("the answer", task_id=first.id),
        actor_chain=[head.sign_chain_hop()],
        metadata=_answer(head, first.id),
    )

    assert answered.status.state == COMPLETED
    assert (await _observed(funduq, first.id))["answeredBy"] == [head.public_key]


async def test_a_provider_answering_its_own_ask_is_visible_as_that(funduq, serve, new_identity):
    """The reason this exists. funduq does not refuse it — the provider holds
    an authority over the run and could have skipped the pause entirely — so
    what is owed is not a refusal but a record that says who it was."""
    served = await serve(AskingAgent(), "self-answerer")
    agent = served.agents["self-answerer"]
    head, keeper = new_identity(), served.identity

    first = await A2AAdapter(funduq).send_task(
        agent, _message("go"), actor_chain=[head.sign_chain_hop()]
    )
    await A2AAdapter(funduq).send_task(
        agent,
        _message("I approve myself", task_id=first.id),
        actor_chain=[keeper.sign_chain_hop()],
        metadata=_answer(keeper, first.id),
    )

    observed = await _observed(funduq, first.id)
    assert observed["answeredBy"] == [keeper.public_key]
    assert observed["answeredBy"] != [head.public_key], (
        "the run's head never answered this, and the record must not read as if it had"
    )


async def test_two_answers_are_two_entries_in_order(funduq, serve, new_identity):
    """A later answer does not supersede an earlier one — they are two acts,
    and a record keeping only the last would say the first never happened."""
    served = await serve(_PausesTwice(), "twice")
    agent = served.agents["twice"]
    head, keeper = new_identity(), served.identity

    first = await A2AAdapter(funduq).send_task(
        agent, _message("go"), actor_chain=[head.sign_chain_hop()]
    )
    await A2AAdapter(funduq).send_task(
        agent,
        _message("one", task_id=first.id),
        actor_chain=[head.sign_chain_hop()],
        metadata=_answer(head, first.id),
    )
    await A2AAdapter(funduq).send_task(
        agent,
        _message("two", task_id=first.id),
        actor_chain=[keeper.sign_chain_hop()],
        metadata=_answer(keeper, first.id, ("int_2",)),
    )

    assert (await _observed(funduq, first.id))["answeredBy"] == [
        head.public_key,
        keeper.public_key,
    ]


async def test_an_old_proof_does_not_answer_a_new_ask(funduq, serve, new_identity):
    """The signature binds the exact asks being answered, so a proof observed
    in flight is worthless against the next pause: the run asks again with
    new ids, and the old signature does not cover them. This is what replaced
    the freshness window for resolve — instance binding instead of a clock."""
    served = await serve(_PausesTwice(), "asks-again")
    agent = served.agents["asks-again"]
    head = new_identity()

    first = await A2AAdapter(funduq).send_task(
        agent, _message("go"), actor_chain=[head.sign_chain_hop()]
    )
    stolen = _answer(head, first.id)  # signs the first ask, "int_1"
    await A2AAdapter(funduq).send_task(
        agent,
        _message("one", task_id=first.id),
        actor_chain=[head.sign_chain_hop()],
        metadata=stolen,
    )

    # The run paused again ("int_2"); replaying the first proof is refused.
    from funduq.identity import InvalidResolution

    with pytest.raises(InvalidResolution):
        await A2AAdapter(funduq).send_task(
            agent,
            _message("replayed", task_id=first.id),
            actor_chain=[head.sign_chain_hop()],
            metadata=stolen,
        )


async def test_an_unbound_run_names_nobody(funduq, serve):
    """The mechanism is opt-in by carrying a chain. A thread that bound no
    authority has none to check against, so there is none to record — and an
    empty entry would be a different claim from no entry."""
    agent = (await serve(AskingAgent(), "open")).agents["open"]

    first = await A2AAdapter(funduq).send_task(agent, _message("go"))
    await A2AAdapter(funduq).send_task(agent, _message("the answer", task_id=first.id))

    assert "answeredBy" not in await _observed(funduq, first.id)


async def test_a_caller_cannot_plant_an_answerer(funduq, serve, new_identity):
    """Everything under funduq's own metadata key is written by funduq. A
    caller-supplied value there is stripped at the doors, which is what lets
    a reader tell funduq's handwriting from a caller's."""
    agent = (await serve(AskingAgent(), "planted")).agents["planted"]
    head, impostor = new_identity(), new_identity()

    first = await A2AAdapter(funduq).send_task(
        agent, _message("go"), actor_chain=[head.sign_chain_hop()]
    )
    await A2AAdapter(funduq).send_task(
        agent,
        _message("the answer", task_id=first.id),
        actor_chain=[head.sign_chain_hop()],
        metadata={
            OBSERVED_METADATA_KEY: {"answeredBy": [impostor.public_key]},
            **_answer(head, first.id),
        },
    )

    assert (await _observed(funduq, first.id))["answeredBy"] == [head.public_key]


async def test_the_authority_that_asked_a_run_to_stop_is_named(funduq, serve, new_identity):
    from tests.test_responsibility_chains import _live_bound_run

    head = new_identity()
    agent, run_id, _keeper = await _live_bound_run(funduq, serve, head)

    await A2AAdapter(funduq).cancel_task(agent, run_id, metadata=_proof(head, run_id))

    assert (await _observed(funduq, run_id))["cancelRequestedBy"] == [head.public_key]


async def test_the_asking_is_recorded_even_when_the_run_cannot_be_stopped(funduq, serve, new_identity):
    """A paused run has no provider working on it, so there is nobody to relay
    a stop to and `cancel_run` refuses. The asking still happened, and funduq
    observed it — so it is written before the refusal, not after.

    Deliberately not asserted by watching the run's status: whether a live
    run has reached `cancelled` yet is a race (it passed on SQLite and failed
    on Postgres), and a record of *acts* is not a record of outcomes anyway.
    A refusal is the one case where the two cannot be confused.
    """
    agent = (await serve(AskingAgent(), "unstoppable")).agents["unstoppable"]
    head = new_identity()

    first = await A2AAdapter(funduq).send_task(
        agent, _message("go"), actor_chain=[head.sign_chain_hop()]
    )
    async with funduq.session() as session:
        assert (await repo.get_run(session, first.id)).status == "input-required"

    with pytest.raises(RunNotCancellable):
        await funduq.cancel_run(first.id, metadata=_proof(head, first.id))

    assert (await _observed(funduq, first.id))["cancelRequestedBy"] == [head.public_key]
