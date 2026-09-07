from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


_JSON = JSON().with_variant(JSONB(), "postgresql")

_TS = DateTime(timezone=True)

_BIGSERIAL = BigInteger().with_variant(Integer(), "sqlite")


providers = Table(
    "providers",
    metadata,
    Column("public_key", String, primary_key=True),
    Column("fingerprint", String, nullable=False, unique=True),
    Column("display_name", String, nullable=True),
    Column("updated_at", _TS, nullable=False, default=_utcnow),
)


agents = Table(
    "agents",
    metadata,
    Column("provider_key", String, ForeignKey("providers.public_key"), primary_key=True),
    Column("name", String, primary_key=True),
    Column("agent_card", _JSON, nullable=False),
    Column("metadata", _JSON, nullable=False, default=dict),
    Column("joined_at", _TS, nullable=False, default=_utcnow),
    Column("last_seen_at", _TS, nullable=False, default=_utcnow),
)


llm_providers = Table(
    "llm_providers",
    metadata,
    Column("provider_key", String, ForeignKey("providers.public_key"), primary_key=True),
    Column("name", String, primary_key=True),
    Column("metadata", _JSON, nullable=False, default=dict),
    Column("joined_at", _TS, nullable=False, default=_utcnow),
    Column("last_seen_at", _TS, nullable=False, default=_utcnow),
)


threads = Table(
    "threads",
    metadata,
    Column("thread_id", String, primary_key=True),
    Column("provider_key", String, nullable=False),
    Column("agent_name", String, nullable=False),
    Column("parent_thread_id", String, ForeignKey("threads.thread_id"), nullable=True),
    # The responsibility segment's head, copied from the first run's chain at the thread's birth; NULL = unbound (today's open behavior).
    Column("head_key", String, nullable=True),
    Column("metadata", _JSON, nullable=False, default=dict),
    Column("created_at", _TS, nullable=False, default=_utcnow),
    Column("last_activity_at", _TS, nullable=False, default=_utcnow),
    ForeignKeyConstraint(
        ["provider_key", "agent_name"], ["agents.provider_key", "agents.name"],
        name="fk_threads_agent",
    ),
    Index("idx_threads_parent", "parent_thread_id"),
)


# Every status a run row may carry. A run that finished asking for input is `completed` — AG-UI's own reading of a RUN_FINISHED with an interrupt outcome; whether a thread is waiting on an answer is read from that run's events, not stored.
RUN_STATUSES = (
    "queued",
    "offering",
    "running",
    "cancelling",
    "completed",
    "failed",
    "cancelled",
)

RUN_STATUS_CHECK = "status IN (%s)" % ", ".join(repr(s) for s in RUN_STATUSES)


# A run is an AG-UI run: `RunAgentInput`, one column per field (`messages` live in `thread_messages`), plus the state funduq holds about it. Nothing else.
runs = Table(
    "runs",
    metadata,
    Column("run_id", String, primary_key=True),
    Column("thread_id", String, ForeignKey("threads.thread_id"), nullable=False),
    Column("provider_key", String, nullable=False),
    Column("agent_name", String, nullable=False),
    Column("status", String, nullable=False),
    # The chain this run was **opened** under, hops and all, exactly as presented; NULL = none was carried. Its head is its first hop.
    Column("actor_chain", _JSON, nullable=True),
    Column("started_at", _TS, nullable=True),
    Column("completed_at", _TS, nullable=True),
    Column("last_activity_at", _TS, nullable=True),
    Column("created_at", _TS, nullable=False, default=_utcnow),
    # --- RunAgentInput ---
    Column("parent_run_id", String, nullable=True),
    Column("state", _JSON, nullable=True),
    Column("tools", _JSON, nullable=False, default=list),
    Column("context", _JSON, nullable=False, default=list),
    Column("forwarded_props", _JSON, nullable=True),
    Column("resume", _JSON, nullable=True),
    # --- state ---
    # Someone asked this run to stop, and who; NULL = nobody has.
    Column("cancel_requested_by", String, nullable=True),
    CheckConstraint(RUN_STATUS_CHECK, name="ck_runs_status"),
    ForeignKeyConstraint(
        ["provider_key", "agent_name"], ["agents.provider_key", "agents.name"],
        name="fk_runs_agent",
    ),
    Index("idx_runs_thread", "thread_id", "created_at"),
    Index("idx_runs_agent_status", "provider_key", "agent_name", "status"),
)


thread_messages = Table(
    "thread_messages",
    metadata,
    Column("id", _BIGSERIAL, primary_key=True, autoincrement=True),
    Column("thread_id", String, ForeignKey("threads.thread_id"), nullable=False),
    Column("run_id", String, ForeignKey("runs.run_id"), nullable=False),
    Column("message_id", String, nullable=False),
    Column("message_json", _JSON, nullable=False),
    Column("metadata", _JSON, nullable=False, default=dict),
    Column("created_at", _TS, nullable=False, default=_utcnow),
    # Who said it: the caller, whose run carried it in (so it is part of that run's `RunAgentInput`), or the agent, whose run produced it.
    Column("origin", String, nullable=False),
    CheckConstraint("origin IN ('caller', 'agent')", name="ck_thread_messages_origin"),
    UniqueConstraint("thread_id", "message_id", name="uq_thread_messages_thread_message"),
    Index("idx_thread_messages_thread", "thread_id", "id"),
)


run_events = Table(
    "run_events",
    metadata,
    Column("id", _BIGSERIAL, primary_key=True, autoincrement=True),
    Column("run_id", String, ForeignKey("runs.run_id"), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("event_json", _JSON, nullable=False),
    Column("created_at", _TS, nullable=False, default=_utcnow),
    Index("idx_run_events_run", "run_id", "seq"),
)
