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


async def test_core_does_not_decide_who_may_read(funduq, bound, new_identity):
    """A chain records acts; reading is not one, so it no longer decides who
    may look (#275). Every read answers from the record, to whoever asks —
    the doors carry no `reader` and core carries no circle. Authorisation is
    the wire's, where it belongs and where a different team usually owns it.

    What core still owes that team is the answer it cannot compute for
    itself: `parties_of`, asserted below."""
    served, _, _, task = bound
    stranger = new_identity()
    adapter = A2AAdapter(funduq)

    assert await adapter.get_task(served.agents["trusted"], task.id) is not None
    assert await funduq.get_thread_messages(task.context_id)
    assert await funduq.get_run(task.id) is not None
    assert await funduq.lineage(task.id)

    # And nothing about the stranger's key changes any of it — there is no
    # longer anywhere to put it.
    assert stranger.public_key not in (await funduq.parties_of(task.context_id))


async def test_a_task_of_another_agent_is_still_not_this_agents(funduq, bound, serve):
    """The one thing `get_task` still refuses is the thing that was never
    authorisation: a task belonging to a different agent is not this agent's
    task, whoever is asking."""
    served, _, _, task = bound
    other = (await serve(EchoAgent(), "other")).agents["other"]

    assert await A2AAdapter(funduq).get_task(other, task.id) is None


async def test_the_middle_actor_may_look_but_not_cancel(funduq, serve, new_identity):
    """The act circle stays {head, serving provider}: a delegating middle
    party follows what it handed on, it does not stop it. The chain decides
    acts and only acts — since #275 it decides no reads at all, so what is
    asserted here is the refusal, not the look."""

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

    assert await adapter.get_task(served.agents["slow"], task.id) is not None

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
    assert await funduq.get_thread_messages(task.context_id)


async def test_a_chainless_run_on_a_bound_thread_does_not_break_every_read(funduq, bound):
    """`readers_of` gathers the chains on a thread to answer `parties_of`.
    It used to filter with `actor_chain.is_not(None)`, which does not mean
    what it reads as: the column is JSON, so a Python `None` is stored as
    JSON `null` rather than SQL NULL and the filter matches it — as it
    matches `[]`, which no such filter catches either. `verify_chain` then
    raised `InvalidChain("empty actor chain")`, and while that answer still
    gated every read, one such row made the whole thread unreadable (#270).

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

    assert await A2AAdapter(funduq).get_task(served.agents["trusted"], task.id) is not None
    assert await funduq.parties_of(stored.thread_id), "a chainless sibling must not empty the answer"


async def test_parties_of_answers_without_deciding(funduq, bound, new_identity):
    """Core is the only party that can compute the set — the chains are here
    and only here are they verified — so it publishes the answer separately
    from anything that acts on it. A gateway that owns authorisation asks
    this instead of reaching into `repo` — and since #275 there is nothing
    else to ask: core itself no longer decides reads."""
    served, head, middle, task = bound
    async with funduq.session() as session:
        stored = await repo.get_run(session, task.id)

    parties = await funduq.parties_of(stored.thread_id)

    assert parties is not None
    assert {head.public_key, middle.public_key, served.identity.public_key} <= parties
    assert new_identity().public_key not in parties


async def test_parties_of_names_nobody_for_an_unbound_thread(funduq, serve):
    """An unbound thread is readable by whoever holds its id, so there is no
    party set to answer with — the same None `readers_of` returns, said out
    loud rather than only implied by a read that succeeds."""
    served = await serve(EchoAgent(), "open")
    task = await A2AAdapter(funduq).send_task(served.agents["open"], _message("hi"))
    async with funduq.session() as session:
        stored = await repo.get_run(session, task.id)

    assert await funduq.parties_of(stored.thread_id) is None
    assert await funduq.parties_of("thread_nope") is None
