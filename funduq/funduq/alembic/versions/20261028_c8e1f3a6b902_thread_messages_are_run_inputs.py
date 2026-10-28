"""A thread message is what a run carried in; the agent's reply is the run's events, so who said it is no longer a column."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8e1f3a6b902"
down_revision: Union[str, Sequence[str], None] = "b5d2e8f0a7c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("DELETE FROM thread_messages WHERE origin = 'agent'"))
    with op.batch_alter_table("thread_messages") as batch:
        batch.drop_constraint("ck_thread_messages_origin", type_="check")
        batch.drop_column("origin")


def downgrade() -> None:
    with op.batch_alter_table("thread_messages") as batch:
        batch.add_column(sa.Column("origin", sa.String(), nullable=False, server_default="caller"))
        batch.create_check_constraint("ck_thread_messages_origin", "origin IN ('caller', 'agent')")
