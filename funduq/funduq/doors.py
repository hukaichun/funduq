from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from funduq import repo
from ag_ui.core import RunErrorEvent, RunStartedEvent

from funduq.agui import build_run_agent_input
from funduq.ids import new_id
from funduq.errors import InvalidRunInput, LlmProviderNotFound
from funduq.identity import (
    InvalidChain,
    verify_chain,
    verify_cancel,
    verify_resolution,
    verify_view,
)
from funduq.kyok import KyokBinding, KyokOptIn, parse_kyok_opt_in
from funduq.models import AgentRef
from funduq.props import RESERVED_METADATA_KEYS, build_forwarded_props

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from funduq.core import Funduq

__all__ = [
    "InboundRun",
    "Opened",
    "PendingAsk",
    "authorize_cancel",
    "dispatch",
    "offline_events",
    "open_run",
    "relayed_chain",
    "resolve_kyok",
    "verify_caller",
]


def relayed_chain(funduq: "Funduq", chain: Any, agent: AgentRef) -> Any:
    """The chain as it will leave funduq: the caller's, plus one hop funduq signs for the dispatch it is making, naming where the run went."""
    return funduq.identity.dispatch_hop(chain, agent) if chain else chain


async def verify_caller(
    session: "AsyncSession", metadata: dict, *, presenter_key: str | None = None
) -> tuple[dict, str | None, Any]:
    """Verifies `metadata["actorChain"]` if present and returns `(metadata stripped of funduq's reserved keys, the chain's head key, the raw chain)` — `(metadata, None, None)` when no chain is attached."""
    metadata = {k: v for k, v in metadata.items() if k not in RESERVED_METADATA_KEYS}
    actor_chain = metadata.get("actorChain")
    if not actor_chain:
        return metadata, None, None
    verified = verify_chain(actor_chain)
    if presenter_key is not None and presenter_key != verified.presenter:
        raise InvalidChain(
            "the chain's last hop was signed by "
            f"{verified.presenter[:16]}…, but the caller authenticated as "
            f"{presenter_key[:16]}… — extend the chain with your own key to present it"
        )
    return metadata, verified.head, actor_chain


async def resolve_kyok(
    session: "AsyncSession", metadata: dict
) -> tuple[dict, KyokOptIn | None]:
    """Reads a KYOK opt-in out of `metadata` and returns `(metadata, the opt-in or None)`. The opt-in stays in the metadata, context included: it is ordinary content of the run's record, and a restart rebuilds the binding from it."""
    opt_in = parse_kyok_opt_in(metadata)
    if opt_in is not None and opt_in.llm_provider is not None:
        if await repo.get_llm_provider(session, opt_in.llm_provider) is None:
            raise LlmProviderNotFound(f"unknown KYOK LLM provider '{opt_in.llm_provider}'")
    return metadata, opt_in


@dataclass(frozen=True)
class InboundRun:
    """One run as a door has translated it, before funduq has decided anything."""

    agent: AgentRef
    messages: list[dict[str, Any]]
    metadata: dict[str, Any]
    head_key: str | None = None
    actor_chain: Any = None
    kyok: KyokOptIn | None = None
    addressed_run_id: str | None = None
    state: Any = None
    tools: list[dict[str, Any]] | None = None
    context: list[dict[str, Any]] | None = None
    resume: list[dict[str, Any]] | None = None
    parent_run_id: str | None = None
    forwarded_props: Any = None
    protocol: str = "ag-ui"

    @property
    def kyok_ref(self) -> Any:
        return self.kyok.llm_provider if self.kyok is not None else None


async def dispatch(
    funduq: "Funduq",
    session: "AsyncSession",
    inbound: InboundRun,
    opened: Opened,
) -> bool:
    """Hands an opened run to the broker with the input its row holds; False if nobody serves its agent, in which case the row is failed `agent_offline`."""
    kyok_ref = inbound.kyok_ref
    if kyok_ref is not None:
        funduq.kyok_relay.bind_run(
            opened.run_id,
            KyokBinding(
                llm_provider=kyok_ref,
                context=inbound.kyok.context,
                actor_chain=inbound.actor_chain,
            ),
        )
    if (
        funduq.enqueue_run(
            opened.run_id,
            inbound.agent,
            opened.thread_id,
            opened.input_json,
            inbound.protocol,
            seq=opened.starting_seq,
            addressed_run_id=inbound.addressed_run_id,
        )
        is None
    ):
        funduq.kyok_relay.discard(opened.run_id)
        await funduq.mark_run_status(
            session, opened.run_id, "failed", metadata={"failureReason": "agent_offline"}
        )
        await session.commit()
        return False
    return True


