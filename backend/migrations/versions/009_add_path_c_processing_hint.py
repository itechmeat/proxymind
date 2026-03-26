"""add_path_c_processing_hint

Revision ID: 009
Revises: 008
Create Date: 2026-03-26 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009"
down_revision: str | Sequence[str] | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE processing_path_enum ADD VALUE IF NOT EXISTS 'path_c'")

    op.add_column("document_versions", sa.Column("processing_hint", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("document_versions", "processing_hint")
