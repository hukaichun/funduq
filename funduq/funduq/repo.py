from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, insert, inspect, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from funduq.identity import provider_fingerprint, verify_chain
from funduq.props import INTERJECTION_EXTENSION_URI
from funduq.agui import build_run_agent_input
from funduq.ids import new_id
from funduq_contract import Registration

from funduq.models import AgentRecord, AgentRef, AgentSummary, LlmRef, LlmSummary, RunRecord
from funduq.schema import (
    agents,
    llm_providers,
    providers,
    run_events,
    runs,
    thread_messages,
    threads,
)

logger = logging.getLogger("funduq.repo")


# A run nobody has accepted yet: waiting in the queue, or handed to a provider that has not answered.
PENDING_RUN_STATUSES = ["queued", "offering"]
ACTIVE_RUN_STATUSES = [*PENDING_RUN_STATUSES, "running", "cancelling"]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _upsert(session: AsyncSession, table):
    is_postgres = session.bind.dialect.name == "postgresql"
    return (pg_insert if is_postgres else sqlite_insert)(table)


class ProviderFingerprintTaken(Exception):
    """A provider's public key hashes to a fingerprint another registered public key already holds."""


class RunRowMissing(Exception):
    pass


class ThreadNotFound(Exception):
    """`ensure_thread` was called on an unregistered thread id without `create_if_missing`."""


class ThreadOwnershipMismatch(Exception):
    pass


class ThreadMembershipRequired(Exception):
    """The thread is bound to a responsibility segment and the writer is not a member."""


class ThreadQueueFull(Exception):
    """The thread's pending-utterance buffer is at its limit; the message was NOT accepted."""


async def get_schema_revision(session: AsyncSession) -> str | None:
    connection = await session.connection()
    if not await connection.run_sync(lambda c: inspect(c).has_table("alembic_version")):
        return None
    return (
        await session.execute(select(text("version_num")).select_from(text("alembic_version")))
    ).scalars().first()