@dataclass(frozen=True)
class PendingAsk:
    """The paused run a result would land on, the key authorized to answer it,
    and the outstanding ask ids a resolution proof must sign."""

    run_id: str
    head_key: str | None
    ask_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Opened:
    """The run a request resolved to — a reopened ask, or a fresh one on the thread — and the input its row now holds, which is exactly what the provider will receive."""

    run_id: str
    thread_id: str
    starting_seq: int
    input_json: dict[str, Any]


def authorize_cancel(run: Any, metadata: dict[str, Any]) -> str | None:
    """Refuses a cancel that carries no authority over a run whose thread is bound, and returns the authority that asked (`None` for an unbound run)."""
    if run.head_key is None:
        return None
    return verify_cancel(
        metadata.get("cancel") or {},
        run.run_id,
        {run.head_key, run.provider_key},
    )


def authorize_view(run: Any, metadata: dict[str, Any]) -> str | None:
    """Refuses a read of a bound run that carries no view proof from one of its parties, and returns the authority that asked (`None` for an unbound run).

    The read circle is wider than the act circle: every actor on the run's
    chain may look — responsibility flowed through them — while cancel and
    resolve stay with the head and the serving provider. An unbound run has
    no parties to scope to and stays as public as its funduq-minted id.
    """
    if run.head_key is None:
        return None
    allowed = {run.head_key, run.provider_key}
    if run.actor_chain:
        allowed |= set(verify_chain(run.actor_chain).actor_public_keys)
    return verify_view(
        metadata.get("view") or {},
        run.run_id,
        allowed,
    )


async def open_run(
    funduq: "Funduq",
    session: "AsyncSession",
    inbound: InboundRun,
    *,
    thread_id: str,
    entrance: Literal["utterance", "result"],
    ask: PendingAsk | None,
) -> Opened | None:
    """Resolves a request to the run it belongs on — the pending ask it answers, or a new run queued on the thread — and writes that run's row with the `RunAgentInput` its provider will receive.

    One form in the database: the row holds the delivered input, from either
    door. So the ids are taken first (the ask claimed or a fresh run id
    minted, the turn's messages stamped), the input is built naming them,
    and only then are the row and the messages written — in one commit.
    """
    if inbound.addressed_run_id is not None:
        target = funduq.broker.get(inbound.addressed_run_id)
        if target is None or target.thread_id != thread_id:
            raise InvalidRunInput(
                f"interjection names '{inbound.addressed_run_id}', which is not a "
                "live run on this thread"
            )

    answered_by = None
    landed_on_ask = False
    if ask is not None:
        if ask.head_key is not None:
            # A chained ask names its authorities; the resolution must be signed by one of them, over exactly the asks still open.
            answered_by = verify_resolution(
                inbound.metadata.get("resolution") or {},
                ask.run_id,
                set(ask.ask_ids),
                {ask.head_key, inbound.agent.provider_key},
            )
        landed_on_ask = await repo.claim_ask(session, ask.run_id)
    if landed_on_ask:
        run_id = ask.run_id
        starting_seq = await repo.get_last_event_seq(session, run_id)
    elif entrance == "result":
        return None
    else:
        await repo.ensure_queue_room(session, thread_id, funduq.settings.thread_queue_limit)
        run_id = new_id("run")
        starting_seq = 0

    messages = repo.stamp_messages(inbound.messages)
    try:
        input_json = build_run_agent_input(
            thread_id,
            run_id,
            messages,
            state=inbound.state,
            tools=inbound.tools,
            context=inbound.context,
            forwarded_props=build_forwarded_props(
                funduq.settings.token_signing_secret,
                run_id,
                inbound.agent,
                inbound.kyok_ref is not None,
                inbound.forwarded_props,
                # Relayed exactly as handed in.
                inbound.actor_chain,
                addressed_run_id=inbound.addressed_run_id,
            ),
            resume=inbound.resume,
            parent_run_id=inbound.parent_run_id,
        )
    except ValueError as e:
        raise InvalidRunInput(str(e)) from e

    if landed_on_ask:
        await repo.reopen_run(
            session, run_id, input_json, metadata=inbound.metadata, answered_by=answered_by
        )
    else:
        await repo.create_run(
            session, thread_id, inbound.agent, inbound.protocol, input_json,
            metadata=inbound.metadata, head_key=inbound.head_key,
            actor_chain=inbound.actor_chain, run_id=run_id,
        )
    await repo.append_thread_messages(session, thread_id, run_id, messages)
    await session.commit()
    return Opened(run_id=run_id, thread_id=thread_id, starting_seq=starting_seq, input_json=input_json)


async def offline_events(thread_id: str, run_id: str) -> AsyncIterator[dict[str, Any]]:
    """The stream a run gets when its agent is registered but nobody is serving it."""
    yield RunStartedEvent(thread_id=thread_id, run_id=run_id).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    yield RunErrorEvent(message="agent is currently offline").model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
