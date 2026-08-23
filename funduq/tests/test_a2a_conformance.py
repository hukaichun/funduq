"""funduq's A2A output, judged by A2A's own package instead of by funduq.

Every other assertion about the A2A door in this suite is funduq checking
its own homework: the adapter produces the events and the test, written
beside it, says they look right. That cannot catch a stream that is
well-formed and *invalid* — and one was. Feeding the first text chunk of
any funduq stream to `a2a.server.tasks.task_manager.append_artifact_to_task`
answered:

    InvalidAgentResponseError: append=True for nonexistent artifact_id='m1'
    in task 'task-1'. The artifact must be created (append=False) before
    appending parts to it.

So this file assembles funduq's stream with the package's own aggregator
and lets it be the judge. It is the same move `test_wire_loopback.py`
makes for the provider port and `contract-vectors.json` makes for the
signed payloads: the party deciding whether funduq is right is not funduq.

Importing `a2a.server.*` here is fine and is why the network-free rule is
about verbs — a test is exactly where an outside opinion belongs, and the
static half of that rule scans `funduq/`, not `tests/`.
"""

from __future__ import annotations

import pytest
from a2a.server.tasks.task_manager import append_artifact_to_task
from a2a.types import a2a_pb2 as pb

from funduq.protocols.a2a import A2AAdapter

from tests.conftest import EchoAgent


def _message(text: str) -> dict:
    return {"role": "user", "parts": [{"type": "text", "text": text}]}


def assemble(events) -> pb.Task:
    """Rebuild a task from a funduq stream the way A2A says a receiver must.

    A stream is a **snapshot** — the `Task` itself — followed by increments
    layered onto it. Nothing here is funduq's code: the ordering rule and
    the artifact aggregation are the package's own, and a violation raises
    out of this function rather than being asserted about.
    """
    task: pb.Task | None = None
    for event in events:
        if isinstance(event, pb.Task):
            task = event
            continue
        if task is None:
            raise AssertionError(
                f"a receiver has no task to layer onto: the stream opened with "
                f"{type(event).__name__}, not a Task snapshot"
            )
        if isinstance(event, pb.TaskArtifactUpdateEvent):
            append_artifact_to_task(task, event)
        elif isinstance(event, pb.TaskStatusUpdateEvent):
            task.status.CopyFrom(event.status)
    if task is None:
        raise AssertionError("the stream carried no Task at all")
    return task


@pytest.fixture
async def callee(serve):
    return (await serve(EchoAgent(), "callee")).agents["callee"]


async def test_a_streamed_run_reassembles_under_a2as_own_rules(funduq, callee):
    """The whole point of the file: A2A's own aggregator accepts the stream, and what it
    rebuilds says what the agent said."""
    stream = await A2AAdapter(funduq).send_task_streaming(callee, _message("hi"))

    task = assemble([event async for event in stream])

    assert task.status.state == pb.TaskState.TASK_STATE_COMPLETED
    assert "".join(p.text for a in task.artifacts for p in a.parts)


async def test_resubscribing_reassembles_too(funduq, callee):
    """The other stream out of the A2A door, held to the same rule."""
    adapter = A2AAdapter(funduq)
    sent = await adapter.send_task(callee, _message("hi"))

    task = assemble([e async for e in await adapter.resubscribe_task(callee, sent.id)])

    assert task.id == sent.id
    assert task.status.state == pb.TaskState.TASK_STATE_COMPLETED