async def ensure_provider(session: AsyncSession, public_key: str) -> None:
    """Inserts a `providers` row for `public_key` if one doesn't exist yet; a no-op if it does."""
    now = _utcnow()
    stmt = _upsert(session, providers).values(
        public_key=public_key,
        fingerprint=provider_fingerprint(public_key),
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_nothing(index_elements=[providers.c.public_key])
    try:
        await session.execute(stmt)
    except IntegrityError as e:
        await session.rollback()
        raise ProviderFingerprintTaken(
            f"another provider already holds fingerprint {provider_fingerprint(public_key)}"
        ) from e


async def set_provider_name(session: AsyncSession, public_key: str, display_name: str) -> None:
    await session.execute(
        update(providers)
        .where(providers.c.public_key == public_key)
        .values(display_name=display_name, updated_at=_utcnow())
    )


async def register_agents(
    session: AsyncSession,
    public_key: str,
    agents_batch: list[Registration],
    provider_name: str | None = None,
) -> dict[str, AgentRef]:
    """Registers or refreshes agents for `public_key`, and returns an `AgentRef` per name."""
    await ensure_provider(session, public_key)
    if provider_name is not None:
        await set_provider_name(session, public_key, provider_name)

    now = _utcnow()
    registered: dict[str, AgentRef] = {}
    for agent in agents_batch:
        name = agent.name
        card = {
            "name": name,
            "description": agent.description,
            **agent.agent_card_extra,
        }
        if agent.takes_interjections:
            declared = list(card.get("extensions", []))
            if INTERJECTION_EXTENSION_URI not in declared:
                declared.append(INTERJECTION_EXTENSION_URI)
            card["extensions"] = declared
        stmt = _upsert(session, agents).values(
            name=name,
            provider_key=public_key,
            agent_card=card,
            metadata=agent.metadata,
            joined_at=now,
            last_seen_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[agents.c.provider_key, agents.c.name],
            set_={
                "agent_card": stmt.excluded.agent_card,
                "metadata": stmt.excluded.metadata,
                "last_seen_at": now,
            },
        )
        await session.execute(stmt)
        registered[name] = AgentRef(provider_key=public_key, name=name)

    await session.commit()
    return registered


async def get_agent_names_for_provider(session: AsyncSession, provider_key: str) -> set[str]:
    rows = (
        await session.execute(
            select(agents.c.name).where(agents.c.provider_key == provider_key)
        )
    ).scalars().all()
    return set(rows)


async def register_llm_providers(
    session: AsyncSession,
    public_key: str,
    names: list[str],
    metadata: dict[str, Any] | None = None,
) -> dict[str, LlmRef]:
    await ensure_provider(session, public_key)
    now = _utcnow()
    registered: dict[str, LlmRef] = {}
    for name in names:
        stmt = _upsert(session, llm_providers).values(
            provider_key=public_key,
            name=name,
            metadata=metadata or {},
            joined_at=now,
            last_seen_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[llm_providers.c.provider_key, llm_providers.c.name],
            set_={"metadata": stmt.excluded.metadata, "last_seen_at": now},
        )
        await session.execute(stmt)
        registered[name] = LlmRef(provider_key=public_key, name=name)
    await session.commit()
    return registered


async def get_llm_provider(session: AsyncSession, ref: LlmRef) -> dict[str, Any] | None:
    row = (
        await session.execute(
            select(llm_providers).where(
                llm_providers.c.provider_key == ref.provider_key,
                llm_providers.c.name == ref.name,
            )
        )
    ).mappings().first()
    return dict(row) if row else None


async def get_llm_names_for_key(session: AsyncSession, public_key: str) -> set[str]:
    rows = (
        await session.execute(
            select(llm_providers.c.name).where(llm_providers.c.provider_key == public_key)
        )
    ).scalars().all()
    return set(rows)


async def touch_llm_providers(
    session: AsyncSession, provider_key: str, names: list[str]
) -> None:
    if not names:
        return
    await session.execute(
        update(llm_providers)
        .where(
            llm_providers.c.provider_key == provider_key,
            llm_providers.c.name.in_(names),
        )
        .values(last_seen_at=_utcnow())
    )
    await session.commit()


async def touch_agents(session: AsyncSession, provider_key: str, names: list[str]) -> None:
    if not names:
        return
    await session.execute(
        update(agents)
        .where(agents.c.provider_key == provider_key, agents.c.name.in_(names))
        .values(last_seen_at=_utcnow())
    )
    await session.commit()


async def get_agent(session: AsyncSession, agent: AgentRef) -> AgentRecord | None:
    row = (
        await session.execute(
            select(
                agents.c.provider_key,
                agents.c.name,
                agents.c.agent_card,
                agents.c.metadata,
                agents.c.joined_at,
                agents.c.last_seen_at,
            ).where(
                agents.c.provider_key == agent.provider_key,
                agents.c.name == agent.name,
            )
        )
    ).mappings().first()
    return AgentRecord(**row) if row else None


async def resolve_agent(session: AsyncSession, provider: str, name: str) -> AgentRecord | None:
    """Looks up an agent by name under a provider identified by either its public key or fingerprint."""
    row = (
        await session.execute(
            select(
                agents.c.provider_key,
                agents.c.name,
                agents.c.agent_card,
                agents.c.metadata,
                agents.c.joined_at,
                agents.c.last_seen_at,
            )
            .select_from(agents.outerjoin(providers, providers.c.public_key == agents.c.provider_key))
            .where(
                or_(agents.c.provider_key == provider, providers.c.fingerprint == provider),
                agents.c.name == name,
            )
        )
    ).mappings().first()
    return AgentRecord(**row) if row else None


async def list_llm_providers(
    session: AsyncSession,
    *,
    stale_hidden_window_seconds: int,
) -> list[LlmSummary]:
    """Lists registered LLM offerings, excluding any not seen within `stale_hidden_window_seconds` — the mirror of `list_agents`."""
    stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_hidden_window_seconds)
    rows = (
        await session.execute(
            select(
                llm_providers.c.provider_key,
                llm_providers.c.name,
                llm_providers.c.metadata,
                llm_providers.c.joined_at,
                llm_providers.c.last_seen_at,
                providers.c.display_name.label("provider_name"),
            )
            .select_from(
                llm_providers.outerjoin(
                    providers, providers.c.public_key == llm_providers.c.provider_key
                )
            )
            .where(llm_providers.c.last_seen_at >= stale_cutoff)
            .order_by(llm_providers.c.name)
        )
    ).mappings().all()
    return [
        LlmSummary(
            provider_key=row["provider_key"],
            name=row["name"],
            metadata=row["metadata"],
            joined_at=row["joined_at"],
            last_seen_at=row["last_seen_at"],
            provider_name=row["provider_name"],
        )
        for row in rows
    ]


