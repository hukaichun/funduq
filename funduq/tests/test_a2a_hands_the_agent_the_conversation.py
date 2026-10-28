"""An A2A caller sends only what is new; the agent is handed the whole conversation, as an
AG-UI caller would send it, so it cannot tell which door a run came through."""

from __future__ import annotations

from uuid import uuid4

import pytest
from a2a.utils.errors import InvalidParamsError

from funduq.protocols.a2a import A2AAdapter


class Recording:
    """Replies `re: <last message>`, and fails the run when told to."""

    def __init__(self) -> None:
        self.inputs: list = []

    async def run_stream(self, agent_name: str, run_input):
        self.inputs.append(run_input)
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        said = run_input.messages[-1].content
        yield {"type": "RUN_STARTED", **ids}
        if said == "fail":
            yield {"type": "RUN_ERROR", "message": "told to"}
            return
        reply = f"reply-{run_input.run_id}"
        yield {"type": "TEXT_MESSAGE_START", "messageId": reply, "role": "assistant"}
        yield {"type": "TEXT_MESSAGE_CONTENT", "messageId": reply, "delta": f"re: {said}"}
        yield {"type": "TEXT_MESSAGE_END", "messageId": reply}
        yield {"type": "RUN_FINISHED", **ids}


def _message(text: str, context_id: str | None = None) -> dict:
    message = {"messageId": uuid4().hex, "role": "user", "parts": [{"type": "text", "text": text}]}
    if context_id is not None:
        message["contextId"] = context_id
    return message


async def test_the_next_message_arrives_with_the_conversation_before_it(funduq, serve):
    provider = Recording()
    agent = (await serve(provider, "a")).agents["a"]
    adapter = A2AAdapter(funduq)

    first = await adapter.send_task(agent, _message("one"))
    await adapter.send_task(agent, _message("two", first.context_id))

    assert [(m.role, m.content) for m in provider.inputs[1].messages] == [
        ("user", "one"), ("assistant", "re: one"), ("user", "two"),
    ]


async def test_a_failed_run_leaves_the_conversation(funduq, serve):
    provider = Recording()
    agent = (await serve(provider, "a")).agents["a"]
    adapter = A2AAdapter(funduq)

    first = await adapter.send_task(agent, _message("fail"))
    await adapter.send_task(agent, _message("two", first.context_id))

    assert [m.content for m in provider.inputs[1].messages] == ["two"]


async def test_a_tasks_history_is_its_own_messages_not_the_contexts(funduq, serve):
    agent = (await serve(Recording(), "a")).agents["a"]
    adapter = A2AAdapter(funduq)

    first = await adapter.send_task(agent, _message("one"))
    second = await adapter.send_task(agent, _message("two", first.context_id))

    task = await adapter.get_task(agent, second.id)
    assert [p.text for m in task.history for p in m.parts] == ["two", "re: two"]


async def test_a_message_without_its_id_is_refused(funduq, serve):
    agent = (await serve(Recording(), "a")).agents["a"]

    with pytest.raises(InvalidParamsError):
        await A2AAdapter(funduq).send_task(agent, {"role": "user", "parts": [{"type": "text", "text": "hi"}]})
