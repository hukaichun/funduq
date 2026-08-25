from __future__ import annotations

import pytest

from funduq import repo
from funduq.doors import verify_caller
from funduq.identity import InvalidChain, extend_chain, new_chain
from funduq.models import AgentRef
from funduq_provider_sdk import InProcessLink, ProviderRuntime

from .conftest import publish_agents


class _Echo:
    async def run_stream(self, name, run_input):
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        yield {"type": "RUN_FINISHED", **ids}


async def test_a_chain_carries_authority_when_its_presenter_authenticated(session, new_identity):
    caller = new_identity()
    chain = [caller.sign_chain_hop()]

    _metadata, head, relayed = await verify_caller(
        session, {"actorChain": chain}, presenter_key=caller.public_key
    )

    assert head == caller.public_key
    assert relayed == chain


async def test_a_chain_presented_by_anyone_else_is_refused(session, new_identity):
    """The provider holds its caller's chain — funduq hands it over verbatim so
    the agent can verify for itself — so possession proves nothing. What the
    seat authenticated has to be the party that signed the tail."""
    caller, provider = new_identity(), new_identity()
    chain = [caller.sign_chain_hop()]

    with pytest.raises(InvalidChain, match="last hop"):
        await verify_caller(session, {"actorChain": chain}, presenter_key=provider.public_key)


async def test_the_head_is_not_what_the_presenter_is_compared_against(session, new_identity):
    """Comparing the head instead of the last hop passes the exact replay this
    check exists to stop, and both keys are on the same chain, so nothing but a
    test distinguishes the two implementations."""
    caller, provider = new_identity(), new_identity()
    chain = extend_chain(provider._private_key, new_chain(caller._private_key))

    with pytest.raises(InvalidChain):
        await verify_caller(session, {"actorChain": chain}, presenter_key=caller.public_key)

    _metadata, head, _relayed = await verify_caller(
        session, {"actorChain": chain}, presenter_key=provider.public_key
    )
    assert head == caller.public_key, "extending is provenance; the head still answers for it"


async def test_a_delegating_provider_still_passes(session, new_identity):
    """The check does not touch delegation: a provider that extends with its own
    key signed the tail, so it presents honestly and the caller stays the head."""
    caller, provider = new_identity(), new_identity()
    received = [caller.sign_chain_hop()]

    onward = [*received, provider.sign_chain_hop(prev_token=received[-1])]
    _metadata, head, _relayed = await verify_caller(
        session, {"actorChain": onward}, presenter_key=provider.public_key
    )

    assert head == caller.public_key


async def test_omitting_the_key_changes_nothing(session, new_identity):
    """The check is an extension for a deployment that has an authenticating
    seat, not a new requirement. Withdrawing authority from every caller whose
    embedder passes no key would be compelling participation — so a caller with
    no seat in front of it keeps exactly what it had, and the deployment stays
    exactly as exposed as it was."""
    caller = new_identity()
    chain = [caller.sign_chain_hop()]

    _metadata, head, relayed = await verify_caller(session, {"actorChain": chain})

    assert head == caller.public_key
    assert relayed == chain


async def test_a_tampered_chain_is_refused_before_the_presenter_is_consulted(
    session, new_identity
):
    caller, forger = new_identity(), new_identity()
    real = [caller.sign_chain_hop()]
    elsewhere = [forger.sign_chain_hop()]
    spliced = [*real, forger.sign_chain_hop(prev_token=elsewhere[-1])]

    with pytest.raises(InvalidChain, match="prevHash"):
        await verify_caller(session, {"actorChain": spliced}, presenter_key=forger.public_key)


async def test_the_door_refuses_a_replayed_chain(funduq, new_identity):
    """The probe's scenario, at the door: the provider presents the caller's own
    chain for work the caller never sent."""
    caller, provider_identity = new_identity(), new_identity()
    runtime = ProviderRuntime(provider_identity, _Echo())
    runtime.start()
    try:
        await publish_agents(funduq, InProcessLink(funduq, runtime), ["assistant"])
        agent = AgentRef(provider_key=provider_identity.public_key, name="assistant")

        with pytest.raises(InvalidChain):
            await funduq.start_run(
                agent,
                {"messages": [{"id": "m1", "role": "user", "content": "transfer the budget"}]},
                metadata={"actorChain": [caller.sign_chain_hop()]},
                presenter_key=provider_identity.public_key,
            )
    finally:
        await runtime.aclose()
