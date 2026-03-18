"""add_background_tasks_table

Revision ID: 003
Revises: 002
Create Date: 2026-03-18 21:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: str | Sequence[str] | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

background_task_type_enum = postgresql.ENUM(
    "INGESTION",
    name="background_task_type_enum",
    create_type=False,
)
background_task_status_enum = postgresql.ENUM(
    "PENDING",
    "PROCESSING",
    "COMPLETE",
    "FAILED",
    "CANCELLED",
    name="background_task_status_enum",
    create_type=False,
)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    background_task_type_enum.create(bind, checkfirst=True)
    background_task_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "background_tasks",
        sa.Column("task_type", background_task_type_enum, nullable=False),
        sa.Column("status", background_task_status_enum, nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=True),
        sa.Column("arq_job_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=True),
        sa.Column("result_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=True),
        sa.Column("agent_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "progress IS NULL OR (progress >= 0 AND progress <= 100)",
            name="ck_background_tasks_progress_range",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_background_tasks_agent_id"),
        "background_tasks",
        ["agent_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_background_tasks_owner_id"),
        "background_tasks",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_background_tasks_source_id"),
        "background_tasks",
        ["source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_background_tasks_status"),
        "background_tasks",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_background_tasks_status"), table_name="background_tasks")
    op.drop_index(op.f("ix_background_tasks_source_id"), table_name="background_tasks")
    op.drop_index(op.f("ix_background_tasks_owner_id"), table_name="background_tasks")
    op.drop_index(op.f("ix_background_tasks_agent_id"), table_name="background_tasks")
    op.drop_table("background_tasks")

    bind = op.get_bind()
    background_task_status_enum.drop(bind, checkfirst=True)
    background_task_type_enum.drop(bind, checkfirst=True)
