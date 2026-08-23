"""The A2A door's operations, called as operations.

funduq used to hand-write JSON-RPC here: envelopes, a table of every method
name the spec has ever used, and the two error codes. All of it is gone, and
the reason is not tidiness — it could not be correct from this seat.
**Which protocol version a request speaks rides an `A2A-Version` HTTP
header** (absent means 0.3, measured against `a2a-sdk 1.1.2`), and core never
sees headers. So the hand-written table answered v1.0 method names to every
client regardless of what it declared, and answered v0.3's names with v1.0's
shapes — which a v0.3 client rejects outright.

A transport mounts `a2a.server.routes.jsonrpc_dispatcher.JsonRpcDispatcher`
over a `RequestHandler` that forwards to this adapter, and gets the names,
the envelopes, the error codes and the version negotiation from the package
that defines them. What stays here is what funduq actually decides, and one
conformance test so a spec change lands as a red test in this repo rather
than in production.
"""

from __future__ import annotations

from typing import get_args

import pytest
from a2a.server.request_handlers.request_handler import RequestHandler
from a2a.types import a2a_pb2 as pb
from a2a.utils.errors import TaskNotFoundError
from google.protobuf.json_format import MessageToDict

from funduq.protocols.a2a import PROTOCOL_VERSION, A2AAdapter, ServedInterface

from tests.conftest import EchoAgent


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


def _wire(message) -> dict:
    return MessageToDict(message)


@pytest.fixture
async def callee(serve):
    return (await serve(EchoAgent(), "callee")).agents["callee"]


# Every operation A2A's own request-handler interface declares, and what
# funduq answers it with. A rename upstream fails the import; an addition
# fails the assertion, which is the point — a new A2A operation should
# arrive as a decision to make, not as silence.
OFFERED = {
    "on_message_send": "send_task",
    "on_message_send_stream": "send_task_streaming",
    "on_get_task": "get_task",
    "on_cancel_task": "cancel_task",
    "on_subscribe_to_task": "resubscribe_task",
}

NOT_OFFERED = {
    # Push notifications: funduq pushes nothing outward on a caller's behalf.
    "on_create_task_push_notification_config",
    "on_get_task_push_notification_config",
    "on_list_task_push_notification_configs",
    "on_delete_task_push_notification_config",
    # Listing tasks and the extended card are the gateway's to answer if it
    # wants them; core exposes the roster its own way.
    "on_list_tasks",
    "on_get_extended_agent_card",
}


def test_every_a2a_operation_is_either_offered_or_deliberately_not():
    assert set(RequestHandler.__abstractmethods__) == set(OFFERED) | NOT_OFFERED
    for operation, method in OFFERED.items():
        assert callable(getattr(A2AAdapter, method)), operation


def test_the_streams_yield_types_a2a_calls_events():
    """`a2a.server.events.Event` is what a request handler yields, and it is a type alias over
    four protobuf messages — vocabulary, not I/O (importing it pulls in no transport module at
    all, checked). funduq's streams must stay inside it, because a transport wraps them with
    the package's own `to_stream_response` and would have nothing to wrap otherwise."""
    from a2a.server.events import Event

    assert set(get_args(Event)) >= {pb.TaskStatusUpdateEvent, pb.TaskArtifactUpdateEvent}


async def test_sending_a_message_settles_the_task(funduq, callee):
    task = await A2AAdapter(funduq).send_task(callee, _message("hi"))

    assert task.status.state == pb.TaskState.TASK_STATE_COMPLETED


async def test_streaming_opens_with_the_task_then_yields_a2as_own_events(funduq, callee):
    """A2A carries a task as a **snapshot** followed by increments layered onto it, so the
    stream opens with the `Task` itself — a receiver handed a status update first has nothing
    to layer onto. Whether the layering then works is not asserted here; it is checked by A2A's
    own aggregator in `tests/test_a2a_conformance.py`."""
    stream = await A2AAdapter(funduq).send_task_streaming(callee, _message("hi"))

    events = [event async for event in stream]

    assert isinstance(events[0], pb.Task)
    assert all(
        isinstance(e, pb.TaskStatusUpdateEvent | pb.TaskArtifactUpdateEvent)
        for e in events[1:]
    )
    assert events[-1].status.state == pb.TaskState.TASK_STATE_COMPLETED


