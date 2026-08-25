from __future__ import annotations

import time

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


async def test_a_run_keeps_the_chain_it_arrived_under(funduq, new_identity):
    """The head answers "who answers for this"; the chain answers "through
    whose hands", and nothing else on the record can. Keeping only the head is
    what made a branch — a party rebuilding a chain without the hands between
    the head and itself — unnoticeable after the fact."""
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

        assert run.actor_chain == chain, "every hop, exactly as presented"
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

    assert run.actor_chain == opened_under, "the chain it was opened under, not the answerer's"
    assert run.head_key == caller.public_key, "the run still answers to the head it was born with"
    assert run.metadata["resolution"]["publicKey"] == caller.public_key, (
        "the answering act is recorded — bound to this run by a signature, "
        "which is a stronger trace than a chain"
    )
