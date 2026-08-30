"""Keep the chain a run arrived under, not only its head."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7b3a94c1f60"
down_revision: Union[str, Sequence[str], None] = "c4d9e17b52aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.add_column("runs", sa.Column("actor_chain", _JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "actor_chain")