async def list_agents(
    session: AsyncSession,
    *,
    stale_hidden_window_seconds: int,
) -> list[AgentSummary]:
    """Lists registered agents, excluding any not seen within `stale_hidden_window_seconds`."""
    stale_cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_hidden_window_seconds)
    rows = (
        await session.execute(
            select(
                agents.c.provider_key,
                agents.c.name,
                agents.c.agent_card,
                agents.c.joined_at,
                agents.c.last_seen_at,
                providers.c.display_name.label("provider_name"),
            )
            .select_from(
                agents.outerjoin(providers, providers.c.public_key == agents.c.provider_key)
            )
            .where(agents.c.last_seen_at >= stale_cutoff)
            .order_by(agents.c.name)
        )
    ).mappings().all()
    return [
        AgentSummary(
            provider_key=row["provider_key"],
            name=row["name"],
            description=row["agent_card"].get("description", ""),
            skills=row["agent_card"].get("skills", []),
            joined_at=row["joined_at"],
            last_seen_at=row["last_seen_at"],
            provider_name=row["provider_name"],
        )
        for row in rows
    ]


async def count_threads_for_agent(session: AsyncSession, agent: AgentRef) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(threads)
            .where(
                threads.c.provider_key == agent.provider_key,
                threads.c.agent_name == agent.name,
            )
        )
    ).scalar_one()


async def count_runs_for_agent(session: AsyncSession, agent: AgentRef, statuses: list[str] | None = None) -> int:
    where = [runs.c.provider_key == agent.provider_key, runs.c.agent_name == agent.name]
    if statuses is not None:
        where.append(runs.c.status.in_(statuses))
    return (
        await session.execute(select(func.count()).select_from(runs).where(*where))
    ).scalar_one()


async def delete_llm_provider(session: AsyncSession, ref: LlmRef) -> bool:
    result = await session.execute(
        delete(llm_providers).where(
            llm_providers.c.provider_key == ref.provider_key, llm_providers.c.name == ref.name
        )
    )
    await session.commit()
    return result.rowcount > 0


async def delete_agent(session: AsyncSession, agent: AgentRef) -> bool:
    result = await session.execute(
        delete(agents).where(
            agents.c.provider_key == agent.provider_key, agents.c.name == agent.name
        )
    )
    await session.commit()
    return result.rowcount > 0


async def get_agent_name_for_public_key(session: AsyncSession, public_key: str) -> str | None:
    return (
        await session.execute(
            select(agents.c.name)
            .where(agents.c.provider_key == public_key)
            .order_by(agents.c.joined_at)
            .limit(1)
        )
    ).scalars().first()


async def get_thread(session: AsyncSession, thread_id: str) -> dict[str, Any] | None:
    row = (
        await session.execute(select(threads).where(threads.c.thread_id == thread_id))
    ).mappings().first()
    return dict(row) if row else None


async def create_thread(
    session: AsyncSession,
    agent: AgentRef,
    parent_thread_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    head_key: str | None = None,
) -> str:
    thread_id = new_id("thread")
    now = _utcnow()
    await session.execute(
        insert(threads).values(
            thread_id=thread_id,
            provider_key=agent.provider_key,
            agent_name=agent.name,
            parent_thread_id=parent_thread_id,
            head_key=head_key,
            metadata=metadata or {},
            created_at=now,
            last_activity_at=now,
        )
    )
    return thread_id


