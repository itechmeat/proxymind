"""add_parent_message_id_to_messages

Revision ID: 007
Revises: 006
Create Date: 2026-03-23 23:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "007"
down_revision: str | Sequence[str] | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("parent_message_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_messages_parent_message_id_messages",
        "messages",
        "messages",
        ["parent_message_id"],
        ["id"],
    )
    op.create_index(
        "ix_messages_parent_message_id",
        "messages",
        ["parent_message_id"],
        unique=False,
    )
    op.drop_index("uq_messages_idempotency_key_not_null", table_name="messages")
    op.create_index(
        "uq_messages_idempotency_key_not_null",
        "messages",
        ["session_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_messages_idempotency_key_not_null", table_name="messages")
    op.create_index(
        "uq_messages_idempotency_key_not_null",
        "messages",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index("ix_messages_parent_message_id", table_name="messages")
    op.drop_constraint(
        "fk_messages_parent_message_id_messages",
        "messages",
        type_="foreignkey",
    )
    op.drop_column("messages", "parent_message_id")
