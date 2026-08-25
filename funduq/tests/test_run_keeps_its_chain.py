from __future__ import annotations

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
