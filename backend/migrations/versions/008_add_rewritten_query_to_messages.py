"""add_rewritten_query_to_messages

Revision ID: 008
Revises: 007
Create Date: 2026-03-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: str | Sequence[str] | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("rewritten_query", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "rewritten_query")
