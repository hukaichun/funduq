"""Responsibility chains, enforced: birth binding, write membership, ask authority.

The design (docs/mechanisms/responsibility-chains.md): a thread whose first
run carries an actor chain binds {segment head, serving provider} at birth;
writing is membership; a chained ask is resolved only by a signature from
its authority set; a session delegation certificate resolves a session
key's signatures to the durable authority. Unbound threads keep the old
open behavior — the whole mechanism is opt-in by carrying a chain.
"""

from __future__ import annotations

import asyncio

import pytest

from funduq import repo
from funduq.errors import ThreadMembershipRequired
from funduq.identity import InvalidCancel, InvalidResolution
from funduq.protocols.a2a import A2AAdapter
from funduq.protocols.a2a_translate import CANCEL_REQUESTED_METADATA_KEY

from tests.conftest import EchoAgent

from a2a.types import a2a_pb2 as pb
from a2a.utils.errors import TaskNotCancelableError

COMPLETED = pb.TaskState.TASK_STATE_COMPLETED
INPUT_REQUIRED = pb.TaskState.TASK_STATE_INPUT_REQUIRED


def _message(
    text: str,
    *,
    context_id: str | None = None,
    task_id: str | None = None,
    reference_task_ids: list[str] | None = None,
) -> dict:
    """An A2A message. Its addressing rides on the message itself, because in A2A v1.0 that is
    the only place it exists — `SendMessageRequest` carries `message` and `metadata`, nothing
    else."""
    message: dict = {"role": "user", "parts": [{"type": "text", "text": text}]}
    if context_id is not None:
        message["contextId"] = context_id
    if task_id is not None:
        message["taskId"] = task_id
    if reference_task_ids is not None:
        message["referenceTaskIds"] = reference_task_ids
    return message


class AskingAgent:
    """Pauses its first round on an interrupt; any later round completes."""

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
                    "interrupts": [{"id": "int_1", "reason": "question", "message": "which?"}],
                },
            }
        else:
            yield {"type": "RUN_FINISHED", **ids}


async def test_a_chained_thread_binds_its_head_at_birth(funduq, serve, new_identity):
    agent = (await serve(EchoAgent(), "bound")).agents["bound"]
    head = new_identity()

    task = await A2AAdapter(funduq).send_task(
        agent, _message("hi"), actor_chain=[head.sign_chain_hop()]
    )

    async with funduq.session() as session:
        run = await repo.get_run(session, task.id)
        thread = await repo.get_thread(session, task.context_id)
    assert run.head_key == head.public_key
    assert thread["head_key"] == head.public_key


async def test_a_non_member_cannot_speak_on_a_bound_thread(funduq, serve, new_identity):
    agent = (await serve(EchoAgent(), "guarded")).agents["guarded"]
    head, stranger = new_identity(), new_identity()

    task = await A2AAdapter(funduq).send_task(
        agent, _message("hi"), actor_chain=[head.sign_chain_hop()]
    )
    thread_id = task.context_id

    with pytest.raises(ThreadMembershipRequired):
        await A2AAdapter(funduq).send_task(
            agent, _message("let me in", context_id=thread_id),
        )
    with pytest.raises(ThreadMembershipRequired):
        await A2AAdapter(funduq).send_task(
            agent,
            _message("me neither", context_id=thread_id),
            actor_chain=[stranger.sign_chain_hop()],
        )

    # Members interject freely: the head, and the serving provider's own key.
    again = await A2AAdapter(funduq).send_task(
        agent, _message("still me", context_id=thread_id),
        actor_chain=[head.sign_chain_hop()],
    )
    assert again.status.state == COMPLETED


async def test_an_unbound_thread_stays_open_and_is_never_retroactively_locked(
    funduq, serve, new_identity
):
    agent = (await serve(EchoAgent(), "open")).agents["open"]

    first = await A2AAdapter(funduq).send_task(agent, _message("anonymous opener"))
    thread_id = first.context_id

    # A chained writer arriving later does not lock the thread against anyone.
    await A2AAdapter(funduq).send_task(
        agent, _message("chained visitor", context_id=thread_id),
        actor_chain=[new_identity().sign_chain_hop()],
    )
    third = await A2AAdapter(funduq).send_task(
        agent, _message("still anonymous", context_id=thread_id),
    )
    assert third.status.state == COMPLETED

    async with funduq.session() as session:
        thread = await repo.get_thread(session, thread_id)
    assert thread["head_key"] is None


