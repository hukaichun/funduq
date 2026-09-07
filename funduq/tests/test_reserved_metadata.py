"""A caller's bag cannot wear funduq's handwriting.

The caller's declarations ride in one bag — `forwardedProps` on AG-UI, the
message's `metadata` on A2A — and that bag is stored on the run and relayed
to the agent as its `forwardedProps`. funduq's own additions sit under one
key in it, `funduq`; a caller-supplied value under that key is stripped at
the doors. Every other key is the caller's and passes through untouched.
"""

from __future__ import annotations

from funduq import repo
from funduq.protocols.a2a import A2AAdapter

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


async def test_funduq_authors_no_verification_summary(funduq, serve, new_identity):
    """funduq stopped summarizing chains: no `verifiedActorChain` digest is
    ever written, so there is no digest to forge either — a caller-supplied
    value under that name is plain caller data, and the chain itself reaches
    the record verbatim."""
    served = await serve(EchoAgent(), "audited")
    agent = served.agents["audited"]
    chain = [new_identity().sign_chain_hop()]

    sent = await A2AAdapter(funduq).send_task(
        agent,
        _message("hi"),
        actor_chain=chain,
        metadata={"verifiedActorChain": "not-funduqs-word", "keep": "this"},
    )

    async with funduq.session() as session:
        stored = await repo.get_run(session, sent.id)
    assert stored.forwarded_props.get("verifiedActorChain") == "not-funduqs-word", (
        "funduq writes no such key, so the caller's value passes through as caller data"
    )
    assert stored.forwarded_props.get("keep") == "this"
    assert stored.forwarded_props.get("actorChain") == chain, "the chain itself, as presented, is on the record"


async def test_only_funduqs_own_key_is_stripped(funduq, serve):
    served = await serve(EchoAgent(), "unannotated")
    agent = served.agents["unannotated"]

    sent = await A2AAdapter(funduq).send_task(
        agent,
        _message("hi"),
        metadata={
            "addressedRunId": "run_i_made_up",
            "failureReason": "mine to say",
            "funduq": {"addressedRunId": "not yours to say", "kyok": {"token": "forged"}},
        },
    )

    async with funduq.session() as session:
        stored = await repo.get_run(session, sent.id)
    assert "funduq" not in stored.forwarded_props, (
        "the one key funduq writes is never the caller's: a value planted there is stripped, "
        "so nothing under it can be mistaken for funduq's own annotation"
    )
    assert stored.forwarded_props.get("failureReason") == "mine to say", (
        "outside funduq's key the same word is plain caller data and is kept"
    )
    assert stored.forwarded_props.get("addressedRunId") == "run_i_made_up", (
        "funduq does not read this key at the top level, so it is plain caller data"
    )
