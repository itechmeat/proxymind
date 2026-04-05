from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PrimaryKeyMixin, TimestampMixin
from app.db.models.enums import TokenType, UserStatus, pg_enum

if TYPE_CHECKING:
    from app.db.models.dialogue import Session


class User(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[UserStatus] = mapped_column(
        pg_enum(UserStatus, name="user_status_enum"),
        nullable=False,
        default=UserStatus.PENDING,
        server_default=text(f"'{UserStatus.PENDING.value}'"),
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(nullable=True)

    profile: Mapped[UserProfile] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    tokens: Mapped[list[UserToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    refresh_tokens: Mapped[list[UserRefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    sessions: Mapped[list[Session]] = relationship(
        backref="user",
        passive_deletes=True,
    )


class UserProfile(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "user_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_profiles_user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    user: Mapped[User] = relationship(back_populates="profile")


class UserToken(PrimaryKeyMixin, Base):
    __tablename__ = "user_tokens"
    __table_args__ = (
        Index("ix_user_tokens_token_hash", "token_hash"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    token_type: Mapped[TokenType] = mapped_column(
        pg_enum(TokenType, name="token_type_enum"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="tokens")


class UserRefreshToken(PrimaryKeyMixin, Base):
    __tablename__ = "user_refresh_tokens"
    __table_args__ = (
        Index("ix_user_refresh_tokens_token_hash", "token_hash"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    device_info: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())

    user: Mapped[User] = relationship(back_populates="refresh_tokens")