async def ensure_thread(
    session: AsyncSession,
    agent: AgentRef,
    thread_id: str | None,
    parent_thread_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    create_if_missing: bool = False,
    head_key: str | None = None,
) -> str:
    """Resolves a thread id for `agent`, creating a new thread when `thread_id` is None.

    Thread ids are funduq-minted, always: `create_if_missing` mints a fresh id
    and the caller's unknown string is never adopted. A caller-chosen name that
    addressed state would be a credential anyone can forge — two callers picking
    the same string would share a history and a queue lane. The real protections
    (agent binding, segment head) guard only threads funduq itself named.
    """
    if thread_id is not None:
        existing = await get_thread(session, thread_id)
        if existing is None:
            if create_if_missing:
                return await create_thread(
                    session, agent, parent_thread_id, metadata=metadata, head_key=head_key
                )
            raise ThreadNotFound(thread_id)
        owner = AgentRef(
            provider_key=existing["provider_key"], name=existing["agent_name"]
        )
        if owner != agent:
            raise ThreadOwnershipMismatch(
                f"thread '{thread_id}' belongs to agent '{owner}', not '{agent}'"
            )
        bound_head = existing.get("head_key")
        if bound_head is not None and head_key != bound_head and head_key != agent.provider_key:
            raise ThreadMembershipRequired(
                f"thread '{thread_id}' is bound to a responsibility segment; only its "
                "head or its serving provider may write to it"
            )
        await session.execute(
            update(threads).where(threads.c.thread_id == thread_id).values(last_activity_at=_utcnow())
        )
        return thread_id

    return await create_thread(session, agent, parent_thread_id, metadata, head_key=head_key)


async def get_thread_children(session: AsyncSession, thread_id: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(
                threads.c.thread_id,
                threads.c.provider_key,
                threads.c.agent_name,
                threads.c.created_at,
            )
            .where(threads.c.parent_thread_id == thread_id)
            .order_by(threads.c.created_at)
        )
    ).mappings().all()
    return [dict(row) for row in rows]


def stamp_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The messages as funduq will store and deliver them: each under an id funduq minted, whatever the caller sent. Pure, so the ids can be named in a run's input before any row exists."""
    return [{**message, "id": new_id("msg")} for message in messages]


async def append_thread_messages(
    session: AsyncSession,
    thread_id: str,
    run_id: str,
    messages: list[dict[str, Any]],
    *,
    origin: str,
) -> None:
    """Writes `messages` — already stamped — to the thread under `run_id`, saying who said them: `"caller"` (carried in by the run; part of its `RunAgentInput`) or `"agent"` (produced by the run). Not committed."""
    for message in messages:
        await session.execute(
            insert(thread_messages).values(
                thread_id=thread_id,
                run_id=run_id,
                message_id=message["id"],
                message_json=message,
                metadata=message.get("metadata", {}),
                origin=origin,
            )
        )


async def get_thread_messages(session: AsyncSession, thread_id: str) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(thread_messages.c.message_json)
            .where(thread_messages.c.thread_id == thread_id)
            .order_by(thread_messages.c.id)
        )
    ).all()
    return [row.message_json for row in rows]


async def create_run(
    session: AsyncSession,
    thread_id: str,
    agent: AgentRef,
    run_input: dict[str, Any],
    *,
    actor_chain: list[str] | None = None,
    run_id: str | None = None,
) -> dict[str, str]:
    """Writes a new queued run: the `RunAgentInput` its provider will receive, one column per field (its messages are written to `thread_messages` by the caller), and the state funduq starts it in. A door mints `run_id` first so the input can name it; None mints one here. Not committed."""
    run_id = run_id or new_id("run")
    await session.execute(
        insert(runs).values(
            run_id=run_id,
            thread_id=thread_id,
            provider_key=agent.provider_key,
            agent_name=agent.name,
            status="queued",
            actor_chain=actor_chain,
            last_activity_at=_utcnow(),
            parent_run_id=run_input.get("parentRunId"),
            state=run_input.get("state"),
            tools=run_input.get("tools") or [],
            context=run_input.get("context") or [],
            forwarded_props=run_input.get("forwardedProps"),
            resume=run_input.get("resume"),
        )
    )
    return {"run_id": run_id}


