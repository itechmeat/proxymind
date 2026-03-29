"""make chunk parents owner nullable

Revision ID: 015
Revises: 014
Create Date: 2026-03-29 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "015"
down_revision: str | None = "014"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "chunk_parents",
        "owner_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE chunk_parents SET owner_id = agent_id WHERE owner_id IS NULL"
        )
    )
    op.alter_column(
        "chunk_parents",
        "owner_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