async def test_a_chained_ask_is_resolved_only_by_its_authority(funduq, serve, new_identity):
    provider = AskingAgent()
    agent = (await serve(provider, "asker")).agents["asker"]
    head, impostor = new_identity(), new_identity()

    first = await A2AAdapter(funduq).send_task(
        agent, _message("go"), actor_chain=[head.sign_chain_hop()]
    )
    task_id = first.id
    assert first.status.state == INPUT_REQUIRED

    # No proof, no answer — even from the head's own chain.
    with pytest.raises(InvalidResolution):
        await A2AAdapter(funduq).send_task(
            agent,
            _message("unproven answer", task_id=task_id),
            actor_chain=[head.sign_chain_hop()],
        )

    # A proof signed by the wrong key is refused.
    bad_signature, bad_ts = impostor.sign_resolution(task_id)
    with pytest.raises(InvalidResolution):
        await A2AAdapter(funduq).send_task(
            agent,
            _message("forged answer", task_id=task_id),
            actor_chain=[head.sign_chain_hop()],
            metadata={
                "resolution": {
                    "publicKey": impostor.public_key,
                    "timestamp": bad_ts,
                    "signature": bad_signature,
                }
            },
        )

    # The head's own signature over funduq-resolve:{run_id}:{timestamp} wins.
    signature, timestamp = head.sign_resolution(task_id)
    answered = await A2AAdapter(funduq).send_task(
        agent,
        _message("the answer", task_id=task_id),
        actor_chain=[head.sign_chain_hop()],
        metadata={
            "resolution": {
                "publicKey": head.public_key,
                "timestamp": timestamp,
                "signature": signature,
            }
        },
    )
    assert answered.id == task_id
    assert answered.status.state == COMPLETED


async def test_a_session_key_resolves_to_its_durable_authority(funduq, serve, new_identity):
    """The delegation certificate: the durable key D signs once, naming the
    session key SK; SK signs everything after, and funduq resolves SK's
    signatures to D — rights attach to D, SK is a glove."""
    provider = AskingAgent()
    agent = (await serve(provider, "delegated")).agents["delegated"]
    durable, session_key = new_identity(), new_identity()
    certificate = durable.sign_delegation(session_key.public_key)

    first = await A2AAdapter(funduq).send_task(
        agent,
        _message("go"),
        actor_chain=[session_key.sign_chain_hop()],
        metadata={"delegation": certificate},
    )
    task_id = first.id

    async with funduq.session() as session:
        run = await repo.get_run(session, task_id)
    assert run.head_key == durable.public_key, "the head resolves through the certificate"

    # A later session: new session key, new certificate, same durable rights.
    session_key_2 = new_identity()
    certificate_2 = durable.sign_delegation(session_key_2.public_key)
    signature, timestamp = session_key_2.sign_resolution(task_id)
    answered = await A2AAdapter(funduq).send_task(
        agent,
        _message("the answer", task_id=task_id),
        actor_chain=[session_key_2.sign_chain_hop()],
        metadata={
            "delegation": certificate_2,
            "resolution": {
                "publicKey": session_key_2.public_key,
                "timestamp": timestamp,
                "signature": signature,
            },
        },
    )
    assert answered.status.state == COMPLETED


async def test_the_provider_may_resolve_its_own_agents_ask(funduq, serve, new_identity):
    provider = AskingAgent()
    served = await serve(provider, "stall-kept")
    agent = served.agents["stall-kept"]
    head = new_identity()

    first = await A2AAdapter(funduq).send_task(
        agent, _message("go"), actor_chain=[head.sign_chain_hop()]
    )
    task_id = first.id

    keeper = served.identity
    signature, timestamp = keeper.sign_resolution(task_id)
    answered = await A2AAdapter(funduq).send_task(
        agent,
        _message("the keeper answers", task_id=task_id),
        actor_chain=[keeper.sign_chain_hop()],
        metadata={
            "resolution": {
                "publicKey": keeper.public_key,
                "timestamp": timestamp,
                "signature": signature,
            }
        },
    )
    assert answered.status.state == COMPLETED


