from __future__ import annotations

import time

import jwt

from funduq import repo
from funduq.models import AgentRef
from funduq_provider_sdk import InProcessLink, ProviderRuntime

from .conftest import publish_agents


class _Echo:
    async def run_stream(self, name, run_input):
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        yield {"type": "RUN_FINISHED", **ids}


async def _serve(funduq, identity):
    runtime = ProviderRuntime(identity, _Echo())
    runtime.start()
    await publish_agents(funduq, InProcessLink(funduq, runtime), ["assistant"])
    return runtime, AgentRef(provider_key=identity.public_key, name="assistant")


async def test_a_run_keeps_the_chain_it_was_dispatched_under(funduq, new_identity):
    """The head answers "who answers for this"; the chain answers "through
    whose hands", and nothing else on the record can. Keeping only the head is
    what made a branch — a party rebuilding a chain without the hands between
    the head and itself — unnoticeable after the fact.

    What is kept is the chain **as dispatched**: every hop the caller
    presented, plus the one funduq signs naming where it sent the run. It
    used to be the presented chain alone, which meant funduq's own books
    could not tell a run it had dispatched from a chain that reached it
    having passed no witness at all — the two were the same bytes. The agent
    always received the longer one; only the record was short.
    """
    caller, provider, hop = new_identity(), new_identity(), None
    runtime, agent = await _serve(funduq, provider)
    try:
        hop = caller.sign_chain_hop()
        chain = [hop, provider.sign_chain_hop(prev_token=hop)]

        handle = await funduq.start_run(
            agent,
            {"messages": [{"id": "m1", "role": "user", "content": "hi"}]},
            metadata={"actorChain": chain},
            presenter_key=provider.public_key,
        )
        async for _ in handle.events():
            pass

        async with funduq.session() as session:
            run = await repo.get_run(session, handle.run_id)

        assert run.actor_chain[: len(chain)] == chain, "every presented hop, untouched"
        assert len(run.actor_chain) == len(chain) + 1, "plus funduq's own"

        dispatched = jwt.decode(run.actor_chain[-1], options={"verify_signature": False})
        assert dispatched["actorPublicKey"] == funduq.identity.public_key
        assert dispatched["dispatchedTo"] == {
            "providerKey": agent.provider_key,
            "name": agent.name,
        }, "the witness names where it sent the run"
        assert run.head_key == caller.public_key
    finally:
        await runtime.aclose()


async def test_a_run_with_no_chain_keeps_none(funduq, new_identity):
    """NULL means none was carried — not that one was dropped."""
    runtime, agent = await _serve(funduq, new_identity())
    try:
        handle = await funduq.start_run(
            agent, {"messages": [{"id": "m1", "role": "user", "content": "hi"}]}
        )
        async for _ in handle.events():
            pass

        async with funduq.session() as session:
            run = await repo.get_run(session, handle.run_id)

        assert run.actor_chain is None
        assert run.head_key is None
    finally:
        await runtime.aclose()


async def test_a_resume_does_not_replace_the_chain_the_run_was_opened_under(
    funduq, new_identity, attach
):
    """A run's responsibility is fixed at its birth and there is one form of
    it. The party answering a paused ask is not taking the run over, so
    neither the head nor the chain moves — and that party is not unrecorded,
    because the signature it had to produce is kept in the run's metadata. A
    chain says who stood on the path; that signature is bound to this act by
    this key."""
    from funduq.identity import resolve_payload

    from .test_facade import PausingProvider, _register, _until

    caller, answerer, identity = new_identity(), new_identity(), new_identity()
    agent_id = await _register(funduq, "asker", identity)
    await attach(identity, PausingProvider(), [agent_id.name])

    opened_under = [caller.sign_chain_hop()]
    handle = await funduq.start_run(
        agent_id,
        {"messages": [{"role": "user", "content": "one"}]},
        metadata={"actorChain": opened_under},
        presenter_key=caller.public_key,
    )
    [_ async for _ in handle.events()]
    await _until(lambda: handle.run_id not in funduq.active_runs())

    timestamp = int(time.time())
    resumed = await funduq.resume_run(
        handle.run_id,
        {
            "messages": [{"role": "user", "content": "two"}],
            "resume": [{"interruptId": "int_1", "status": "resolved", "payload": {"answer": 42}}],
        },
        metadata={
            "actorChain": [answerer.sign_chain_hop()],
            "resolution": {
                "publicKey": caller.public_key,
                "timestamp": timestamp,
                "signature": caller.sign(resolve_payload(handle.run_id, timestamp)),
            },
        },
        presenter_key=answerer.public_key,
    )
    [_ async for _ in resumed.events()]
    await _until(lambda: handle.run_id not in funduq.active_runs())

    async with funduq.session() as session:
        run = await repo.get_run(session, handle.run_id)

    assert run.actor_chain[0] == opened_under[0], "the hop it was opened under"
    assert answerer.public_key not in [
        jwt.decode(hop, options={"verify_signature": False})["actorPublicKey"]
        for hop in run.actor_chain
    ], "the answerer never enters the chain — answering is not taking the run over"
    assert run.head_key == caller.public_key, "the run still answers to the head it was born with"
    assert run.metadata["resolution"]["publicKey"] == caller.public_key, (
        "the answering act is recorded — bound to this run by a signature, "
        "which is a stronger trace than a chain"
    )


async def test_the_agent_sees_the_same_chain_on_every_round(funduq, serve, new_identity):
    """A resume is the same run continuing, so what the agent verifies must
    not change because somebody else answered its pause.

    It used to. The resume path handed dispatch the *answering party's* chain
    and head, and dispatch signed a fresh hop over them — so a provider that
    resolved its own agent's ask (which it may) sent that agent a chain
    headed by the provider itself on the second round. The whole design rests
    on the agent verifying for itself rather than trusting a relayed digest,
    and on round two what it verified said it was working for whoever
    answered. The run's own `head_key` never moved, so the record and the
    thing handed to the agent disagreed, and only the agent's side was wrong.

    Signing the dispatch hop at the door rather than inside dispatch is what
    makes the fix available: the chain the run stores is already the one to
    relay, so a resume relays it unchanged instead of re-signing a handover
    that is not happening — one delegation, one witness signature.
    """
    from funduq.protocols.a2a import A2AAdapter

    from .test_responsibility_chains import AskingAgent, _message

    provider = AskingAgent()
    served = await serve(provider, "asker")
    agent = served.agents["asker"]
    head, keeper = new_identity(), served.identity

    first = await A2AAdapter(funduq).send_task(
        agent, _message("go"), actor_chain=[head.sign_chain_hop()]
    )
    signature, timestamp = keeper.sign_resolution(first.id)
    await A2AAdapter(funduq).send_task(
        agent,
        _message("the provider answers its own ask", task_id=first.id),
        actor_chain=[keeper.sign_chain_hop()],
        metadata={
            "resolution": {
                "publicKey": keeper.public_key,
                "timestamp": timestamp,
                "signature": signature,
            }
        },
    )

    rounds = [(r.forwarded_props or {}).get("actorChain") for r in provider.rounds]
    assert len(rounds) == 2, "the ask was answered, so the agent ran twice"
    assert rounds[0] == rounds[1], "the same run, so the same chain"

    signers = [
        jwt.decode(hop, options={"verify_signature": False})["actorPublicKey"]
        for hop in rounds[1]
    ]
    assert signers[0] == head.public_key, "still working for the head that opened it"
    assert keeper.public_key not in signers, (
        "the party that answered the pause does not become who the work is for"
    )