async def test_get_returns_the_task_that_was_sent(funduq, callee):
    adapter = A2AAdapter(funduq)
    sent = await adapter.send_task(callee, _message("hi"))

    got = await adapter.get_task(callee, sent.id)

    assert got.id == sent.id


async def test_a_task_of_another_agent_is_simply_not_found(funduq, callee, serve):
    other = (await serve(EchoAgent(), "stranger")).agents["stranger"]
    adapter = A2AAdapter(funduq)
    sent = await adapter.send_task(callee, _message("hi"))

    assert await adapter.get_task(other, sent.id) is None
    assert await adapter.cancel_task(other, sent.id) is None


async def test_context_id_is_read_off_the_message(funduq, callee):
    adapter = A2AAdapter(funduq)
    first = await adapter.send_task(callee, _message("hi"))

    second = await adapter.send_task(
        callee, {**_message("again"), "contextId": first.context_id}
    )

    assert second.context_id == first.context_id
    assert second.id != first.id


async def test_task_id_on_the_message_continues_that_task(funduq, callee):
    adapter = A2AAdapter(funduq)
    first = await adapter.send_task(callee, _message("hi"))

    second = await adapter.send_task(callee, {**_message("again"), "taskId": first.id})

    assert second.context_id == first.context_id


async def test_an_unknown_task_id_is_task_not_found_not_a_fresh_thread(funduq, callee):
    """And it is A2A's own error type, so a transport maps it without a table of funduq's."""
    with pytest.raises(TaskNotFoundError):
        await A2AAdapter(funduq).send_task(callee, {**_message("hi"), "taskId": "run_nope"})


async def test_subscribing_to_a_finished_task_reports_its_outcome(funduq, callee):
    adapter = A2AAdapter(funduq)
    sent = await adapter.send_task(callee, _message("hi"))

    events = [event async for event in await adapter.resubscribe_task(callee, sent.id)]

    assert events[-1].status.state == pb.TaskState.TASK_STATE_COMPLETED


async def test_subscribing_to_an_unknown_task_is_task_not_found(funduq, callee):
    with pytest.raises(TaskNotFoundError):
        await A2AAdapter(funduq).resubscribe_task(callee, "run_nope")


async def test_the_agent_card_says_which_spec_this_endpoint_speaks(funduq, callee):
    served = ServedInterface(url="https://funduq.example/a2a/ab12/callee/rpc", binding="JSONRPC")
    card = await A2AAdapter(funduq).agent_card(callee, interfaces=[served])

    assert PROTOCOL_VERSION == "1.0"
    assert _wire(card)["supportedInterfaces"] == [
        {
            "url": "https://funduq.example/a2a/ab12/callee/rpc",
            "protocolBinding": "JSONRPC",
            "protocolVersion": "1.0",
        }
    ]
    assert card.capabilities.streaming is True


async def test_a_card_for_a_funduq_nobody_serves_advertises_nowhere(funduq, callee):
    card = await A2AAdapter(funduq).agent_card(callee)

    assert "supportedInterfaces" not in _wire(card)
    assert card.capabilities.streaming is True


async def test_the_agent_card_carries_the_agents_own_version(funduq):
    from tests.conftest import Identity

    identity = Identity()
    signature, timestamp = identity.sign_registration(["versioned"])
    registered = await funduq.register_agents(
        identity.public_key,
        signature,
        timestamp,
        [{"name": "versioned", "agent_card_extra": {"version": "3.1.4"}}],
    )

    card = await A2AAdapter(funduq).agent_card(registered.agents["versioned"])

    assert card.version == "3.1.4"
