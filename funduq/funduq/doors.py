from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from funduq import repo
from ag_ui.core import RunErrorEvent, RunStartedEvent

from funduq.agui import build_run_agent_input
from funduq.errors import InvalidRunInput, LlmProviderNotFound
from funduq.identity import (
    InvalidActorChain,
    verify_actor_chain,
    verify_cancel,
    verify_delegation,
    verify_resolution,
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
    "resolve_kyok",
    "verify_caller",
]


async def verify_caller(
    session: "AsyncSession", metadata: dict, *, presenter_key: str | None = None
) -> tuple[dict, str | None, Any]:
    """Verifies `metadata["actorChain"]` if present and returns
    `(metadata stripped of funduq's reserved keys, the chain's head key, the raw chain)` —
    `(metadata, None, None)` when no chain is attached. Raises `InvalidActorChain` if the
    chain is tampered: a bad chain is refused at the door, never carried.

    `presenter_key` is the key an authenticating seat in front of this door
    proved belongs to whoever is calling, and it is the answer to **a chain
    proves origin, not possession**. A chain is not a secret — funduq relays
    it to the serving provider verbatim — so holding one is no evidence of
    being its head, and a provider can otherwise present its caller's chain
    back here for work the caller never asked for
    (`scripts/probes/probe_a_provider_can_speak_as_the_caller.py`). When a
    key is supplied it must equal the chain's **presenter** (the last hop's
    signer, never the head — comparing the head is exactly the mistake that
    lets the replay through), and a mismatch is refused rather than
    downgraded: presenting a chain is a claim, and a claim that cannot be
    backed is not the same act as making no claim at all.

    funduq compares; it never authenticates. A door receives bytes, not a
    connection, so establishing who is calling needs the live channel the
    seat has and core does not. Supplying the key is therefore the
    embedder's, and **omitting it changes nothing**: the chain is verified,
    relayed and its head copied exactly as before. This is an extension for
    a deployment that has an authenticating seat, not a new requirement —
    withdrawing authority from every caller who has no seat in front of them
    would be compelling participation, which funduq does not do. It also
    means a deployment that supplies no key is exactly as exposed as it was,
    and that is a deployment invariant rather than a setting: core's caller
    doors are not independently safe.

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
    verified = verify_actor_chain(actor_chain)
    if presenter_key is not None and presenter_key != verified.presenter:
        raise InvalidActorChain(
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


@dataclass(frozen=True)
class PendingAsk:
    """The paused run a result would land on, and the key authorized to answer it.

    Each door finds this its own way — that lookup is the door's grammar,
    not funduq's — and hands it over in this one shape.
    """

    run_id: str
    head_key: str | None


@dataclass(frozen=True)
class Opened:
    """The run a request resolved to: a reopened ask, or a fresh one on the thread."""

    run_id: str
    starting_seq: int
    landed_on_ask: bool


def authorize_cancel(run: Any, metadata: dict[str, Any]) -> None:
    """Refuses a cancel that carries no authority over a run whose thread is bound.

    Stopping someone else's run is a rights question, and it was left
    outside when writing a bound thread became a membership act: a complete
    stranger holding the run id could still ask the provider to stop.
    A run id is an identifier, and identifiers are never credentials.

    The authority set is the one an ask on the same run would have — the
    run's segment head and the agent's own provider key — because the two
    are the same question asked twice: who does this run's segment answer
    to? The proof is a signature over
    `identity.cancel_signing_payload(run_id, timestamp)`, which is
    possession of a private key rather than a chain hop anyone downstream
    could replay.

    **An unbound run stays open**, exactly as it is today. The whole
    mechanism is opt-in by carrying a chain: a thread that named no
    authority at birth has none to check against, and inventing one here
    would make funduq the authority instead of the caller.

    Raises `InvalidCancel`; a no-op for an unbound run.
    """
    if run.head_key is None:
        return
    verify_cancel(
        metadata.get("cancel") or {},
        run.run_id,
        {run.head_key, run.provider_key},
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
    """Resolves a request to the run it belongs on: the pending ask it answers, or a new run
    queued on the thread. Returns None only for a declared **result** that found no ask to land
    on — either there was none, or another caller answered first.

    The two lanes are [the seam's two
    entrances](../../docs/design-records.md); which one a caller used is
    theirs to declare, never inferred from the target's state:

    - a **result** must land on a pending ask. It reopens that run under its
      own id, and the reopen is status-guarded so two concurrent answers
      resolve to one; the loser gets None, same as if there had been no ask.
      A result never queues — it drains an ask rather than piling new input,
      which is why `thread_queue_limit` is not consulted on this path.
    - an **utterance** becomes a new queued run. If it happens to be
      addressed at a run that is *currently* a pending ask, it lands there
      instead — that is A2A's grammar, where a result is a plain message
      plus addressing, so one that lands on no ask honestly is an
      utterance. When the reopen loses, it degrades to an utterance too.

    A chained ask names its authorities, and a resolution must carry a
    signature from one of them (raising `InvalidResolution` otherwise) —
    checked before the reopen, so a failed signature cannot consume the win.
    """
    if ask is not None:
        if ask.head_key is not None:
            verify_resolution(
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
    """The stream a run gets when its agent is registered but nobody is serving it.

    funduq has reached a verdict — the run is recorded `failed` with
    `agent_offline` — and a caller left holding a silent stream cannot tell
    that from an agent with nothing to say. Both events are built from
    AG-UI's own models rather than hand-written dicts, dumped with
    `exclude_none=True` so no `timestamp: null` enters a caller's stream.
    """
    yield RunStartedEvent(thread_id=thread_id, run_id=run_id).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    yield RunErrorEvent(message="agent is currently offline").model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
