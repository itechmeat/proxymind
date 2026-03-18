from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PrimaryKeyMixin, SoftDeleteMixin, TenantMixin, TimestampMixin
from app.db.models.enums import CatalogItemType, pg_enum

if TYPE_CHECKING:
    from app.db.models.knowledge import Source


class Agent(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agents"

    owner_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    active_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    default_knowledge_base_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    language: Mapped[str] = mapped_column(String(32), nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)


class CatalogItem(PrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "catalog_items"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_type: Mapped[CatalogItemType] = mapped_column(
        pg_enum(CatalogItemType, name="catalog_item_type_enum"),
        nullable=False,
    )
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    valid_from: Mapped[datetime | None] = mapped_column(nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(nullable=True)

    sources: Mapped[list[Source]] = relationship(back_populates="catalog_item")
