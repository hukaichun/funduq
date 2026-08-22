from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from funduq import repo
from funduq.agui import build_run_agent_input
from funduq.errors import InvalidRunInput, LlmProviderNotFound
from funduq.identity import verify_actor_chain, verify_delegation
from funduq.kyok import KyokBinding, KyokOptIn, parse_kyok_opt_in, strip_kyok_context
from funduq.models import AgentRef
from funduq.props import RESERVED_METADATA_KEYS, build_forwarded_props

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from funduq.core import Funduq

__all__ = ["InboundRun", "dispatch", "resolve_kyok", "verify_caller"]


async def verify_caller(session: "AsyncSession", metadata: dict) -> tuple[dict, str | None, Any]:
    """Verifies `metadata["actorChain"]` if present and returns
    `(metadata stripped of funduq's reserved keys, the chain's head key, the raw chain)` —
    `(metadata, None, None)` when no chain is attached. Raises `InvalidActorChain` if the
    chain is tampered: a bad chain is refused at the door, never carried.

    funduq's whole part in caller identity is four verbs — verify, copy the
    head, relay, refuse — and this is the verify. No summary is produced:
    the chain reaches the agent verbatim (`forwardedProps.actorChain`) and
    the agent verifies for itself; the head key is what funduq copies onto
    the records that need an authority (a thread's binding, a paused ask).

    A session delegation certificate under `metadata["delegation"]` resolves
    the head: when the certificate's named delegate signed the chain's first
    hop, the certificate's authority is the effective head — rights attach to
    the durable key; the session key is a glove.

    Every door funnels caller metadata through here, which also makes it the
    one place to strip funduq's reserved keys from the caller's input. It
    lives outside `protocols/` because nothing about it is any protocol's:
    which door the metadata arrived by does not change a single line of it.
    """
    metadata = {k: v for k, v in metadata.items() if k not in RESERVED_METADATA_KEYS}
    actor_chain = metadata.get("actorChain")
    if not actor_chain:
        return metadata, None, None
    head = verify_actor_chain(actor_chain).head
    delegation = metadata.get("delegation")
    if delegation is not None:
        authority = verify_delegation(delegation)
        if delegation.get("delegatePublicKey") == head:
            head = authority
    return metadata, head, actor_chain


async def resolve_kyok(
    session: "AsyncSession", metadata: dict
) -> tuple[dict, KyokOptIn | None]:
    """Reads a KYOK opt-in out of `metadata` and returns
    `(metadata with the caller's KYOK context removed, the opt-in or None)`.

    Raises `LlmProviderNotFound` if the opt-in names an offering that is not
    registered — refused at the door, so a run is never created bound to an
    offering that does not exist.

    The context is stripped from what gets stored because it is the caller's
    to relay, not funduq's to keep: it travels to the LLM provider through
    the binding and is never persisted (see `mechanisms/kyok.md`).
    """
    opt_in = parse_kyok_opt_in(metadata)
    if opt_in is not None and opt_in.llm_provider is not None:
        if await repo.get_llm_provider(session, opt_in.llm_provider) is None:
            raise LlmProviderNotFound(f"unknown KYOK LLM provider '{opt_in.llm_provider}'")
    return strip_kyok_context(metadata), opt_in


@dataclass(frozen=True)
class InboundRun:
    """One run as a door has translated it, before funduq has decided anything.

    Everything here is either the caller's own words or a field of AG-UI's
    `RunAgentInput` — the shape every provider sees, whichever door the run
    arrived by. What funduq owes it is the rest: a thread, a run id, the
    folded message history and the forwarded-props funduq itself authors. That
    division is the whole point of this type; a door translates, and the seat
    decides.

    `protocol` records which door it came by. It is a stored fact, never
    branched on — nothing in dispatch reads it back.
    """

    agent: AgentRef
    messages: list[dict[str, Any]]
    metadata: dict[str, Any]
    head_key: str | None = None
    actor_chain: Any = None
    kyok: KyokOptIn | None = None
    inherit_kyok_from: str | None = None
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
    """Appends the inbound messages to the thread, builds the provider's AG-UI input, commits,
    and hands the run to the broker. Returns False without enqueuing if the agent is registered
    but nobody is currently serving it — the run is recorded `failed`/`agent_offline` and
    committed, because a run nothing will dispatch must not read as `queued` forever.

    Raises `InvalidRunInput` if the assembled input is not valid AG-UI.

    This is the far side of every door and it names no protocol. The KYOK
    binding is established after the commit for the same reason it always
    was: it is in-memory state about a run that must exist first.
    """
    messages = await repo.append_thread_messages(
        session, thread_id, run_id, inbound.messages
    )

    if not funduq.is_serving(inbound.agent):
        await funduq.mark_run_status(
            session, run_id, "failed", metadata={"failureReason": "agent_offline"}
        )
        await session.commit()
        return False

    kyok_ref = inbound.kyok_ref
    inherited = (
        kyok_ref is None
        and inbound.inherit_kyok_from is not None
        and funduq.kyok_relay.inherit(
            inbound.inherit_kyok_from, run_id, inbound.actor_chain
        )
    )

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
                kyok_ref is not None or inherited,
                inbound.forwarded_props,
                inbound.actor_chain,
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
    funduq.enqueue_run(
        run_id, inbound.agent, thread_id, input_json, inbound.protocol, seq=starting_seq
    )
    return True
