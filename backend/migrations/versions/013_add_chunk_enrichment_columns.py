"""add chunk enrichment columns

Revision ID: 013
Revises: 012
Create Date: 2026-03-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "013"
down_revision: str | None = "012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("enriched_summary", sa.Text(), nullable=True))
    op.add_column(
        "chunks",
        sa.Column("enriched_keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "chunks",
        sa.Column("enriched_questions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("chunks", sa.Column("enriched_text", sa.Text(), nullable=True))
    op.add_column("chunks", sa.Column("enrichment_model", sa.String(length=100), nullable=True))
    op.add_column(
        "chunks",
        sa.Column("enrichment_pipeline_version", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chunks", "enrichment_pipeline_version")
    op.drop_column("chunks", "enrichment_model")
    op.drop_column("chunks", "enriched_text")
    op.drop_column("chunks", "enriched_questions")
    op.drop_column("chunks", "enriched_keywords")
    op.drop_column("chunks", "enriched_summary")