async def test_the_agui_door_guards_a_chained_resume_the_same_way(funduq, serve, new_identity):
    from ag_ui.core import RunAgentInput, UserMessage
    from ag_ui.core.types import ResumeEntry

    from funduq.protocols.agui import AGUIAdapter

    provider = AskingAgent()
    served = await serve(provider, "agui-asker")
    agent = served.agents["agui-asker"]
    head = new_identity()
    adapter = AGUIAdapter(funduq)

    def _body(thread_id: str, text: str, metadata: dict, resume=None) -> RunAgentInput:
        return RunAgentInput(
            thread_id=thread_id, run_id="ignored", state={},
            messages=[UserMessage(id="m1", role="user", content=text)],
            tools=[], context=[], forwarded_props={},
            metadata=metadata, resume=resume,
        )

    first = await adapter.run(
        agent, _body("t-chained", "go", {"actorChain": [head.sign_chain_hop()]})
    )
    events = [e async for e in first.events]
    assert any(e.get("type") == "RUN_FINISHED" for e in events)
    run_id = first.run_id

    answer = [ResumeEntry.model_validate(
        {"interruptId": "int_1", "status": "resolved", "payload": {"answer": 42}}
    )]

    with pytest.raises(InvalidResolution):
        await adapter.run(
            agent,
            _body(first.thread_id, "unproven", {"actorChain": [head.sign_chain_hop()]},
                  resume=answer),
        )

    signature, timestamp = head.sign_resolution(run_id)
    resumed = await adapter.run(
        agent,
        _body(
            first.thread_id,
            "the answer",
            {
                "actorChain": [head.sign_chain_hop()],
                "resolution": {
                    "publicKey": head.public_key,
                    "timestamp": timestamp,
                    "signature": signature,
                },
            },
            resume=answer,
        ),
    )
    final = [e async for e in resumed.events]
    assert any(e.get("type") == "RUN_FINISHED" for e in final)


class _NeverFinishes:
    """Starts and then waits, so a cancel meets a run that is genuinely live."""

    async def run_stream(self, agent_name: str, run_input):
        yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_input.run_id}
        await asyncio.Event().wait()


async def _live_bound_run(funduq, serve, head):
    """A live run on a thread that bound `head` at birth, plus the provider serving it."""
    served = await serve(_NeverFinishes(), "bound")
    agent = served.agents["bound"]
    stream = await A2AAdapter(funduq).send_task_streaming(
        agent, _message("go"), actor_chain=[head.sign_chain_hop()]
    )
    opening = await stream.__anext__()
    return agent, opening.id, served.identity


def _was_asked_to_stop(task) -> bool:
    """The cancel landed. Deliberately not a state assertion: what these are
    about is whether the request was accepted at all, and the state it comes
    back in depends on how far the run had got."""
    return CANCEL_REQUESTED_METADATA_KEY in task.metadata


def _proof(identity, run_id):
    signature, timestamp = identity.sign_cancel(run_id)
    return {
        "cancel": {
            "publicKey": identity.public_key,
            "timestamp": timestamp,
            "signature": signature,
        }
    }


async def test_holding_a_run_id_is_not_a_right_to_stop_a_bound_threads_run(
    funduq, serve, new_identity
):
    """Writing a bound thread became a membership act; stopping its run was
    left outside, so a complete stranger holding the run id could still ask
    the provider to stop. A run id is an identifier, and identifiers are
    never credentials."""
    head, stranger = new_identity(), new_identity()
    agent, run_id, _provider = await _live_bound_run(funduq, serve, head)
    a2a = A2AAdapter(funduq)

    with pytest.raises(InvalidCancel):
        await a2a.cancel_task(agent, run_id)

    with pytest.raises(InvalidCancel):
        await a2a.cancel_task(agent, run_id, metadata=_proof(stranger, run_id))

    # Being able to speak on the thread is not the same as being its authority.
    with pytest.raises(InvalidCancel):
        await a2a.cancel_task(
            agent, run_id, metadata={"actorChain": [stranger.sign_chain_hop()]}
        )


