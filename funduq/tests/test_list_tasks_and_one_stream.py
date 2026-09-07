"""A2A `ListTasks` (§3.1.4), and one stream per task (§3.5.2).

Listing is scoped by `contextId`: the id a caller holds is what makes a
thread's tasks visible to it on an unbound thread, and on a bound thread the
reader must be a party — the same rule every read takes (#264). Without a
`contextId` nothing is visible and the page is empty. A task's stream is
served once: a second subscriber is refused rather than handed half the
events.
"""

from __future__ import annotations

import asyncio

import pytest
from a2a.server.context import ServerCallContext
from a2a.types import a2a_pb2 as pb
from a2a.utils.errors import UnsupportedOperationError

from funduq.protocols.a2a import A2AAdapter, A2ARequestHandler

from tests.conftest import EchoAgent

COMPLETED = pb.TaskState.TASK_STATE_COMPLETED


def _message(text: str, **extra) -> dict:
    return {"role": "user", "parts": [{"type": "text", "text": text}], **extra}


async def _three_tasks(funduq, agent):
    adapter = A2AAdapter(funduq)
    first = await adapter.send_task(agent, _message("one"))
    second = await adapter.send_task(agent, _message("two", contextId=first.context_id))
    third = await adapter.send_task(agent, _message("three", contextId=first.context_id))
    return adapter, first.context_id, [first.id, second.id, third.id]


async def test_a_context_lists_its_tasks_newest_first(funduq, serve):
    agent = (await serve(EchoAgent(), "lister")).agents["lister"]
    adapter, context_id, ids = await _three_tasks(funduq, agent)

    page = await adapter.list_tasks(agent, context_id=context_id)

    assert [t.id for t in page.tasks] == list(reversed(ids)), "status timestamp descending"
    assert page.total_size == 3 and page.page_size == 3
    assert page.next_page_token == "", "always present; empty when there is no more"
    assert all(t.status.state == COMPLETED for t in page.tasks)
    assert all(not t.artifacts for t in page.tasks), "artifacts are omitted unless asked for"


async def test_without_a_context_id_nothing_is_visible(funduq, serve):
    agent = (await serve(EchoAgent(), "lister")).agents["lister"]
    adapter, _, _ = await _three_tasks(funduq, agent)

    page = await adapter.list_tasks(agent, context_id=None)

    assert list(page.tasks) == [] and page.total_size == 0 and page.next_page_token == ""


async def test_pages_are_cursor_paged_and_the_last_page_says_so(funduq, serve):
    agent = (await serve(EchoAgent(), "lister")).agents["lister"]
    adapter, context_id, ids = await _three_tasks(funduq, agent)

    first = await adapter.list_tasks(agent, context_id=context_id, page_size=2)
    assert [t.id for t in first.tasks] == [ids[2], ids[1]]
    assert first.next_page_token != "" and first.total_size == 3

    rest = await adapter.list_tasks(agent, context_id=context_id, page_size=2, page_token=first.next_page_token)
    assert [t.id for t in rest.tasks] == [ids[0]]
    assert rest.next_page_token == ""


async def test_status_and_artifacts_are_honoured(funduq, serve):
    agent = (await serve(EchoAgent(), "lister")).agents["lister"]
    adapter, context_id, ids = await _three_tasks(funduq, agent)

    none = await adapter.list_tasks(agent, context_id=context_id, status=pb.TaskState.TASK_STATE_WORKING)
    assert list(none.tasks) == []

    with_art = await adapter.list_tasks(agent, context_id=context_id, include_artifacts=True)
    assert all(t.artifacts for t in with_art.tasks), "EchoAgent says 'done' on every task"


async def test_a_bound_context_lists_only_for_its_parties(funduq, serve, new_identity):
    served = await serve(EchoAgent(), "bound")
    agent = served.agents["bound"]
    head, stranger = new_identity(), new_identity()
    adapter = A2AAdapter(funduq)
    task = await adapter.send_task(
        agent, _message("hi"), actor_chain=[head.sign_chain_hop()], presenter_key=head.public_key
    )

    assert list((await adapter.list_tasks(agent, context_id=task.context_id)).tasks) == [], "nobody"
    assert list((await adapter.list_tasks(agent, context_id=task.context_id, reader=stranger.public_key)).tasks) == []
    for party in (head, served.identity):
        page = await adapter.list_tasks(agent, context_id=task.context_id, reader=party.public_key)
        assert [t.id for t in page.tasks] == [task.id]


async def test_the_handler_reads_the_request_fields(funduq, serve):
    agent = (await serve(EchoAgent(), "lister")).agents["lister"]
    _, context_id, ids = await _three_tasks(funduq, agent)
    handler = A2ARequestHandler(funduq, agent)

    response = await handler.on_list_tasks(
        pb.ListTasksRequest(context_id=context_id, page_size=1, include_artifacts=True), ServerCallContext()
    )
    assert [t.id for t in response.tasks] == [ids[2]]
    assert response.next_page_token == "1"
    assert response.tasks[0].artifacts


class _Holds:
    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def run_stream(self, agent_name: str, run_input):
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        await self.release.wait()
        yield {"type": "RUN_FINISHED", **ids}


async def test_a_second_stream_on_one_task_is_refused(funduq, serve):
    """§3.5.2 leaves serving several streams a MAY; funduq serves one. A second
    subscriber would take half the events off the one queue, so it is refused
    in A2A's words instead."""
    provider = _Holds()
    agent = (await serve(provider, "holder")).agents["holder"]
    adapter = A2AAdapter(funduq)

    stream = await adapter.send_task_streaming(agent, _message("hi"))
    opening = await stream.__anext__()

    with pytest.raises(UnsupportedOperationError):
        await adapter.resubscribe_task(agent, opening.id)

    provider.release.set()
    events = [e async for e in stream]
    assert events, "the first stream was untouched by the refusal"


async def test_a_stream_nobody_holds_can_be_taken(funduq, serve):
    provider = _Holds()
    agent = (await serve(provider, "holder")).agents["holder"]
    adapter = A2AAdapter(funduq)

    opening = await adapter.send_task(agent, _message("hi"), return_immediately=True)
    stream = await adapter.resubscribe_task(agent, opening.id)
    provider.release.set()
    events = [e async for e in stream]

    assert events[-1].status.state == COMPLETED