async def messages_of_run(session: AsyncSession, run_id: str) -> list[dict[str, Any]]:
    """The messages this run carried in — the caller's, in order; what the agent said in reply is on the thread under the same run but is not the run's input."""
    rows = (
        await session.execute(
            select(thread_messages.c.message_json)
            .where(thread_messages.c.run_id == run_id, thread_messages.c.origin == "caller")
            .order_by(thread_messages.c.id)
        )
    ).all()
    return [row.message_json for row in rows]


async def messages_of_runs(session: AsyncSession, run_ids: list[str]) -> list[dict[str, Any]]:
    """Every thread message the given runs carried in or produced, in thread order — a task's history when `run_ids` is a lineage."""
    if not run_ids:
        return []
    rows = (
        await session.execute(
            select(thread_messages.c.message_json)
            .where(thread_messages.c.run_id.in_(run_ids))
            .order_by(thread_messages.c.id)
        )
    ).all()
    return [row.message_json for row in rows]


async def readers_of(session: AsyncSession, thread: dict[str, Any]) -> set[str] | None:
    """The keys that may read a bound thread — its head, the provider serving its agent, and every key on its runs' chains — or None for a thread nobody bound, which is readable by whoever holds its id."""
    if thread.get("head_key") is None:
        return None
    circle = {thread["provider_key"], thread["head_key"]}
    chains = (
        await session.execute(
            select(runs.c.actor_chain).where(
                runs.c.thread_id == thread["thread_id"], runs.c.actor_chain.is_not(None)
            )
        )
    ).scalars().all()
    for chain in chains:
        circle |= set(verify_chain(chain).actor_public_keys)
    return circle


async def run_input_of(session: AsyncSession, run: RunRecord) -> dict[str, Any]:
    """The `RunAgentInput` this row is — the projection its provider receives, byte for byte what was stored."""
    return build_run_agent_input(
        run.thread_id,
        run.run_id,
        await messages_of_run(session, run.run_id),
        state=run.state,
        tools=run.tools,
        context=run.context,
        forwarded_props=run.forwarded_props,
        resume=run.resume,
        parent_run_id=run.parent_run_id,
    )


async def record_cancel_request(
    session: AsyncSession, run_id: str, *, requested_by: str | None
) -> None:
    """Notes that someone asked this run to stop, and who. The one state a run keeps beyond its status."""
    if requested_by is None:
        return
    await session.execute(
        update(runs).where(runs.c.run_id == run_id).values(cancel_requested_by=requested_by)
    )
    await session.commit()


# The run-status state machine: which statuses each `mark_run_status` write may legally come from.
LEGAL_STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "offering": ("queued",),
    # "queued" as well as "offering": an offer that was declined, went unanswered, or failed puts the run back in the queue (`Requeue`).
    "running": ("queued", "offering"),
    "cancelling": ("running",),
    "completed": ("running", "cancelling"),
    "cancelled": ("queued", "offering", "running", "cancelling"),
    "failed": ("queued", "offering", "running", "cancelling"),
}


async def return_run_to_queue(session: AsyncSession, run_id: str) -> bool:
    """Puts a run whose offer was not accepted back to "queued", and returns whether it applied."""
    result = await session.execute(
        update(runs)
        .where(runs.c.run_id == str(run_id), runs.c.status == "offering")
        .values(status="queued", last_activity_at=_utcnow())
    )
    await session.commit()
    return result.rowcount > 0


