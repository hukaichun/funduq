from __future__ import annotations

import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from funduq.errors import AgentNotFound, InvalidRegistration
from funduq_provider_sdk import InProcessLink, ProviderIdentity, ProviderRuntime

from funduq.models import AgentRef

from tests.conftest import publish_offline


class LocalProvider:
    async def run_stream(self, agent_id: str, run_input: dict):
        yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_FINISHED", "threadId": run_input.thread_id, "runId": run_input.run_id}


async def _register(funduq, name: str = "local"):
    identity = ProviderIdentity.generate()
    registration = await publish_offline(funduq, identity, [{"name": name}])
    return registration, identity, registration.agents[name]


async def test_in_process_still_answers_a_ticket_like_anyone_else(funduq):
    """Sharing a process is not a reason to skip the ceremony. The link mints
    a ticket for its own key, signs it, and has the signature verified — and
    it is the same code path a link across a wire takes."""
    identity = ProviderIdentity.generate()
    runtime = ProviderRuntime(identity, LocalProvider())
    runtime.start()
    try:
        link = InProcessLink(funduq, runtime)
        await funduq.attach_provider(link)
        await funduq.register_agents(link, [{"name": "local"}])

        assert funduq.is_serving(AgentRef(provider_key=identity.public_key, name="local"))
    finally:
        await runtime.aclose()


async def test_publishing_less_than_last_time_takes_the_rest_offline(funduq):
    """Not registered is offline. The names a link serves are exactly the ones
    it last published, so a shorter roster is how a provider stops offering
    something — the record stays."""
    identity = ProviderIdentity.generate()
    runtime = ProviderRuntime(identity, LocalProvider())
    runtime.start()
    try:
        link = InProcessLink(funduq, runtime)
        await funduq.attach_provider(link)
        await funduq.register_agents(link, [{"name": "kept"}, {"name": "dropped"}])
        assert {a.name for a in await funduq.list_agents() if a.online} == {"kept", "dropped"}

        await funduq.register_agents(link, [{"name": "kept"}])

        roster = {a.name: a.online for a in await funduq.list_agents()}
        assert roster == {"kept": True, "dropped": False}
    finally:
        await runtime.aclose()


async def test_an_attached_provider_is_actually_online_and_reachable(funduq, attach):
    _registration, identity, agent_id = await _register(funduq)

    await attach(identity, LocalProvider(), [agent_id.name])

    roster = await funduq.list_agents()
    assert [a.name for a in roster] == [agent_id.name]
    assert roster[0].online is True

    handle = await funduq.start_run(agent_id, {"messages": []})
    assert [e["type"] async for e in handle.events()] == ["RUN_STARTED", "RUN_FINISHED"]


async def test_detaching_marks_it_offline_immediately(funduq, attach):
    _registration, identity, agent_id = await _register(funduq)
    await attach(identity, LocalProvider(), [agent_id.name])
    assert (await funduq.list_agents())[0].online is True

    funduq.detach_all_for(identity.public_key)

    roster = await funduq.list_agents()
    assert roster[0].online is False
    assert roster[0].name == agent_id.name
