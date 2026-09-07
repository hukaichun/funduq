from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from funduq import repo
from ag_ui.core import RunErrorEvent, RunStartedEvent

from funduq.agui import build_run_agent_input
from funduq.ids import new_id
from funduq.errors import InvalidRunInput, LlmProviderNotFound, PresenterRequired
from funduq.identity import (
    InvalidChain,
    verify_chain,
    verify_cancel,
    verify_resolution,
)
from funduq.kyok import KyokBinding, KyokOptIn, parse_kyok_opt_in
from funduq.handlers import close_with_terminal_event
from funduq.models import AgentRef
from funduq.pause import open_asks
from funduq.props import RESERVED_METADATA_KEYS, build_forwarded_props

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from funduq.core import Funduq

__all__ = [
    "InboundRun",
    "Opened",
    "authorize_cancel",
    "dispatch",
    "head_key_of",
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
    session: "AsyncSession", props: dict, *, presenter_key: str | None = None
) -> tuple[dict, str | None, Any]:
    """Reads the caller's declarations off its bag — `forwardedProps` on AG-UI, the message's `metadata` on A2A, one bag either way — verifies `actorChain` if present, and returns `(the bag stripped of funduq's own key, the chain's head key, the raw chain)`; `(bag, None, None)` when no chain is attached."""
    props = {k: v for k, v in props.items() if k not in RESERVED_METADATA_KEYS}
    actor_chain = props.get("actorChain")
    if not actor_chain:
        return props, None, None
    if presenter_key is None:
        # The chain's last hop says "I present this"; with nobody at the door that cannot be checked, and recording it would record an unverified fact.
        raise PresenterRequired(
            "a chain was presented, but this door was not told which key presented it. "
            "Nothing in the request is wrong: the transport must authenticate the caller "
            "and hand the key to core (`presenter_key_of` on the A2A handler, "
            "`presenter_key=` on the AG-UI adapter and the facade). Until it does, this "
            "deployment does not accept chains."
        )
    verified = verify_chain(actor_chain)
    if presenter_key != verified.presenter:
        raise InvalidChain(
            "the chain's last hop was signed by "
            f"{verified.presenter[:16]}…, but the caller authenticated as "
            f"{presenter_key[:16]}… — extend the chain with your own key to present it"
        )
    return props, verified.head, actor_chain


async def resolve_kyok(
    session: "AsyncSession", props: dict
) -> tuple[dict, KyokOptIn | None]:
    """Reads a KYOK opt-in off the caller's bag and returns `(the bag, the opt-in or None)`. The opt-in stays in the bag, context included: it is the caller's own word, relayed to the agent like the rest, and a restart rebuilds the binding from it."""
    opt_in = parse_kyok_opt_in(props)
    if opt_in is not None and opt_in.llm_provider is not None:
        if await repo.get_llm_provider(session, opt_in.llm_provider) is None:
            raise LlmProviderNotFound(f"unknown KYOK LLM provider '{opt_in.llm_provider}'")
    return props, opt_in


def head_key_of(run: Any) -> str | None:
    """The authority a run was opened under: the first hop of its chain, or None for an unbound run."""
    return verify_chain(run.actor_chain).head if run.actor_chain else None


@dataclass(frozen=True)
class InboundRun:
    """One run as a door has translated it, before funduq has decided anything."""

    agent: AgentRef
    messages: list[dict[str, Any]]
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
            seq=opened.starting_seq,
            addressed_run_id=inbound.addressed_run_id,
        )
        is None
    ):
        funduq.kyok_relay.discard(opened.run_id)
        await funduq.mark_run_status(session, opened.run_id, "failed")
        await session.commit()
        # The record keeps the terminal event too, not only the caller's stream: a failed run with no RUN_ERROR would have no reason.
        await close_with_terminal_event(funduq, opened.run_id, "agent_offline")
        return False
    return True


@dataclass(frozen=True)
class Opened:
    """The run a request resolved to — a reopened ask, or a fresh one on the thread — and the input its row now holds, which is exactly what the provider will receive."""

    run_id: str
    thread_id: str
    starting_seq: int
    input_json: dict[str, Any]


def authorize_cancel(run: Any, metadata: dict[str, Any]) -> str | None:
    """Refuses a cancel that carries no authority over a run whose thread is bound, and returns the authority that asked (`None` for an unbound run)."""
    head = head_key_of(run)
    if head is None:
        return None
    return verify_cancel(
        metadata.get("cancel") or {},
        run.run_id,
        {head, run.provider_key},
    )


async def open_run(
    funduq: "Funduq",
    session: "AsyncSession",
    inbound: InboundRun,
    *,
    thread_id: str,
    answers: Any = None,
) -> Opened:
    """Opens a new run on the thread and writes its row — the `RunAgentInput` its provider will receive, one column per field, with its messages in the thread — in one commit.

    Every input is a run (AG-UI's own model). When the input answers the
    thread's open asks, `answers` is the finished run that asked: the new
    run's `parentRunId` names it, and on a bound thread the bag must carry a
    resolution proof signed by that run's head or the serving provider over
    exactly the asks still open.
    """
    if inbound.addressed_run_id is not None:
        target = funduq.broker.get(inbound.addressed_run_id)
        if target is None or target.thread_id != thread_id:
            raise InvalidRunInput(
                f"interjection names '{inbound.addressed_run_id}', which is not a "
                "live run on this thread"
            )

    parent_run_id = inbound.parent_run_id
    if answers is not None:
        head = head_key_of(answers)
        if head is not None:
            # A chained ask names its authorities; the resolution must be signed by one of them, over exactly the asks still open.
            bag = inbound.forwarded_props if isinstance(inbound.forwarded_props, dict) else {}
            # Signed over the id the caller holds for this conversation — the lineage's root, the A2A task id — and exactly the asks still open; the ask ids are new for every pause, so the proof binds to this one.
            verify_resolution(
                bag.get("resolution") or {},
                await repo.root_of(session, answers),
                open_asks(await repo.get_run_events(session, answers.run_id)),
                {head, inbound.agent.provider_key},
            )
        parent_run_id = answers.run_id
    else:
        # An answer is how a waiting thread drains; only fresh utterances count against the buffer.
        await repo.ensure_queue_room(session, thread_id, funduq.settings.thread_queue_limit)

    run_id = new_id("run")
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
            parent_run_id=parent_run_id,
        )
    except ValueError as e:
        raise InvalidRunInput(str(e)) from e

    await repo.create_run(
        session, thread_id, inbound.agent, input_json,
        actor_chain=inbound.actor_chain, run_id=run_id,
    )
    await repo.append_thread_messages(session, thread_id, run_id, messages, origin="caller")
    await session.commit()
    return Opened(run_id=run_id, thread_id=thread_id, starting_seq=0, input_json=input_json)


async def offline_events(thread_id: str, run_id: str) -> AsyncIterator[dict[str, Any]]:
    """The stream a run gets when its agent is registered but nobody is serving it."""
    yield RunStartedEvent(thread_id=thread_id, run_id=run_id).model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
    yield RunErrorEvent(message="agent is currently offline").model_dump(
        mode="json", by_alias=True, exclude_none=True
    )
