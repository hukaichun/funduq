from __future__ import annotations

import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from funduq.identity import (
    InvalidActorChain,
    extend_actor_chain,
    new_actor_chain,
)
from funduq.protocols.a2a import A2AAdapter

from tests.conftest import EchoAgent

from a2a.types import a2a_pb2 as pb
from a2a.utils.errors import TaskNotCancelableError

COMPLETED = pb.TaskState.TASK_STATE_COMPLETED
INPUT_REQUIRED = pb.TaskState.TASK_STATE_INPUT_REQUIRED

USER = {"type": "user", "id": "employee_x"}


def _message(
    text: str,
    *,
    context_id: str | None = None,
    task_id: str | None = None,
    reference_task_ids: list[str] | None = None,
) -> dict:
    """An A2A message. Its addressing rides on the message itself, because in A2A v1.0 that is
    the only place it exists — `SendMessageRequest` carries `message` and `metadata`, nothing
    else."""
    message: dict = {"role": "user", "parts": [{"type": "text", "text": text}]}
    if context_id is not None:
        message["contextId"] = context_id
    if task_id is not None:
        message["taskId"] = task_id
    if reference_task_ids is not None:
        message["referenceTaskIds"] = reference_task_ids
    return message


async def test_delegate_without_building_a_json_rpc_envelope(funduq, serve):
    callee = (await serve(EchoAgent(), "callee")).agents["callee"]

    task = await A2AAdapter(funduq).send_task(callee, _message("do the thing"))

    assert task.status.state == COMPLETED
    assert task.id.startswith("run_")


async def test_the_callers_chain_reaches_the_agent_verbatim_on_both_roads(funduq, serve):
    from ag_ui.core import RunAgentInput, UserMessage

    from funduq.protocols.agui import AGUIAdapter

    agui_served = await serve(EchoAgent(), "agui-callee")
    a2a_served = await serve(EchoAgent(), "a2a-callee")
    chain = new_actor_chain(Ed25519PrivateKey.generate())

    stream = await AGUIAdapter(funduq).run(
        agui_served.agents["agui-callee"],
        RunAgentInput(
            thread_id="t-props",
            run_id="r",
            state={},
            messages=[UserMessage(id="m1", role="user", content="hi")],
            tools=[],
            context=[],
            forwarded_props={},
            metadata={"actorChain": chain},
        ),
    )
    async for _ in stream.events:
        pass
    await A2AAdapter(funduq).send_task(a2a_served.agents["a2a-callee"], _message("hi"), actor_chain=chain)

    # No funduq-authored digest exists: both doors relay the caller's own
    # chain, byte-identical, and the agent verifies it for itself.
    assert agui_served.provider.seen_chain == chain
    assert a2a_served.provider.seen_chain == chain


async def test_identity_is_carried_through_an_in_process_hop(funduq, serve):
    served = await serve(EchoAgent(), "callee")
    callee, provider = served.agents["callee"], served.provider

    agency, relaying_agent = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
    chain = extend_actor_chain(relaying_agent, new_actor_chain(agency))

    await A2AAdapter(funduq).send_task(callee, _message("hi"), actor_chain=chain)

    assert provider.seen_chain == chain
    from funduq_provider_sdk import verify_chain

    result = verify_chain(provider.seen_chain)
    assert result.actor_public_keys == [
        agency.public_key().public_bytes_raw().hex(),
        relaying_agent.public_key().public_bytes_raw().hex(),
    ]
    assert result.head == agency.public_key().public_bytes_raw().hex()


async def test_a_tampered_chain_is_rejected_on_this_path_too(funduq, serve):
    callee = (await serve(EchoAgent(), "callee")).agents["callee"]

    chain = new_actor_chain(Ed25519PrivateKey.generate())
    tampered = [chain[0][:-4] + "AAAA"]

    with pytest.raises(InvalidActorChain):
        await A2AAdapter(funduq).send_task(callee, _message("hi"), actor_chain=tampered)


async def test_lineage_links_the_callee_thread_back_to_the_caller(funduq, serve, register):
    caller = (await register("caller")).agents["caller"]
    callee = (await serve(EchoAgent(), "callee")).agents["callee"]

    caller_thread = await funduq.create_thread(caller)
    caller_run = await funduq.start_run(caller, {"messages": []}, thread_id=caller_thread)

    await A2AAdapter(funduq).send_task(
        callee, _message("hi", reference_task_ids=[caller_run.run_id]),
    )

    tree = await funduq.get_thread_tree(caller_thread)
    assert len(tree["children"]) == 1


async def test_context_id_continues_the_same_conversation(funduq, serve):
    callee = (await serve(EchoAgent(), "callee")).agents["callee"]
    adapter = A2AAdapter(funduq)

    first = await adapter.send_task(callee, _message("one"))
    second = await adapter.send_task(
        callee, _message("two", context_id=first.context_id),
    )

    assert second.context_id == first.context_id
    assert second.id != first.id


async def test_there_is_only_one_rung_now(funduq, serve):
    """There used to be two ways in here — a JSON-RPC envelope and the operation behind it —
    and a test that they agreed. Core no longer writes the envelope, so the agreement is
    structural rather than checked: an in-process delegation and a networked caller reach the
    same method, and what differs is only what the transport wraps it in."""
    callee = (await serve(EchoAgent(), "callee")).agents["callee"]

    task = await A2AAdapter(funduq).send_task(callee, _message("hi"))

    assert isinstance(task, pb.Task)
    assert task.status.state == COMPLETED


async def test_get_and_cancel_are_callable_directly(funduq, serve):
    callee = (await serve(EchoAgent(), "callee")).agents["callee"]
    adapter = A2AAdapter(funduq)

    task = await adapter.send_task(callee, _message("hi"))
    assert (await adapter.get_task(callee, task.id)).id == task.id

    # The echo agent has already finished, and a finished task is not
    # cancellable — returning it as though the request had been accepted is
    # the unreadable answer this raise replaces (funduq#149).
    with pytest.raises(TaskNotCancelableError):
        await adapter.cancel_task(callee, task.id)


async def test_an_unknown_task_is_not_found_rather_than_an_exception(funduq, register):
    """`None`, which is what A2A's own request-handler interface means by not-found: the
    transport turns it into whatever its binding calls that. funduq used to mint the JSON-RPC
    code itself, which it could never do correctly — the code a caller should see depends on
    the protocol version they declared in a header core does not see."""
    callee = (await register("callee")).agents["callee"]
    adapter = A2AAdapter(funduq)

    assert await adapter.get_task(callee, "run_nope") is None
    assert await adapter.cancel_task(callee, "run_nope") is None