async def test_a_stranger_is_refused_before_being_told_a_run_is_uncancellable(
    funduq, serve, new_identity
):
    """A paused run cannot be cancelled, and a caller with no authority over
    it must not learn that from the refusal.

    `cancel_run` checks authority first and cancellability second, and the
    order is the point: "not cancellable" names the run's state, and telling
    a stranger holding nothing but the id which state a bound run is in is
    the same leak rule zero is about. The head gets the state; the stranger
    gets the door.
    """
    head, stranger = new_identity(), new_identity()
    agent = (await serve(AskingAgent(), "asker")).agents["asker"]
    a2a = A2AAdapter(funduq)

    paused = await a2a.send_task(agent, _message("go"), actor_chain=[head.sign_chain_hop()])
    assert paused.status.state == INPUT_REQUIRED

    with pytest.raises(InvalidCancel):
        await a2a.cancel_task(agent, paused.id, metadata=_proof(stranger, paused.id))

    # The head holds the authority, so it gets the real answer.
    with pytest.raises(TaskNotCancelableError):
        await a2a.cancel_task(agent, paused.id, metadata=_proof(head, paused.id))


async def test_a_resolution_signature_is_not_a_cancel_signature(funduq, serve, new_identity):
    """Separate tags, so a signature collected for one act can never be spent
    as the other — the head answering its own ask does not thereby hand
    anyone the power to stop its runs."""
    head = new_identity()
    agent, run_id, _provider = await _live_bound_run(funduq, serve, head)

    signature, timestamp = head.sign_resolution(run_id)
    with pytest.raises(InvalidCancel):
        await A2AAdapter(funduq).cancel_task(
            agent,
            run_id,
            metadata={
                "cancel": {
                    "publicKey": head.public_key,
                    "timestamp": timestamp,
                    "signature": signature,
                }
            },
        )


async def test_the_runs_own_authorities_may_stop_it(funduq, serve, new_identity):
    """The same authority set an ask on the run would have — its segment head
    and the agent's own provider — because it is the same question asked
    twice: who does this run's segment answer to?"""
    head = new_identity()
    agent, run_id, provider = await _live_bound_run(funduq, serve, head)

    by_head = await A2AAdapter(funduq).cancel_task(agent, run_id, metadata=_proof(head, run_id))
    assert _was_asked_to_stop(by_head)

    other_head = new_identity()
    agent2, run_2, provider2 = await _live_bound_run(funduq, serve, other_head)
    by_provider = await A2AAdapter(funduq).cancel_task(
        agent2, run_2, metadata=_proof(provider2, run_2)
    )
    assert _was_asked_to_stop(by_provider)


async def test_an_unbound_run_is_still_anyones_to_stop(funduq, serve, new_identity):
    """The mechanism is opt-in by carrying a chain, same as every other part
    of it. A thread that named no authority at birth has none to check
    against, and inventing one here would make funduq the authority instead
    of the caller."""
    served = await serve(_NeverFinishes(), "open")
    agent = served.agents["open"]
    stream = await A2AAdapter(funduq).send_task_streaming(agent, _message("go"))
    opening = await stream.__anext__()

    cancelled = await A2AAdapter(funduq).cancel_task(agent, opening.id)

    assert _was_asked_to_stop(cancelled)


async def test_the_facade_asks_the_same_question_as_the_door(funduq, serve, new_identity):
    """One check, wherever the cancel came in. A serving layer reaching past
    the A2A door for `cancel_run` would otherwise be the bypass."""
    head = new_identity()
    _agent, run_id, _provider = await _live_bound_run(funduq, serve, head)

    with pytest.raises(InvalidCancel):
        await funduq.cancel_run(run_id)

    assert await funduq.cancel_run(run_id, metadata=_proof(head, run_id)) is True
