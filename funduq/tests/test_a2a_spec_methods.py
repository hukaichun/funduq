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
over `A2ARequestHandler` — the `RequestHandler` that forwards to this
adapter, exercised in `test_a2a_request_handler.py` — and gets the names,
the envelopes, the error codes and the version negotiation from the package
that defines them. What stays here is what funduq actually decides, and one
conformance test so a spec change lands as a red test in this repo rather
than in production.
"""

from __future__ import annotations

import asyncio

from typing import get_args

import pytest
from a2a.server.request_handlers.request_handler import RequestHandler
from a2a.types import a2a_pb2 as pb
from a2a.utils.errors import TaskNotCancelableError, TaskNotFoundError
from google.protobuf.json_format import MessageToDict

from funduq.protocols.a2a import PROTOCOL_VERSION, A2AAdapter, ServedInterface
from funduq.protocols.a2a_translate import CANCEL_REQUESTED_METADATA_KEY

from tests.conftest import EchoAgent, publish_offline
from funduq_contract import Registration


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
    registered = await publish_offline(funduq, identity, [Registration(name="versioned", agent_card_extra={"version": "3.1.4"})])

    card = await A2AAdapter(funduq).agent_card(registered["versioned"])

    assert card.version == "3.1.4"


class _NeverFinishes:
    """Starts and then waits, so a cancel meets a run that is genuinely live."""

    async def run_stream(self, agent_name: str, run_input):
        yield {"type": "RUN_STARTED", "threadId": run_input.thread_id, "runId": run_input.run_id}
        await asyncio.Event().wait()


async def test_cancelling_a_live_task_answers_working_and_says_the_request_is_pending(
    funduq, serve
):
    """funduq can ask a provider to stop and cannot make it, so the answer is
    never `canceled` on the strength of the request. It used to be nothing at
    all: `cancelling` had no A2A state, so `status` serialised empty and a
    client reading `status.state` learned neither that its request had landed
    nor that anything was still running (funduq#149).

    `working` is the true thing A2A has a word for, and the marker is what
    separates "asked, not yet answered" from "nothing is happening".
    """
    agent = (await serve(_NeverFinishes(), "slow")).agents["slow"]
    adapter = A2AAdapter(funduq)

    stream = await adapter.send_task_streaming(agent, _message("hi"))
    opening = await stream.__anext__()
    async with asyncio.timeout(5):
        while (await funduq.get_run(opening.id)).status != "running":
            await asyncio.sleep(0.005)

    cancelled = await adapter.cancel_task(agent, opening.id)

    assert cancelled.status.state == pb.TaskState.TASK_STATE_WORKING
    assert _wire(cancelled)["metadata"][CANCEL_REQUESTED_METADATA_KEY] is True


async def test_cancelling_a_task_that_already_ended_is_refused_in_a2as_words(funduq, callee):
    """A2A's own server raises here, and returning the finished task as though
    the request had been accepted is the same unreadable answer in a different
    disguise."""
    adapter = A2AAdapter(funduq)
    done = await adapter.send_task(callee, _message("hi"))
    assert done.status.state == pb.TaskState.TASK_STATE_COMPLETED

    with pytest.raises(TaskNotCancelableError):
        await adapter.cancel_task(callee, done.id)


class _Asks:

    async def run_stream(self, agent_name: str, run_input):
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        yield {
            "type": "RUN_FINISHED",
            **ids,
            "outcome": {
                "type": "interrupt",
                "interrupts": [{"id": "int_1", "reason": "question", "message": "which?"}],
            },
        }


async def test_cancelling_a_paused_task_is_refused_in_the_same_words(funduq, serve):
    """`input-required` is not terminal, so it fell past the check above and
    out through a `cancel_run` that answered False — and the caller got its
    task back unchanged, at the same state, with no pending-cancel marker on
    it. A cancel that reads exactly like never having asked is the failure
    mode the terminal branch exists to prevent, reached by the opposite road.

    Not terminal is not the same as cancellable. funduq's cancel relays the
    request to whoever is working on the run; a paused run's provider already
    ended its stream, so there is nobody to relay to and no outcome to
    observe. `TaskNotCancelableError` is A2A's own word for a task that will
    not reach `CANCELED`, which is what a2a-python raises in the same place.
    """
    agent = (await serve(_Asks(), "asker")).agents["asker"]
    adapter = A2AAdapter(funduq)

    paused = await adapter.send_task(agent, _message("go"))
    assert paused.status.state == pb.TaskState.TASK_STATE_INPUT_REQUIRED

    with pytest.raises(TaskNotCancelableError):
        await adapter.cancel_task(agent, paused.id)

    # And the ask it was still holding is untouched: refusing a cancel must
    # not be a way to settle a run funduq has observed nothing about.
    assert (await funduq.get_run(paused.id)).status == "input-required"


async def test_the_task_carries_the_conversation_as_history(funduq, callee):
    """A2A's Task travels with its conversation; funduq holds the thread's
    messages and the Task now says so — user messages as ROLE_USER, the
    agent's replies as ROLE_AGENT."""
    adapter = A2AAdapter(funduq)
    sent = await adapter.send_task(callee, _message("hi"))

    got = await adapter.get_task(callee, sent.id)

    spoken = [(m.role, m.parts[0].text) for m in got.history]
    assert (pb.Role.ROLE_USER, "hi") in spoken
    assert any(role == pb.Role.ROLE_AGENT for role, _ in spoken)
    assert all(m.context_id == got.context_id for m in got.history)


async def test_the_opening_snapshot_already_carries_the_callers_message(funduq, callee):
    """Inbound messages are persisted at the door, before any provider runs —
    so the stream's opening Task can already show the caller what the thread
    holds."""
    stream = await A2AAdapter(funduq).send_task_streaming(callee, _message("hi"))

    events = [event async for event in stream]

    opening = events[0]
    assert any(
        m.role == pb.Role.ROLE_USER and m.parts[0].text == "hi"
        for m in opening.history
    )


async def test_return_immediately_answers_before_the_run_finishes(funduq, serve):
    """The polling road: send, get a snapshot at once, poll `get_task` to a
    terminal state. funduq's queued lane makes `submitted` a state with real
    duration, and this is how a polling caller learns that is where its run is."""

    class Holding:
        def __init__(self) -> None:
            self.release = asyncio.Event()

        async def run_stream(self, agent_name, run_input):
            ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
            yield {"type": "RUN_STARTED", **ids}
            await self.release.wait()
            yield {"type": "RUN_FINISHED", **ids}

    provider = Holding()
    served = await serve(provider, "slow")
    adapter = A2AAdapter(funduq)

    async with asyncio.timeout(5):
        task = await adapter.send_task(
            served.agents["slow"], _message("hi"), return_immediately=True
        )

    assert task.status.state in (
        pb.TaskState.TASK_STATE_SUBMITTED,
        pb.TaskState.TASK_STATE_WORKING,
    )
    assert any(m.parts[0].text == "hi" for m in task.history)

    provider.release.set()
    async with asyncio.timeout(5):
        while True:
            got = await adapter.get_task(served.agents["slow"], task.id)
            if got.status.state == pb.TaskState.TASK_STATE_COMPLETED:
                break
            await asyncio.sleep(0.02)


async def test_history_length_keeps_the_last_messages(funduq, callee):
    adapter = A2AAdapter(funduq)
    sent = await adapter.send_task(callee, _message("hi"))
    assert len(sent.history) >= 2, "one exchange stores at least two messages"

    trimmed = await adapter.get_task(callee, sent.id, history_length=1)

    assert len(trimmed.history) == 1
    assert trimmed.history[0].role == pb.Role.ROLE_AGENT


async def test_an_unknown_context_id_is_a2as_own_error_not_a_new_thread(funduq, callee):
    """Thread ids are funduq-minted on both doors; a caller's own string
    never addresses state. The doors differ only in what an unknown id can
    mean: A2A's contextId is optional, so omitting it already says "new
    conversation" and a present-but-unknown id can only be a mistake. AG-UI's
    thread_id is required — an unseen id is the only way that protocol can
    say "new" — so its door mints a fresh thread instead (see
    test_agui_adapter.py)."""
    from a2a.utils.errors import InvalidParamsError

    with pytest.raises(InvalidParamsError):
        await A2AAdapter(funduq).send_task(
            callee, {**_message("hi"), "contextId": "ctx-invented"}
        )
