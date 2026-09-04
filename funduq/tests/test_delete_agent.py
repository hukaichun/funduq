from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from funduq import repo
from funduq.core import Funduq
from funduq.errors import AgentInUse, AgentNotFound, InvalidRegistration
from funduq_provider_sdk import InProcessLink, ProviderIdentity, ProviderRuntime
from funduq.models import AgentRef
from funduq_contract import Registration


class _Provider:
    async def run_stream(self, agent_name: str, run_input: dict):
        yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_FINISHED", "threadId": run_input.thread_id, "runId": run_input.run_id}


class _Identity(ProviderIdentity):

    def __init__(self) -> None:
        super().__init__(Ed25519PrivateKey.generate())


async def _link(funduq: Funduq, identity, provider=None):
    """An open link for `identity` — the credential for everything it does to
    its own roster. There is no signed alternative to reach these by."""
    runtime = ProviderRuntime(identity, provider or _Provider())
    runtime.start()
    link = InProcessLink(funduq, runtime)
    await funduq.attach_provider(link)
    return link, runtime


async def _serving(funduq: Funduq, identity, *names: str):
    link, runtime = await _link(funduq, identity)
    await funduq.register_agents(link, [Registration(name=n) for n in names])
    return link, runtime


async def test_deleting_takes_a_link_of_your_own(funduq):
    """The deletion signature is gone: it re-proved a key the link already
    proved. What replaces it is that there is no way in without one — a
    stranger has no link to yours, and its own link only reaches its own
    names."""
    identity, stranger = _Identity(), _Identity()
    _link_a, runtime_a = await _serving(funduq, identity, "translator")
    stranger_link, runtime_b = await _link(funduq, stranger)
    try:
        with pytest.raises(AgentNotFound):
            await funduq.delete_agent(stranger_link, "translator")

        assert await funduq.get_agent(
            AgentRef(provider_key=identity.public_key, name="translator")
        ) is not None
    finally:
        await runtime_a.aclose()
        await runtime_b.aclose()


async def test_deleting_without_an_open_link_is_refused(funduq):
    identity = _Identity()
    link, runtime = await _serving(funduq, identity, "translator")
    funduq.detach_provider(identity.public_key, link)

    with pytest.raises(InvalidRegistration, match="not on an open link"):
        await funduq.delete_agent(link, "translator")
    await runtime.aclose()


async def test_an_unused_agent_is_deleted_even_while_this_link_serves_it(funduq):
    """Deleting happens on the link that serves the name, so "a provider is
    serving it" cannot be the guard it used to be — the caller *is* that
    provider. The name goes offline on the way out."""
    identity = _Identity()
    link, runtime = await _serving(funduq, identity, "typo")
    agent = AgentRef(provider_key=identity.public_key, name="typo")
    assert funduq.is_serving(agent)

    await funduq.delete_agent(link, "typo")

    assert await funduq.get_agent(agent) is None
    assert not funduq.is_serving(agent)

    await funduq.register_agents(link, [Registration(name="typo")])
    assert await funduq.get_agent(agent) is not None
    await runtime.aclose()


async def test_deleting_an_agent_that_never_existed_is_not_found(funduq):
    identity = _Identity()
    link, runtime = await _serving(funduq, identity, "real")

    with pytest.raises(AgentNotFound):
        await funduq.delete_agent(link, "imaginary")
    await runtime.aclose()


async def test_an_agent_with_a_paused_run_is_refused(funduq):
    identity = _Identity()
    link, runtime = await _serving(funduq, identity, "paused")
    agent = AgentRef(provider_key=identity.public_key, name="paused")

    async with funduq.session() as session:
        thread_id = await repo.ensure_thread(session, agent, None)
        created = await repo.create_run(session, thread_id, agent, "ag-ui", {})
        await session.commit()
        await repo.mark_run_status(session, created["run_id"], "running")
        await repo.mark_run_status(session, created["run_id"], "input-required")
        await session.commit()

    with pytest.raises(AgentInUse) as refused:
        await funduq.delete_agent(link, "paused")
    assert refused.value.reason == "has_history"
    await runtime.aclose()


async def test_an_agent_that_has_held_a_conversation_is_refused(funduq):
    """One guard where there were three. A conversation behind it is what
    makes a record worth keeping; stop offering it instead, and it goes
    offline and off the roster with its record intact."""
    identity = _Identity()
    link, runtime = await _serving(funduq, identity, "worked")
    agent = AgentRef(provider_key=identity.public_key, name="worked")

    handle = await funduq.start_run(agent, {"messages": []})
    assert [e["type"] async for e in handle.events()][-1] == "RUN_FINISHED"

    with pytest.raises(AgentInUse) as refused:
        await funduq.delete_agent(link, "worked")
    assert refused.value.reason == "has_history"

    await funduq.register_agents(link, [Registration(name="something-else")])
    assert [a.online for a in await funduq.list_agents() if a.name == "worked"] == [False]
    assert await funduq.get_agent(agent) is not None
    await runtime.aclose()
