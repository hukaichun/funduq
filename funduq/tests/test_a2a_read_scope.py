"""Who may read a bound run through the A2A door.

The read circle is wider than the act circle: every actor on the run's
chain may look — the parties responsibility flowed through — while cancel
and resolve stay with the head and the serving provider. A read takes a
key: the transport authenticates whoever is asking and hands the key down
(`presenter_key_of`); how it established the key is its business. An
unauthorized read looks like absence, because existence is part of what is
guarded; an unbound run stays as public as its funduq-minted id.
"""

from __future__ import annotations

import time

import pytest
from a2a.utils.errors import TaskNotFoundError

from sqlalchemy import insert

from funduq import repo
from funduq.identity import InvalidCancel, cancel_payload
from funduq.protocols.a2a import A2AAdapter
from funduq.schema import runs

from tests.conftest import EchoAgent


def _message(text: str) -> dict:
    return {"role": "user", "parts": [{"type": "text", "text": text}]}


@pytest.fixture
async def bound(funduq, serve, new_identity):
    """One settled run under a two-party chain: head (the user) -> middle (a
    delegating provider) -> the serving provider. The middle party presents."""
    head, middle = new_identity(), new_identity()
    served = await serve(EchoAgent(), "trusted")
    chain = [head.sign_chain_hop()]
    chain.append(middle.sign_chain_hop(chain[-1]))

    task = await A2AAdapter(funduq).send_task(
        served.agents["trusted"], _message("hi"), metadata={"actorChain": chain},
        presenter_key=middle.public_key,
    )
    return served, head, middle, task


async def test_without_a_key_a_bound_run_looks_absent(funduq, bound):
    served, _, _, task = bound
    adapter = A2AAdapter(funduq)

    assert await adapter.get_task(served.agents["trusted"], task.id) is None
    with pytest.raises(TaskNotFoundError):
        async for _ in await adapter.resubscribe_task(served.agents["trusted"], task.id):
            pass


async def test_every_chain_party_may_look(funduq, bound):
    served, head, middle, task = bound
    adapter = A2AAdapter(funduq)

    for party in (head, middle, served.identity):
        got = await adapter.get_task(served.agents["trusted"], task.id, reader=party.public_key)
        assert got is not None, f"{party.public_key[:8]} is on the chain and may look"
        assert any(m.parts[0].text == "hi" for m in got.history)


async def test_a_stranger_sees_nothing(funduq, bound, new_identity):
    served, _, _, task = bound
    stranger = new_identity()

    got = await A2AAdapter(funduq).get_task(
        served.agents["trusted"], task.id, reader=stranger.public_key
    )

    assert got is None


async def test_the_same_rule_holds_on_the_facade_and_for_the_provider(funduq, bound, new_identity):
    """One surface, every entrance: the provider serving the agent reads its thread's history as itself; a stranger reads nothing; the record does not care which door asked."""
    served, head, _, task = bound
    stranger = new_identity()

    assert await funduq.as_reader(served.identity.public_key).thread_messages(task.context_id), "the provider is a party"
    assert await funduq.as_reader(head.public_key).thread_messages(task.context_id), "so is the head"
    assert await funduq.as_reader(stranger.public_key).thread_messages(task.context_id) == []
    assert await funduq.as_reader(None).thread_messages(task.context_id) == []
    assert await funduq.as_reader(stranger.public_key).run(task.id) is None
    assert await funduq.as_reader(stranger.public_key).lineage(task.id) == []


async def test_the_middle_actor_may_look_but_not_cancel(funduq, serve, new_identity):
    """The act circle stays {head, serving provider}: a delegating middle
    party follows what it handed on, it does not stop it. Reads take a key;
    acts take a signature over the act."""

    class Holding:
        async def run_stream(self, agent_name, run_input):
            import asyncio

            ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
            yield {"type": "RUN_STARTED", **ids}
            await asyncio.Event().wait()

    head, middle = new_identity(), new_identity()
    served = await serve(Holding(), "slow")
    chain = [head.sign_chain_hop()]
    chain.append(middle.sign_chain_hop(chain[-1]))
    adapter = A2AAdapter(funduq)
    task = await adapter.send_task(
        served.agents["slow"],
        _message("hi"),
        metadata={"actorChain": chain},
        presenter_key=middle.public_key,
        return_immediately=True,
    )

    assert await adapter.get_task(served.agents["slow"], task.id, reader=middle.public_key) is not None

    timestamp = int(time.time())
    with pytest.raises(InvalidCancel):
        await adapter.cancel_task(
            served.agents["slow"],
            task.id,
            metadata={
                "cancel": {
                    "publicKey": middle.public_key,
                    "timestamp": timestamp,
                    "signature": middle.sign(cancel_payload(task.id, timestamp)),
                }
            },
        )


async def test_an_unbound_run_stays_as_public_as_its_id(funduq, serve):
    served = await serve(EchoAgent(), "open")
    adapter = A2AAdapter(funduq)
    task = await adapter.send_task(served.agents["open"], _message("hi"))

    assert await adapter.get_task(served.agents["open"], task.id) is not None
    assert await funduq.as_reader(None).thread_messages(task.context_id)


async def test_a_chainless_run_on_a_bound_thread_does_not_break_every_read(funduq, bound):
    """`readers_of` gathers the chains on a thread to build its circle. It
    used to filter with `actor_chain.is_not(None)`, which does not mean what
    it reads as: the column is JSON, so a Python `None` is stored as JSON
    `null` rather than SQL NULL and the filter matches it — as it matches
    `[]`, which no such filter catches either. `verify_chain` then raised
    `InvalidChain("empty actor chain")` and *every* read of the thread
    raised instead of answering, for the parties in the circle too.

    The doors refuse a chainless write to a bound thread, so this row is one
    door away rather than impossible; the record has to be total on its own.
    """
    served, head, _, task = bound
    async with funduq.session() as session:
        stored = await repo.get_run(session, task.id)
        for run_id, empty in ((f"{task.id}_null", None), (f"{task.id}_empty", [])):
            await session.execute(
                insert(runs).values(
                    run_id=run_id, thread_id=stored.thread_id,
                    provider_key=served.identity.public_key, agent_name="trusted",
                    status="completed", actor_chain=empty,
                )
            )
        await session.commit()

    got = await A2AAdapter(funduq).get_task(
        served.agents["trusted"], task.id, reader=head.public_key
    )
    assert got is not None, "the head is in the circle and a chainless sibling run must not hide it"
