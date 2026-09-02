"""The bridge a transport mounts: `RequestHandler` calls in, `A2AAdapter` out.

How far to support the A2A protocol is the transport's decision, not
funduq's: it mounts a2a-sdk's own dispatchers for whichever bindings and
spec versions it chooses, and method names, envelopes, error codes and
version negotiation come from the package that defines them. Every choice
arrives at `A2ARequestHandler` as the same protobuf-typed calls — the ones
exercised here, with no dict crossing the seam in either direction.
"""

from __future__ import annotations

import pytest
from a2a.server.context import ServerCallContext
from a2a.types import a2a_pb2 as pb
from a2a.utils.errors import (
    InvalidParamsError,
    TaskNotCancelableError,
    TaskNotFoundError,
    UnsupportedOperationError,
)

from funduq.models import AgentRef
from funduq.protocols import a2a as a2a_module
from funduq.protocols.a2a import A2ARequestHandler

from tests.conftest import EchoAgent


def _send(text: str) -> pb.SendMessageRequest:
    return pb.SendMessageRequest(
        message=pb.Message(
            message_id="m-in", role=pb.Role.ROLE_USER, parts=[pb.Part(text=text)]
        )
    )


@pytest.fixture
async def handler(funduq, serve):
    served = await serve(EchoAgent(), "callee")
    return A2ARequestHandler(funduq, served.agents["callee"])


async def test_the_bridge_leaves_no_operation_abstract(funduq):
    """Constructing it is the proof: an abstract method left unanswered raises TypeError."""
    A2ARequestHandler(funduq, AgentRef(provider_key="k", name="a"))


async def test_sending_a_message_settles_the_task(funduq, handler):
    task = await handler.on_message_send(_send("hi"), ServerCallContext())

    assert task.status.state == pb.TaskState.TASK_STATE_COMPLETED


async def test_streaming_opens_with_the_task_then_reaches_completed(funduq, handler):
    events = [
        event
        async for event in handler.on_message_send_stream(
            _send("hi"), ServerCallContext()
        )
    ]

    assert isinstance(events[0], pb.Task)
    assert any(
        isinstance(event, pb.TaskStatusUpdateEvent)
        and event.status.state == pb.TaskState.TASK_STATE_COMPLETED
        for event in events
    )


async def test_a_request_missing_its_message_is_a2as_invalid_params(funduq, handler):
    with pytest.raises(InvalidParamsError):
        await handler.on_message_send(pb.SendMessageRequest(), ServerCallContext())


async def test_get_task_answers_none_for_a_task_the_agent_does_not_have(funduq, handler):
    found = await handler.on_get_task(
        pb.GetTaskRequest(id="t-none"), ServerCallContext()
    )

    assert found is None


async def test_cancelling_a_settled_task_is_a2as_own_error(funduq, handler):
    task = await handler.on_message_send(_send("hi"), ServerCallContext())

    with pytest.raises(TaskNotCancelableError):
        await handler.on_cancel_task(
            pb.CancelTaskRequest(id=task.id), ServerCallContext()
        )


async def test_subscribing_to_an_unknown_task_is_a2as_own_error(funduq, handler):
    with pytest.raises(TaskNotFoundError):
        async for _ in handler.on_subscribe_to_task(
            pb.SubscribeToTaskRequest(id="t-none"), ServerCallContext()
        ):
            pass


@pytest.mark.parametrize(
    ("operation", "request_"),
    [
        ("on_create_task_push_notification_config", pb.TaskPushNotificationConfig()),
        ("on_get_task_push_notification_config", pb.GetTaskPushNotificationConfigRequest()),
        ("on_list_task_push_notification_configs", pb.ListTaskPushNotificationConfigsRequest()),
        ("on_delete_task_push_notification_config", pb.DeleteTaskPushNotificationConfigRequest()),
        ("on_list_tasks", pb.ListTasksRequest()),
        ("on_get_extended_agent_card", pb.GetExtendedAgentCardRequest()),
    ],
)
async def test_what_is_not_offered_answers_unsupported_operation(
    handler, operation, request_
):
    with pytest.raises(UnsupportedOperationError):
        await getattr(handler, operation)(request_, ServerCallContext())


async def test_the_transports_authenticated_identity_is_handed_down(
    funduq, serve, monkeypatch
):
    """The transport authenticates whoever presents a request; `presenter_key_of` is where it says so, and the key must reach the adapter as `presenter_key`."""
    served = await serve(EchoAgent(), "callee")
    seen: dict = {}
    original = a2a_module.A2AAdapter.send_task

    async def spy(self, agent, message, **kwargs):
        seen["presenter_key"] = kwargs.get("presenter_key")
        return await original(self, agent, message, **kwargs)

    monkeypatch.setattr(a2a_module.A2AAdapter, "send_task", spy)
    handler = A2ARequestHandler(
        funduq,
        served.agents["callee"],
        presenter_key_of=lambda context: context.state.get("presenter"),
    )

    await handler.on_message_send(
        _send("hi"), ServerCallContext(state={"presenter": "pk-of-the-hop"})
    )

    assert seen["presenter_key"] == "pk-of-the-hop"
