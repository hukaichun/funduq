from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from funduq import repo
from ag_ui.core import RunErrorEvent, RunStartedEvent

from funduq.agui import build_run_agent_input
from funduq.errors import InvalidRunInput, LlmProviderNotFound
from funduq.identity import (
    InvalidChain,
    verify_chain,
    verify_cancel,
    verify_delegation,
    verify_resolution,
    verify_view,
)
from funduq.kyok import KyokBinding, KyokOptIn, parse_kyok_opt_in, strip_kyok_context
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
    head = verified.head
    delegation = metadata.get("delegation")
    if delegation is not None:
        authority = verify_delegation(delegation)
        if delegation.get("delegatePublicKey") == head:
            head = authority
    return metadata, head, actor_chain


async def resolve_kyok(
    session: "AsyncSession", metadata: dict
) -> tuple[dict, KyokOptIn | None]:
    """Reads a KYOK opt-in out of `metadata` and returns `(metadata with the caller's KYOK context removed, the opt-in or None)`."""
    opt_in = parse_kyok_opt_in(metadata)
    if opt_in is not None and opt_in.llm_provider is not None:
        if await repo.get_llm_provider(session, opt_in.llm_provider) is None:
            raise LlmProviderNotFound(f"unknown KYOK LLM provider '{opt_in.llm_provider}'")
    return strip_kyok_context(metadata), opt_in


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
    *,
    thread_id: str,
    run_id: str,
    starting_seq: int,
) -> bool:
    """Appends the inbound messages to the thread, builds the provider's AG-UI input, commits, and hands the run to the broker."""
    if inbound.addressed_run_id is not None:
        target = funduq.broker.get(inbound.addressed_run_id)
        if target is None or target.thread_id != thread_id:
            raise InvalidRunInput(
                f"interjection names '{inbound.addressed_run_id}', which is not a "
                "live run on this thread"
            )

    messages = await repo.append_thread_messages(
        session, thread_id, run_id, inbound.messages
    )

    kyok_ref = inbound.kyok_ref

    # Relayed exactly as handed in.
    relayed_chain = inbound.actor_chain

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
                kyok_ref is not None,
                inbound.forwarded_props,
                relayed_chain,
                addressed_run_id=inbound.addressed_run_id,
                delegation=inbound.metadata.get("delegation"),
            ),
            resume=inbound.resume,
            parent_run_id=inbound.parent_run_id,
        )
    except ValueError as e:
        raise InvalidRunInput(str(e)) from e

    await session.commit()

    if kyok_ref is not None:
        funduq.kyok_relay.bind_run(
            run_id,
            KyokBinding(
                llm_provider=kyok_ref,
                context=inbound.kyok.context,
                actor_chain=inbound.actor_chain,
            ),
        )
    if (
        funduq.enqueue_run(
            run_id,
            inbound.agent,
            thread_id,
            input_json,
            inbound.protocol,
            seq=starting_seq,
            addressed_run_id=inbound.addressed_run_id,
        )
        is None
    ):
        funduq.kyok_relay.discard(run_id)
        await funduq.mark_run_status(
            session, run_id, "failed", metadata={"failureReason": "agent_offline"}
        )
        await session.commit()
        return False
    return True


@dataclass(frozen=True)
class PendingAsk:
    """The paused run a result would land on, and the key authorized to answer it."""

    run_id: str
    head_key: str | None


@dataclass(frozen=True)
class Opened:
    """The run a request resolved to: a reopened ask, or a fresh one on the thread."""

    run_id: str
    starting_seq: int
    landed_on_ask: bool


def authorize_cancel(run: Any, metadata: dict[str, Any]) -> str | None:
    """Refuses a cancel that carries no authority over a run whose thread is bound, and returns the authority that asked (`None` for an unbound run)."""
    if run.head_key is None:
        return None
    return verify_cancel(
        metadata.get("cancel") or {},
        run.run_id,
        {run.head_key, run.provider_key},
        metadata.get("delegation"),
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
        metadata.get("delegation"),
    )


async def open_run(
    funduq: "Funduq",
    session: "AsyncSession",
    *,
    agent: AgentRef,
    thread_id: str,
    entrance: Literal["utterance", "result"],
    ask: PendingAsk | None,
    run_input: dict[str, Any],
    metadata: dict[str, Any],
    head_key: str | None,
    protocol: str,
    actor_chain: Any = None,
) -> Opened | None:
    """Resolves a request to the run it belongs on: the pending ask it answers, or a new run queued on the thread."""
    if ask is not None:
        answered_by = None
        if ask.head_key is not None:
            answered_by = verify_resolution(
                metadata.get("resolution") or {},
                ask.run_id,
                {ask.head_key, agent.provider_key},
                metadata.get("delegation"),
            )
        if await repo.reopen_run(
            session,
            ask.run_id,
            run_input,
            metadata=metadata,
            expected_status="input-required",
            answered_by=answered_by,
        ):
            return Opened(
                run_id=ask.run_id,
                starting_seq=await repo.get_last_event_seq(session, ask.run_id),
                landed_on_ask=True,
            )

    if entrance == "result":
        return None

    await repo.ensure_queue_room(session, thread_id, funduq.settings.thread_queue_limit)
    created = await repo.create_run(
        session, thread_id, agent, protocol, run_input,
        metadata=metadata, head_key=head_key, actor_chain=actor_chain,
    )
    return Opened(run_id=created["run_id"], starting_seq=0, landed_on_ask=False)


async def offline_events(thread_id: str, run_id: str) -> AsyncIterator[dict[str, Any]]:
    """The stream a run gets when its agent is registered but nobody is serving it."""
    yield RunStartedEvent(thread_id=thread_id, run_id=run_id).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    yield RunErrorEvent(message="agent is currently offline").model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
