from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from funduq import repo
from ag_ui.core import CustomEvent, RunErrorEvent, RunStartedEvent

from funduq.agui import build_run_agent_input
from funduq.broker import RelayEvent
from funduq.errors import InvalidRunInput, LlmProviderNotFound
from funduq.identity import (
    InvalidResolution,
    verify_actor_chain,
    verify_cancel,
    verify_delegation,
    verify_resolution,
)
from funduq.kyok import KyokBinding, KyokOptIn, parse_kyok_opt_in, strip_kyok_context
from funduq.models import AgentRef
from funduq.props import (
    RESERVED_METADATA_KEYS,
    RESOLVED_EVENT_NAME,
    RESOLVED_METADATA_KEY,
    build_forwarded_props,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from funduq.core import Funduq

__all__ = [
    "InboundRun",
    "Opened",
    "PendingAsk",
    "Resolved",
    "answers_of",
    "authorize_cancel",
    "pending_interrupt_ids",
    "dispatch",
    "offline_events",
    "open_run",
    "resolve_kyok",
    "verify_caller",
]


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


def _unstamped(message: dict[str, Any]) -> dict[str, Any]:
    """`message` without funduq's resolution stamp, whoever put it there."""
    metadata = message.get("metadata")
    if not isinstance(metadata, dict) or RESOLVED_METADATA_KEY not in metadata:
        return message
    return {
        **message,
        "metadata": {k: v for k, v in metadata.items() if k != RESOLVED_METADATA_KEY},
    }


async def dispatch(
    funduq: "Funduq",
    session: "AsyncSession",
    inbound: InboundRun,
    *,
    thread_id: str,
    run_id: str,
    starting_seq: int,
    resolved: "Resolved | None" = None,
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
    # `funduq/resolved` is funduq's handwriting on a message, and only
    # funduq writes it. Stripped from every inbound message before anything
    # is stamped: without this a caller plants the key on an ordinary
    # utterance and the thread carries a resolution, naming an authority
    # nobody ever proved. Same defense as the reserved run-metadata keys,
    # on the record messages live in.
    inbound_messages = [_unstamped(m) for m in inbound.messages]
    if resolved is not None:
        # An answer belongs in the conversation it answers. The caller's own
        # words carry it when there are any (A2A's answer *is* a message); an
        # AG-UI resume says everything in its entries and nothing in prose, so
        # funduq records a wordless turn rather than inventing words for it.
        # Either way the decisions and the authority ride in the metadata,
        # written in the same transaction as the guard that picked this
        # answer over any other.
        if not inbound_messages:
            inbound_messages = [{"role": "user", "content": ""}]
        first = dict(inbound_messages[0])
        first["metadata"] = {
            **(first.get("metadata") or {}),
            RESOLVED_METADATA_KEY: {
                "answers": resolved.answers,
                "authority": resolved.authority,
            },
        }
        inbound_messages[0] = first
    messages = await repo.append_thread_messages(
        session, thread_id, run_id, inbound_messages
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
    if resolved is not None:
        # The update, as distinct from the record: whoever is watching learns
        # that the ask was answered and under whose authority. Where it lands
        # in the stream does not matter — the record is the thread message
        # above, so this is free to arrive whenever the run's own lane gets
        # to it.
        funduq.broker.push(
            run_id,
            RelayEvent(
                CustomEvent(
                    name=RESOLVED_EVENT_NAME,
                    value={
                        "runId": run_id,
                        "messageId": messages[0]["id"] if messages else None,
                        "answers": resolved.answers,
                        "authority": resolved.authority,
                    },
                ).model_dump(mode="json", by_alias=True, exclude_none=True)
            ),
        )
    return True


@dataclass(frozen=True)
class PendingAsk:
    """The paused run a result would land on: the key authorized to answer it,
    and the questions it is actually asking.

    Each door finds this its own way — that lookup is the door's grammar,
    not funduq's — and hands it over in this one shape. The ids are what a
    resolution names, so an answer to one ask cannot be spent on the next.
    """

    run_id: str
    head_key: str | None
    interrupt_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Resolved:
    """What answering an ask established, once the reopen was won.

    Kept because it is the fact the chain exists to produce — who said yes to
    what — and because nothing else records it: the signature that proved it
    is evidence, and evidence is not the thing proved.
    """

    answers: dict[str, str]
    authority: str | None


@dataclass(frozen=True)
class Opened:
    """The run a request resolved to: a reopened ask, or a fresh one on the thread."""

    run_id: str
    starting_seq: int
    landed_on_ask: bool
    resolved: Resolved | None = None


def pending_interrupt_ids(record: Any) -> frozenset[str]:
    """The ids of the questions a paused run is asking, read off its record."""
    metadata = (record.get("metadata") if isinstance(record, dict) else record.metadata) or {}
    return frozenset(
        i["id"] for i in (metadata.get("interrupts") or []) if isinstance(i, dict) and i.get("id")
    )


def answers_of(resume: list[dict[str, Any]] | None) -> dict[str, str]:
    """`{interrupt id: decision}` for the entries a request is submitting.

    AG-UI's own shape and its own two words (`resolved` / `cancelled`), read
    off `RunAgentInput.resume` — which is what the provider will receive
    whichever door the answer arrived by.
    """
    return {
        entry["interruptId"]: entry.get("status", "")
        for entry in (resume or [])
        if isinstance(entry, dict) and entry.get("interruptId")
    }


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
    answers: dict[str, str] | None = None,
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
        answers = answers or {}
        authority = None
        if ask.head_key is not None:
            if answers.keys() != ask.interrupt_ids:
                raise InvalidResolution(
                    "a resolution must name every question this ask is asking "
                    f"({sorted(ask.interrupt_ids)}), and only those — a reopen ends the "
                    "whole pause, so an unnamed question is dropped rather than left waiting"
                )
            authority = verify_resolution(
                metadata.get("resolution") or {},
                ask.run_id,
                answers,
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
            # Only the winner gets here — the reopen is status-guarded — so
            # this is the one place an answer can be recorded without racing
            # a second one, and it is in the same transaction as the guard.
            return Opened(
                run_id=ask.run_id,
                starting_seq=await repo.get_last_event_seq(session, ask.run_id),
                landed_on_ask=True,
                resolved=Resolved(answers=answers, authority=authority) if answers else None,
            )

    if entrance == "result":
        return None

    await repo.ensure_queue_room(session, thread_id, funduq.settings.thread_queue_limit)
    created = await repo.create_run(
        session, thread_id, agent, protocol, run_input,
        metadata=metadata, head_key=head_key,
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
