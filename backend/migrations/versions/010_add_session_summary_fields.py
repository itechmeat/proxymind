"""add_session_summary_fields

Revision ID: 010
Revises: 009
Create Date: 2026-03-26 20:00:00.000000

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("summary_token_count", sa.Integer(), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("summary_up_to_message_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_sessions_summary_up_to_message_id_messages",
        "sessions",
        "messages",
        ["summary_up_to_message_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_sessions_summary_up_to_message_id_messages",
        "sessions",
        type_="foreignkey",
    )
    op.drop_column("sessions", "summary_up_to_message_id")
    op.drop_column("sessions", "summary_token_count")
    op.drop_column("sessions", "summary")
