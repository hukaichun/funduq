"""Keep the chain a run arrived under, not only its head.

funduq copied the head key onto what needs an authority and kept nothing
else, so its records answered "who answers for this" and could never answer
"through whose hands". That was a decision about authority; the cost to
auditing was never weighed. A chain can be branched — a party rebuilds it
without the hands between the head and itself, forging nothing — and with no
chain on the record that erasure is not merely unprovable at verification
time, it is unnoticeable afterwards. See docs/mechanisms/actor-chain.md.

Nullable, because most runs carry no chain at all and a run that carried one
before this revision has nothing to backfill from: NULL means "none was
kept", which for old rows is the truth.

Revision ID: e7b3a94c1f60
Revises: c4d9e17b52aa
Create Date: 2026-08-25
"""

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
