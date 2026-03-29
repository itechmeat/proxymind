"""add chunk parents for s9 02

Revision ID: 014
Revises: 013
Create Date: 2026-03-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "014"
down_revision: str | None = "013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chunk_parents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id"),
            nullable=False,
        ),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_index", sa.Integer(), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("anchor_page", sa.Integer(), nullable=True),
        sa.Column("anchor_chapter", sa.String(length=255), nullable=True),
        sa.Column("anchor_section", sa.String(length=255), nullable=True),
        sa.Column("anchor_timecode", sa.String(length=64), nullable=True),
        sa.Column("heading_path", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint(
            "document_version_id",
            "parent_index",
            name="uq_chunk_parents_document_version_id_parent_index",
        ),
    )
    op.create_index("ix_chunk_parents_snapshot_id", "chunk_parents", ["snapshot_id"])
    op.create_index("ix_chunk_parents_source_id", "chunk_parents", ["source_id"])

    op.add_column("chunks", sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_chunks_parent_id_chunk_parents",
        "chunks",
        "chunk_parents",
        ["parent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_chunks_parent_id", "chunks", ["parent_id"])


def downgrade() -> None:
    op.drop_index("ix_chunks_parent_id", table_name="chunks")
    op.drop_constraint("fk_chunks_parent_id_chunk_parents", "chunks", type_="foreignkey")
    op.drop_column("chunks", "parent_id")
    op.drop_index("ix_chunk_parents_source_id", table_name="chunk_parents")
    op.drop_index("ix_chunk_parents_snapshot_id", table_name="chunk_parents")
    op.drop_table("chunk_parents")
