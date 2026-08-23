"""Widen ck_runs_status with "offering": the dispatch window is a state.

Between funduq handing a run to a provider and the provider answering,
"queued" and "running" are both untrue — nobody has the run yet, and nobody
has accepted it either. The window used to be invisible in the record, which
is why a cancel arriving inside it could be recorded against a run that was
handed over a moment later. See docs/mechanisms/requests.md.

Revision ID: c4d9e17b52aa
Revises: a11c3b7d42e9
Create Date: 2026-08-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4d9e17b52aa"
down_revision: Union[str, Sequence[str], None] = "a11c3b7d42e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BEFORE = (
    "status IN ('queued', 'running', 'input-required', 'cancelling', "
    "'completed', 'failed', 'cancelled')"
)
_AFTER = (
    "status IN ('queued', 'offering', 'running', 'input-required', 'cancelling', "
    "'completed', 'failed', 'cancelled')"
)

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _runs(status_check: str) -> sa.Table:
    """The `runs` table as this revision knows it, frozen here rather than
    imported from `funduq.schema`.

    SQLite cannot alter a CHECK constraint, so batch mode rebuilds the table
    — and it rebuilds it from whatever definition it is handed. Handing it
    the live metadata would make this migration mean something different
    every time a later revision changes the table; a copy that cannot drift
    is the point.
    """
    return sa.Table(
        "runs",
        sa.MetaData(),
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("thread_id", sa.String(), sa.ForeignKey("threads.thread_id"), nullable=False),
        sa.Column("provider_key", sa.String(), nullable=False),
        sa.Column("agent_name", sa.String(), nullable=False),
        sa.Column("protocol", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("head_key", sa.String(), nullable=True),
        sa.Column("input_json", _JSON, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", _JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("protocol IN ('ag-ui', 'a2a')", name="ck_runs_protocol"),
        sa.CheckConstraint(status_check, name="ck_runs_status"),
        sa.ForeignKeyConstraint(
            ["provider_key", "agent_name"], ["agents.provider_key", "agents.name"],
            name="fk_runs_agent",
        ),
        sa.Index("idx_runs_thread", "thread_id", "created_at"),
        sa.Index("idx_runs_agent_status", "provider_key", "agent_name", "status"),
    )


def _replace_status_check(new_check: str) -> None:
    with op.batch_alter_table("runs", copy_from=_runs(new_check)) as batch:
        batch.drop_constraint("ck_runs_status", type_="check")
        batch.create_check_constraint("ck_runs_status", new_check)


def upgrade() -> None:
    _replace_status_check(_AFTER)


def downgrade() -> None:
    # An "offering" run is one funduq was mid-handover on; the pre-revision
    # vocabulary has no word for that, and the nearest true one is where it
    # came from.
    op.execute(sa.text("UPDATE runs SET status = 'queued' WHERE status = 'offering'"))
    _replace_status_check(_BEFORE)
