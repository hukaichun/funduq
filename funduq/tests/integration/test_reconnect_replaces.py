from __future__ import annotations

from tests.conftest import publish_agents, publish_llm

from funduq_provider_sdk.llm import InProcessLLMProvider, ProviderIdentity

from funduq.models import AgentRef, LlmRef

from tests.test_llm_provider_drives_kyok import StubLLM


class _StubConnection:

    max_concurrent_runs = None

    def __init__(self, identity: ProviderIdentity) -> None:
        self.public_key = identity.public_key
        self.sign_connect = identity.sign_connect

    async def deliver(self, run):
        return False

    def cancel(self, run_id: str) -> None:
        pass


async def test_a_replaced_agent_connections_cleanup_leaves_the_replacement_serving(funduq, register):
    served = await register("worker")
    key = served.identity.public_key
    ref = AgentRef(provider_key=key, name="worker")
    old, new = _StubConnection(served.identity), _StubConnection(served.identity)

    await publish_agents(funduq, old, ["worker"])
    await publish_agents(funduq, new, ["worker"])
    assert funduq.broker.serving(ref) is new

    funduq.detach_provider(key, connection=old)
    assert funduq.broker.serving(ref) is new

    funduq.detach_provider(key, connection=new)
    assert funduq.broker.serving(ref) is None


async def test_a_replaced_llm_connections_cleanup_leaves_the_replacement_serving(funduq):
    identity = ProviderIdentity.generate()
    ref = LlmRef(provider_key=identity.public_key, name="gpt4")
    old = InProcessLLMProvider(identity, StubLLM())
    new = InProcessLLMProvider(identity, StubLLM())

    await publish_llm(funduq, old, ["gpt4"])
    await publish_llm(funduq, new, ["gpt4"])
    assert funduq.kyok_relay.serving(ref) is new

    funduq.detach_llm_provider(identity.public_key, connection=old)
    assert funduq.kyok_relay.serving(ref) is new

    funduq.detach_llm_provider(identity.public_key, connection=new)
    assert funduq.kyok_relay.serving(ref) is None


async def test_detach_all_for_evicts_the_key_from_both_rosters(funduq, register):
    served = await register("evictee")
    identity = served.identity
    key = identity.public_key
    agent_ref = AgentRef(provider_key=key, name="evictee")
    llm_ref = LlmRef(provider_key=key, name="gpt4")

    await publish_agents(funduq, _StubConnection(identity), ["evictee"])
    await publish_llm(funduq, InProcessLLMProvider(identity, StubLLM()), ["gpt4"])
    assert funduq.broker.serving(agent_ref) is not None
    assert funduq.kyok_relay.serving(llm_ref) is not None

    funduq.detach_all_for(key)

    assert funduq.broker.serving(agent_ref) is None
    assert funduq.kyok_relay.serving(llm_ref) is None
