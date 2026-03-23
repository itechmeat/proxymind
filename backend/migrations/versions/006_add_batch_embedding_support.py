"""add_batch_embedding_support

Revision ID: 006
Revises: 005
Create Date: 2026-03-23 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "006"
down_revision: str | Sequence[str] | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE background_task_type_enum ADD VALUE IF NOT EXISTS 'BATCH_EMBEDDING'"
        )

    op.add_column("batch_jobs", sa.Column("snapshot_id", sa.UUID(), nullable=True))
    op.add_column(
        "batch_jobs",
        sa.Column("source_ids", postgresql.ARRAY(sa.UUID()), nullable=True),
    )
    op.add_column("batch_jobs", sa.Column("background_task_id", sa.UUID(), nullable=True))
    op.add_column("batch_jobs", sa.Column("request_count", sa.Integer(), nullable=True))
    op.add_column("batch_jobs", sa.Column("succeeded_count", sa.Integer(), nullable=True))
    op.add_column("batch_jobs", sa.Column("failed_count", sa.Integer(), nullable=True))
    op.add_column(
        "batch_jobs",
        sa.Column("result_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "batch_jobs",
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index(op.f("ix_batch_jobs_snapshot_id"), "batch_jobs", ["snapshot_id"], unique=False)
    op.create_index(
        op.f("ix_batch_jobs_background_task_id"),
        "batch_jobs",
        ["background_task_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_batch_jobs_background_task_id_background_tasks",
        "batch_jobs",
        "background_tasks",
        ["background_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_batch_jobs_source_ids_gin",
        "batch_jobs",
        ["source_ids"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_batch_jobs_source_ids_gin", table_name="batch_jobs")
    op.drop_constraint(
        "fk_batch_jobs_background_task_id_background_tasks",
        "batch_jobs",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_batch_jobs_background_task_id"), table_name="batch_jobs")
    op.drop_index(op.f("ix_batch_jobs_snapshot_id"), table_name="batch_jobs")

    op.drop_column("batch_jobs", "last_polled_at")
    op.drop_column("batch_jobs", "result_metadata")
    op.drop_column("batch_jobs", "failed_count")
    op.drop_column("batch_jobs", "succeeded_count")
    op.drop_column("batch_jobs", "request_count")
    op.drop_column("batch_jobs", "background_task_id")
    op.drop_column("batch_jobs", "source_ids")
    op.drop_column("batch_jobs", "snapshot_id")

    op.execute("DELETE FROM background_tasks WHERE task_type = 'BATCH_EMBEDDING'")
    op.execute("ALTER TYPE background_task_type_enum RENAME TO background_task_type_enum_old")
    recreated_enum = postgresql.ENUM(
        "INGESTION",
        name="background_task_type_enum",
        create_type=False,
    )
    recreated_enum.create(op.get_bind(), checkfirst=False)
    op.execute(
        "ALTER TABLE background_tasks ALTER COLUMN task_type TYPE background_task_type_enum USING task_type::text::background_task_type_enum"
    )
    postgresql.ENUM(
        name="background_task_type_enum_old",
        create_type=False,
    ).drop(op.get_bind(), checkfirst=False)
