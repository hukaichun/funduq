"""A run is an AG-UI run: RunAgentInput one column per field, plus funduq's state; nothing else. A thread message says who said it (#259)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1f4c9d27e3b"
down_revision: Union[str, Sequence[str], None] = "e7b3a94c1f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

_STATUSES = ("queued", "offering", "running", "cancelling", "completed", "failed", "cancelled")
_STATUS_CHECK = "status IN (%s)" % ", ".join(repr(s) for s in _STATUSES)


def upgrade() -> None:
    # Nothing is published and a restart already voids held runs, so rows are not migrated; the shape is.
    op.execute(sa.text("DELETE FROM run_events"))
    op.execute(sa.text("DELETE FROM thread_messages"))
    op.execute(sa.text("DELETE FROM runs"))
    with op.batch_alter_table("runs", recreate="always") as batch:
        batch.drop_constraint("ck_runs_protocol", type_="check")
        batch.drop_constraint("ck_runs_status", type_="check")
        batch.drop_column("protocol")
        batch.drop_column("head_key")
        batch.drop_column("input_json")
        batch.drop_column("metadata")
        batch.add_column(sa.Column("parent_run_id", sa.String(), nullable=True))
        batch.add_column(sa.Column("state", _JSON, nullable=True))
        batch.add_column(sa.Column("tools", _JSON, nullable=False))
        batch.add_column(sa.Column("context", _JSON, nullable=False))
        batch.add_column(sa.Column("forwarded_props", _JSON, nullable=True))
        batch.add_column(sa.Column("resume", _JSON, nullable=True))
        batch.add_column(sa.Column("cancel_requested_by", sa.String(), nullable=True))
        batch.create_check_constraint("ck_runs_status", _STATUS_CHECK)
    with op.batch_alter_table("thread_messages", recreate="always") as batch:
        batch.add_column(sa.Column("origin", sa.String(), nullable=False))
        batch.create_check_constraint("ck_thread_messages_origin", "origin IN ('caller', 'agent')")


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM run_events"))
    op.execute(sa.text("DELETE FROM thread_messages"))
    op.execute(sa.text("DELETE FROM runs"))
    with op.batch_alter_table("thread_messages", recreate="always") as batch:
        batch.drop_constraint("ck_thread_messages_origin", type_="check")
        batch.drop_column("origin")
    with op.batch_alter_table("runs", recreate="always") as batch:
        batch.drop_constraint("ck_runs_status", type_="check")
        for column in ("cancel_requested_by", "resume", "forwarded_props", "context", "tools", "state", "parent_run_id"):
            batch.drop_column(column)
        batch.add_column(sa.Column("protocol", sa.String(), nullable=False, server_default="ag-ui"))
        batch.add_column(sa.Column("head_key", sa.String(), nullable=True))
        batch.add_column(sa.Column("input_json", _JSON, nullable=False))
        batch.add_column(sa.Column("metadata", _JSON, nullable=False))
        batch.create_check_constraint("ck_runs_protocol", "protocol IN ('ag-ui', 'a2a')")
        batch.create_check_constraint(
            "ck_runs_status",
            "status IN ('queued', 'offering', 'running', 'input-required', 'cancelling', 'completed', 'failed', 'cancelled')",
        )
