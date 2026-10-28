"""Whether a run was asked to stop is its own column; who asked stays NULL on an unbound run instead of an empty string."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4a7c2e9f150"
down_revision: Union[str, Sequence[str], None] = "c8e1f3a6b902"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(sa.text("UPDATE runs SET cancel_requested = :yes WHERE cancel_requested_by IS NOT NULL").bindparams(yes=True))
    op.execute(sa.text("UPDATE runs SET cancel_requested_by = NULL WHERE cancel_requested_by = ''"))


def downgrade() -> None:
    op.execute(sa.text("UPDATE runs SET cancel_requested_by = '' WHERE cancel_requested AND cancel_requested_by IS NULL"))
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("cancel_requested")