async def mark_run_status(session: AsyncSession, run_id: str, status: str) -> bool:
    """Moves a run to `status` if its current status legally precedes it (`LEGAL_STATUS_TRANSITIONS`), and returns whether the transition applied."""
    legal_from = LEGAL_STATUS_TRANSITIONS.get(status)
    if legal_from is None:
        raise ValueError(
            f"run {run_id}: '{status}' is not a status mark_run_status may write — "
            "runs are created 'queued' and only move along the machine above"
        )
    timestamp_col = {
        "running": "started_at",
        "completed": "completed_at",
        "failed": "completed_at",
        "cancelled": "completed_at",
    }.get(status)
    now = _utcnow()
    values: dict[str, Any] = {"status": status, "last_activity_at": now}
    if timestamp_col:
        values[timestamp_col] = now
    result = await session.execute(
        update(runs)
        .where(runs.c.run_id == str(run_id), runs.c.status.in_(legal_from))
        .values(**values)
    )
    await session.commit()
    if result.rowcount > 0:
        return True
    current = (
        await session.execute(select(runs.c.status).where(runs.c.run_id == str(run_id)))
    ).scalar_one_or_none()
    if current is None:
        raise RunRowMissing(
            f"run {run_id}: no such run in the database — funduq is dispatching a run "
            "this database does not have"
        )
    logger.warning(
        "run %s: refused illegal status transition %r -> %r; the recorded status stands",
        run_id,
        current,
        status,
    )
    return False


async def get_active_run_for_thread(session: AsyncSession, thread_id: str) -> dict[str, Any] | None:
    row = (
        await session.execute(
            select(runs)
            .where(
                runs.c.thread_id == thread_id,
                runs.c.status.in_(ACTIVE_RUN_STATUSES),
            )
            .order_by(runs.c.created_at.desc())
            .limit(1)
        )
    ).mappings().first()
    return dict(row) if row else None


async def ensure_queue_room(session: AsyncSession, thread_id: str, limit: int | None) -> None:
    """Refuses (ThreadQueueFull) a new pending run when the thread's buffer is at `limit`; a no-op when `limit` is None."""
    if limit is None:
        return
    depth = await count_queued_runs_for_thread(session, thread_id)
    if depth >= limit:
        raise ThreadQueueFull(
            f"thread '{thread_id}' already has {depth} pending run(s), at its limit of "
            f"{limit} — the message was not accepted; wait for the thread to drain "
            "or answer its paused question"
        )


async def count_queued_runs_for_thread(session: AsyncSession, thread_id: str) -> int:
    """How many of the thread's runs no provider has accepted yet (`PENDING_RUN_STATUSES`) — the depth of its pending-utterance buffer."""
    return (
        await session.execute(
            select(func.count())
            .select_from(runs)
            .where(runs.c.thread_id == thread_id, runs.c.status.in_(PENDING_RUN_STATUSES))
        )
    ).scalar_one()


async def latest_run_for_thread(session: AsyncSession, thread_id: str) -> RunRecord | None:
    """The thread's most recent run. Whether the thread is waiting on an answer is a question about this run's events (`pause.open_asks`), not a status."""
    row = (
        await session.execute(
            select(runs)
            .where(runs.c.thread_id == thread_id)
            .order_by(runs.c.created_at.desc(), runs.c.run_id.desc())
            .limit(1)
        )
    ).mappings().first()
    return RunRecord(**row) if row else None


async def lineage_tail(session: AsyncSession, run_id: str) -> RunRecord | None:
    """The last run in the lineage rooted at `run_id`: follows `parent_run_id` links downward, taking the newest child at each step. None if `run_id` names no run. An A2A task is such a lineage; its state is its tail's."""
    current = await get_run(session, run_id)
    while current is not None:
        child = (
            await session.execute(
                select(runs)
                .where(runs.c.parent_run_id == current.run_id)
                .order_by(runs.c.created_at.desc(), runs.c.run_id.desc())
                .limit(1)
            )
        ).mappings().first()
        if child is None:
            return current
        current = RunRecord(**child)
    return None


