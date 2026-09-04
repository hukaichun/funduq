from __future__ import annotations

from funduq import repo
from funduq.models import AgentRef
from funduq_contract import Registration


async def test_registering_mints_no_id_at_all(session, new_identity):
    identity = new_identity()

    registered = await repo.register_agents(session, identity.public_key, [Registration(name="a")])

    assert registered["a"] == AgentRef(provider_key=identity.public_key, name="a")
    assert registered["a"].provider_key == identity.public_key


async def test_create_thread_assigns_a_database_generated_thread_id(session, new_identity):
    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="a")])
    thread_id = await repo.create_thread(session, registered["a"])
    assert thread_id.startswith("thread_")


async def test_ensure_thread_mints_a_fresh_thread_when_neither_id_is_given(session, new_identity):
    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="a")])
    thread_id = await repo.ensure_thread(session, registered["a"], None)
    assert thread_id.startswith("thread_")


async def test_ensure_thread_rejects_an_unknown_thread_id_by_default(session, new_identity):
    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="a")])
    try:
        await repo.ensure_thread(session, registered["a"], "thread_made_up")
        assert False, "expected ThreadNotFound"
    except repo.ThreadNotFound:
        pass


async def test_ensure_thread_creates_under_an_unknown_id_when_told_to(session, new_identity):
    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="a")])
    thread_id = await repo.ensure_thread(
        session, registered["a"], "thread_made_up", create_if_missing=True
    )
    assert thread_id.startswith("thread_")
    assert thread_id != "thread_made_up"


async def test_create_run_assigns_a_database_generated_run_id(session, new_identity):
    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="a")])
    thread_id = await repo.create_thread(session, registered["a"])

    first = await repo.create_run(session, thread_id, registered["a"], "ag-ui", {})
    await session.commit()
    assert first["run_id"].startswith("run_")

    second = await repo.create_run(session, thread_id, registered["a"], "ag-ui", {})
    await session.commit()
    assert second["run_id"] != first["run_id"]


async def test_stamping_discards_any_caller_supplied_id():
    stamped = repo.stamp_messages(
        [{"id": "whatever-the-caller-made-up", "role": "user", "content": "hi"}]
    )
    assert stamped[0]["id"] != "whatever-the-caller-made-up"
    assert stamped[0]["id"].startswith("msg_")


async def test_a_message_is_stored_under_the_id_it_was_stamped_with(session, new_identity):
    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="a")])
    thread_id = await repo.create_thread(session, registered["a"])
    run = await repo.create_run(session, thread_id, registered["a"], "ag-ui", {})
    await session.commit()

    stamped = repo.stamp_messages([{"role": "user", "content": "hi"}])
    await repo.append_thread_messages(session, thread_id, run["run_id"], stamped)

    persisted = await repo.get_thread_messages(session, thread_id)
    assert persisted[0]["id"] == stamped[0]["id"]


async def test_stamping_never_deduplicates_by_content(session, new_identity):
    identity = new_identity()
    registered = await repo.register_agents(session, identity.public_key, [Registration(name="a")])
    thread_id = await repo.create_thread(session, registered["a"])
    run = await repo.create_run(session, thread_id, registered["a"], "ag-ui", {})
    await session.commit()

    same_content = [{"role": "user", "content": "hi"}]
    await repo.append_thread_messages(session, thread_id, run["run_id"], repo.stamp_messages(same_content))
    await repo.append_thread_messages(session, thread_id, run["run_id"], repo.stamp_messages(same_content))

    persisted = await repo.get_thread_messages(session, thread_id)
    assert len(persisted) == 2
    assert persisted[0]["id"] != persisted[1]["id"]
