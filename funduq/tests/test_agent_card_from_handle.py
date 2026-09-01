from __future__ import annotations

import pytest
from funduq_provider_sdk import AgentHandle
from funduq_contract import Registration

SKILLS = [
    {"id": "translate", "name": "Translate", "tags": ["language", "text"]},
    {"id": "summarize", "name": "Summarize", "tags": ["text"]},
]


async def _run_stream(run_input: dict):
    yield {"type": "RUN_FINISHED", "threadId": run_input.thread_id, "runId": run_input.run_id}


async def _register(funduq, identity, *handles: AgentHandle):
    from tests.conftest import publish_offline

    return await publish_offline(funduq, identity, [h.as_registration() for h in handles])


async def test_skills_declared_on_a_handle_reach_the_roster(funduq, new_identity):
    identity = new_identity()
    handle = AgentHandle(
        name="translator",
        run_stream=_run_stream,
        description="translates things",
        agent_card_extra={"skills": SKILLS},
    )

    await _register(funduq, identity, handle)

    listed = next(a for a in await funduq.list_agents() if a.name == "translator")
    assert listed.skills == SKILLS


async def test_the_card_keeps_name_and_description_alongside_the_extra(funduq, new_identity):
    identity = new_identity()
    handle = AgentHandle(
        name="translator",
        run_stream=_run_stream,
        description="translates things",
        agent_card_extra={"skills": SKILLS, "version": "2.0"},
    )

    registration = await _register(funduq, identity, handle)

    card = (await funduq.get_agent(registration["translator"])).agent_card
    assert card["name"] == "translator"
    assert card["description"] == "translates things"
    assert card["version"] == "2.0"
    assert card["skills"] == SKILLS


async def test_metadata_is_stored_and_stays_off_the_public_card(funduq, new_identity):
    identity = new_identity()
    handle = AgentHandle(
        name="translator",
        run_stream=_run_stream,
        metadata={"cost_centre": "research", "owner": "ada"},
    )

    registration = await _register(funduq, identity, handle)
    record = await funduq.get_agent(registration["translator"])

    assert record.metadata == {"cost_centre": "research", "owner": "ada"}
    assert "cost_centre" not in record.agent_card


async def test_a_handle_that_declares_nothing_extra_still_registers(funduq, new_identity):
    identity = new_identity()
    handle = AgentHandle(name="plain", run_stream=_run_stream, description="d")

    assert handle.as_registration() == Registration(name="plain", description="d")

    registration = await _register(funduq, identity, handle)
    record = await funduq.get_agent(registration["plain"])

    assert record.agent_card == {"name": "plain", "description": "d"}
    assert record.metadata == {}


@pytest.mark.parametrize("field_name", ["agent_card_extra", "metadata"])
async def test_re_registering_replaces_what_the_handle_now_says(funduq, new_identity, field_name):
    identity = new_identity()

    await _register(
        funduq,
        identity,
        AgentHandle(name="a", run_stream=_run_stream, **{field_name: {"skills": SKILLS}}),
    )
    registration = await _register(
        funduq,
        identity,
        AgentHandle(name="a", run_stream=_run_stream, **{field_name: {"skills": SKILLS[:1]}}),
    )

    record = await funduq.get_agent(registration["a"])
    stored = record.agent_card if field_name == "agent_card_extra" else record.metadata
    assert stored["skills"] == SKILLS[:1]


async def test_a_provider_with_the_hook_declares_interjections_on_its_card(funduq, serve):
    from funduq.props import INTERJECTION_EXTENSION_URI
    from funduq.protocols.a2a import A2AAdapter

    class Interjecting:
        async def run_stream(self, agent_name, run_input):
            ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
            yield {"type": "RUN_STARTED", **ids}
            yield {"type": "RUN_FINISHED", **ids}

        async def interject_stream(self, agent_name, run_input, active_run_id):
            ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
            yield {"type": "RUN_STARTED", **ids}
            yield {"type": "RUN_FINISHED", **ids}

    provider = Interjecting()
    served = await serve(provider, "interruptible")
    assert served.runtime.takes_interjections is True

    # Re-publish with the declaration the runtime derives, as a serving layer would.
    await funduq.register_agents(
        served.link,
        [Registration(name="interruptible", takes_interjections=served.runtime.takes_interjections)],
    )

    card = await A2AAdapter(funduq).agent_card(served.agents["interruptible"])
    assert INTERJECTION_EXTENSION_URI in [e.uri for e in card.capabilities.extensions]


async def test_a_provider_without_the_hook_declares_nothing(funduq, serve):
    from funduq.props import INTERJECTION_EXTENSION_URI
    from funduq.protocols.a2a import A2AAdapter

    served = await serve(None, "plain-speaker")
    assert served.runtime.takes_interjections is False

    card = await A2AAdapter(funduq).agent_card(served.agents["plain-speaker"])
    assert INTERJECTION_EXTENSION_URI not in [e.uri for e in card.capabilities.extensions]