async def root_of(session: AsyncSession, run: RunRecord) -> str:
    """The id of the run that started `run`'s lineage — the id a caller holds for it across every answer (an A2A task id), and what a resolution proof is signed over."""
    current = run
    while current.parent_run_id is not None:
        parent = await get_run(session, current.parent_run_id)
        if parent is None:
            break
        current = parent
    return current.run_id


async def lineage(session: AsyncSession, run_id: str) -> list[RunRecord]:
    """Every run in the lineage rooted at `run_id`, root first."""
    out: list[RunRecord] = []
    current = await get_run(session, run_id)
    while current is not None:
        out.append(current)
        child = (
            await session.execute(
                select(runs)
                .where(runs.c.parent_run_id == current.run_id)
                .order_by(runs.c.created_at.desc(), runs.c.run_id.desc())
                .limit(1)
            )
        ).mappings().first()
        current = RunRecord(**child) if child else None
    return out


async def get_thread_snapshot(session: AsyncSession, thread_id: str) -> dict[str, Any] | None:
    """The thread's state as a caller may see it: its messages, and a summary of the run in flight."""
    thread = await get_thread(session, thread_id)
    if thread is None:
        return None
    messages = await get_thread_messages(session, thread_id)
    active_run = await get_active_run_for_thread(session, thread_id)
    summary = (
        {"run_id": active_run["run_id"], "status": active_run["status"]}
        if active_run
        else None
    )
    return {"thread_id": thread_id, "messages": messages, "active_run": summary}


async def touch_run_activity(session: AsyncSession, run_id: str) -> None:
    await session.execute(
        update(runs).where(runs.c.run_id == run_id).values(last_activity_at=_utcnow())
    )


async def _fail_runs(session: AsyncSession, where_clause) -> list[str]:
    """Marks every run matching `where_clause` failed and returns their ids. The reason is the terminal RUN_ERROR the caller appends — the record, not a column."""
    rows = (await session.execute(select(runs.c.run_id).where(where_clause))).all()
    now = _utcnow()
    run_ids: list[str] = []
    for row in rows:
        result = await session.execute(
            update(runs)
            .where(runs.c.run_id == row.run_id, where_clause)
            .values(status="failed", completed_at=now)
        )
        if result.rowcount > 0:
            run_ids.append(row.run_id)
    await session.commit()
    return run_ids


async def fail_orphaned_runs(session: AsyncSession) -> list[str]:
    """Fails every run the previous process was holding — offered, running or cancelling — because the claim and the connection died with it. A `queued` run was never in any process and is not touched: `queued_runs` reads it back."""
    return await _fail_runs(session, runs.c.status.in_(["offering", "running", "cancelling"]))


async def queued_runs(session: AsyncSession) -> list[RunRecord]:
    """Every run still waiting for a provider, oldest first — the order each thread's turns were taken in."""
    rows = (
        await session.execute(
            select(runs).where(runs.c.status == "queued").order_by(runs.c.created_at, runs.c.run_id)
        )
    ).mappings().all()
    return [RunRecord(**row) for row in rows]


async def get_run(session: AsyncSession, run_id: str) -> RunRecord | None:
    row = (
        await session.execute(select(runs).where(runs.c.run_id == run_id))
    ).mappings().first()
    return RunRecord(**row) if row else None


async def append_run_event(session: AsyncSession, run_id: str, seq: int, event_json: dict[str, Any]) -> None:
    await session.execute(
        insert(run_events).values(run_id=run_id, seq=seq, event_json=event_json, created_at=_utcnow())
    )
    await session.commit()


async def get_run_events(session: AsyncSession, run_id: str, since_seq: int = 0) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(run_events.c.event_json)
            .where(run_events.c.run_id == run_id, run_events.c.seq > since_seq)
            .order_by(run_events.c.seq)
        )
    ).all()
    return [row.event_json for row in rows]


async def get_last_event_seq(session: AsyncSession, run_id: str) -> int:
    return (
        await session.execute(
            select(func.coalesce(func.max(run_events.c.seq), 0)).where(run_events.c.run_id == run_id)
        )
    ).scalar()
