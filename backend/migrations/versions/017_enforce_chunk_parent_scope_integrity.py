"""enforce chunk parent scope integrity

Revision ID: 017
Revises: 016
Create Date: 2026-03-29 21:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "017"
down_revision: str | None = "016"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def _constraint_exists(name: str) -> bool:
    bind = op.get_bind()
    return (
        bind.execute(
            sa.text(
                "SELECT 1 FROM pg_constraint WHERE conname = :constraint_name"
            ),
            {"constraint_name": name},
        ).scalar()
        is not None
    )


def upgrade() -> None:
    if not _constraint_exists("uq_chunk_parents_scope_identity"):
        op.create_unique_constraint(
            "uq_chunk_parents_scope_identity",
            "chunk_parents",
            ["id", "document_version_id", "snapshot_id", "source_id"],
        )

    if not _constraint_exists("fk_chunks_parent_scope_chunk_parents"):
        op.create_foreign_key(
            "fk_chunks_parent_scope_chunk_parents",
            "chunks",
            "chunk_parents",
            ["parent_id", "document_version_id", "snapshot_id", "source_id"],
            ["id", "document_version_id", "snapshot_id", "source_id"],
        )


def downgrade() -> None:
    if _constraint_exists("fk_chunks_parent_scope_chunk_parents"):
        op.drop_constraint(
            "fk_chunks_parent_scope_chunk_parents",
            "chunks",
            type_="foreignkey",
        )
    if _constraint_exists("uq_chunk_parents_scope_identity"):
        op.drop_constraint(
            "uq_chunk_parents_scope_identity",
            "chunk_parents",
            type_="unique",
        )
