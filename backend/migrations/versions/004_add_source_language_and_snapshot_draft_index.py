"""add_source_language_and_snapshot_draft_index

Revision ID: 004
Revises: 003
Create Date: 2026-03-19 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: str | Sequence[str] | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sources", sa.Column("language", sa.String(length=32), nullable=True))
    op.create_index(
        "uq_one_draft_per_scope",
        "knowledge_snapshots",
        ["agent_id", "knowledge_base_id"],
        unique=True,
        postgresql_where=sa.text("status = 'draft'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_one_draft_per_scope", table_name="knowledge_snapshots")
    op.drop_column("sources", "language")
