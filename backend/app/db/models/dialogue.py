from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PrimaryKeyMixin, TenantMixin, TimestampMixin
from app.db.models.enums import (
    MessageRole,
    MessageStatus,
    SessionChannel,
    SessionStatus,
    pg_enum,
)


class Session(PrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "sessions"

    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    status: Mapped[SessionStatus] = mapped_column(
        pg_enum(SessionStatus, name="session_status_enum"),
        nullable=False,
    )
    message_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    channel: Mapped[SessionChannel] = mapped_column(
        pg_enum(SessionChannel, name="session_channel_enum"),
        nullable=False,
        default=SessionChannel.WEB,
        server_default=text(f"'{SessionChannel.WEB.value}'"),
    )
    channel_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    visitor_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    external_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel_connector: Mapped[str | None] = mapped_column(String(255), nullable=True)

    messages: Mapped[list[Message]] = relationship(
        back_populates="session",
        order_by="Message.created_at",
    )


class Message(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_session_id", "session_id"),
        Index("ix_messages_parent_message_id", "parent_message_id"),
        Index(
            "uq_messages_idempotency_key_not_null",
            "session_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id"), nullable=False)
    parent_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id"),
        nullable=True,
        default=None,
    )
    role: Mapped[MessageRole] = mapped_column(
        pg_enum(MessageRole, name="message_role_enum"),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[MessageStatus] = mapped_column(
        pg_enum(MessageStatus, name="message_status_enum"),
        nullable=False,
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    source_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=True,
    )
    citations: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    content_type_spans: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    token_count_prompt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count_completion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config_commit_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config_content_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rewritten_query: Mapped[str | None] = mapped_column(Text, nullable=True)

    session: Mapped[Session] = relationship(back_populates="messages")
