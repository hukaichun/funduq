"""A message id is the caller's or the agent's, unique within its run, not within its thread."""

from typing import Sequence, Union

from alembic import op

revision: str = "b5d2e8f0a7c4"
down_revision: Union[str, Sequence[str], None] = "a1f4c9d27e3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("thread_messages") as batch:
        batch.drop_constraint("uq_thread_messages_thread_message", type_="unique")
        batch.create_unique_constraint("uq_thread_messages_run_message", ["run_id", "message_id"])


def downgrade() -> None:
    with op.batch_alter_table("thread_messages") as batch:
        batch.drop_constraint("uq_thread_messages_run_message", type_="unique")
        batch.create_unique_constraint("uq_thread_messages_thread_message", ["thread_id", "message_id"])
