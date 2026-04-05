"""add end user auth

Revision ID: 018
Revises: 017
Create Date: 2026-04-04 22:45:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "018"
down_revision: str | None = "017"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    user_status_enum = postgresql.ENUM(
        "pending",
        "active",
        "blocked",
        name="user_status_enum",
        create_type=False,
    )
    token_type_enum = postgresql.ENUM(
        "email_verification",
        "password_reset",
        name="token_type_enum",
        create_type=False,
    )
    user_status_enum.create(op.get_bind(), checkfirst=True)
    token_type_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", user_status_enum, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("avatar_url", sa.String(length=2048), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_profiles_user_id"),
    )

    op.create_table(
        "user_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("token_type", token_type_enum, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_user_tokens_token_hash"), "user_tokens", ["token_hash"], unique=False)
    op.create_index(op.f("ix_user_tokens_user_id"), "user_tokens", ["user_id"], unique=False)

    op.create_table(
        "user_refresh_tokens",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("device_info", sa.String(length=512), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_user_refresh_tokens_token_hash"),
        "user_refresh_tokens",
        ["token_hash"],
        unique=False,
    )
    op.create_index(
        op.f("ix_user_refresh_tokens_user_id"),
        "user_refresh_tokens",
        ["user_id"],
        unique=False,
    )

    op.alter_column("sessions", "visitor_id", new_column_name="user_id")
    # The renamed column contains legacy anonymous visitor identifiers, not rows from the
    # new users table. These values cannot satisfy the new users.id foreign key, so the
    # migration intentionally clears them before adding the FK. This data loss is
    # irreversible but preserves a consistent authenticated schema.
    op.execute(sa.text("UPDATE sessions SET user_id = NULL WHERE user_id IS NOT NULL"))
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False)
    op.create_foreign_key(
        "fk_sessions_user_id_users",
        "sessions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sessions_user_id_users", "sessions", type_="foreignkey")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions")
    op.alter_column("sessions", "user_id", new_column_name="visitor_id")

    op.drop_index(op.f("ix_user_refresh_tokens_user_id"), table_name="user_refresh_tokens")
    op.drop_index(op.f("ix_user_refresh_tokens_token_hash"), table_name="user_refresh_tokens")
    op.drop_table("user_refresh_tokens")

    op.drop_index(op.f("ix_user_tokens_user_id"), table_name="user_tokens")
    op.drop_index(op.f("ix_user_tokens_token_hash"), table_name="user_tokens")
    op.drop_table("user_tokens")

    op.drop_table("user_profiles")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    token_type_enum = postgresql.ENUM(
        "email_verification",
        "password_reset",
        name="token_type_enum",
        create_type=False,
    )
    user_status_enum = postgresql.ENUM(
        "pending",
        "active",
        "blocked",
        name="user_status_enum",
        create_type=False,
    )
    token_type_enum.drop(op.get_bind(), checkfirst=True)
    user_status_enum.drop(op.get_bind(), checkfirst=True)
