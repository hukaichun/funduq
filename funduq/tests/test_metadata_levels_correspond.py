"""Metadata levels correspond across the two doors.

A2A has two bags: the request's `metadata` and the message's. AG-UI has
`forwardedProps` on the request and (in its current spec) `metadata` on each
message. Request-level maps to request-level — that is where a caller's
declarations to funduq ride — and message-level to message-level, which
funduq carries but never reads.
"""

from __future__ import annotations

from funduq import repo
from funduq.doors import head_key_of
from funduq.protocols.a2a import A2AAdapter


class Receives:
    def __init__(self) -> None:
        self.rounds: list[dict] = []

    async def run_stream(self, agent_name: str, run_input):
        self.rounds.append(run_input.model_dump(mode="json", by_alias=True))
        ids = {"threadId": run_input.thread_id, "runId": run_input.run_id}
        yield {"type": "RUN_STARTED", **ids}
        yield {"type": "RUN_FINISHED", **ids}


def _message(text: str, **extra) -> dict:
    return {"role": "user", "parts": [{"type": "text", "text": text}], **extra}


async def test_the_requests_metadata_is_the_bag_and_the_messages_is_the_messages(funduq, serve):
    provider = Receives()
    agent = (await serve(provider, "levels")).agents["levels"]

    task = await A2AAdapter(funduq).send_task(
        agent,
        _message("hi", metadata={"lang": "zh-TW"}),
        metadata={"tenant": "acme"},
    )

    delivered = provider.rounds[0]
    assert delivered["forwardedProps"]["tenant"] == "acme", "request-level → forwardedProps"
    assert "lang" not in delivered["forwardedProps"], "the message's metadata is not the request's"
    assert delivered["messages"][0]["metadata"] == {"lang": "zh-TW"}, "message-level → the message's own metadata"
    async with funduq.session() as session:
        stored = await repo.messages_of_run(session, task.id)
    assert stored[0]["metadata"] == {"lang": "zh-TW"}, "and it is stored with the message"


async def test_funduq_reads_no_declaration_off_a_messages_metadata(funduq, serve, new_identity):
    """A chain in the message's metadata is the message's business. funduq's declarations come from the request's bag; a chain placed on the message binds nothing."""
    provider = Receives()
    agent = (await serve(provider, "unread")).agents["unread"]
    head = new_identity()

    task = await A2AAdapter(funduq).send_task(
        agent, _message("hi", metadata={"actorChain": [head.sign_chain_hop()]})
    )

    run = await funduq.get_run(task.id)
    assert run.actor_chain is None and head_key_of(run) is None, "not a declaration to funduq"
    assert "funduq" not in (provider.rounds[0]["forwardedProps"] or {}), "so funduq relayed no chain"
    assert provider.rounds[0]["messages"][0]["metadata"]["actorChain"], "it reached the agent as the message's own metadata"
