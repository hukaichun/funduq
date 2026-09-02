"""Who may read a bound run through the A2A door.

The read circle is wider than the act circle: every actor on the run's
chain may look — the parties responsibility flowed through — while cancel
and resolve stay with the head and the serving provider. An unauthorized
read looks like absence, because existence is part of what is guarded; an
unbound run stays as public as its funduq-minted id.
"""

from __future__ import annotations

import time

import pytest
from a2a.types import a2a_pb2 as pb
from a2a.utils.errors import TaskNotFoundError

from funduq.identity import InvalidCancel, cancel_payload, view_payload
from funduq.protocols.a2a import A2AAdapter

from tests.conftest import EchoAgent


def _message(text: str) -> dict:
    return {"role": "user", "parts": [{"type": "text", "text": text}]}


def _view(identity, run_id: str) -> dict:
    timestamp = int(time.time())
    return {
        "view": {
            "publicKey": identity.public_key,
            "timestamp": timestamp,
            "signature": identity.sign(view_payload(run_id, timestamp)),
        }
    }


@pytest.fixture
async def bound(funduq, serve, new_identity):
    """One settled run under a two-party chain: head (the user) -> middle (a
    delegating provider) -> the serving provider."""
    head, middle = new_identity(), new_identity()
    served = await serve(EchoAgent(), "trusted")
    chain = [head.sign_chain_hop()]
    chain.append(middle.sign_chain_hop(chain[-1]))

    task = await A2AAdapter(funduq).send_task(
        served.agents["trusted"], _message("hi"), metadata={"actorChain": chain}
    )
    return served, head, middle, task


async def test_without_a_proof_a_bound_run_looks_absent(funduq, bound):
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
        got = await adapter.get_task(
            served.agents["trusted"], task.id, view_metadata=_view(party, task.id)
        )
        assert got is not None, f"{party.public_key[:8]} is on the chain and may look"
        assert any(m.parts[0].text == "hi" for m in got.history)


async def test_a_strangers_own_signature_buys_nothing(funduq, bound, new_identity):
    served, _, _, task = bound
    stranger = new_identity()

    got = await A2AAdapter(funduq).get_task(
        served.agents["trusted"], task.id, view_metadata=_view(stranger, task.id)
    )

    assert got is None


async def test_the_middle_actor_may_look_but_not_cancel(funduq, serve, new_identity):
    """The act circle stays {head, serving provider}: a delegating middle
    party follows what it handed on, it does not stop it."""

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
        return_immediately=True,
    )

    assert (
        await adapter.get_task(
            served.agents["slow"], task.id, view_metadata=_view(middle, task.id)
        )
        is not None
    )

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

    got = await adapter.get_task(served.agents["open"], task.id)

    assert got is not None
