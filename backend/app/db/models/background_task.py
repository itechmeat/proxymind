from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, PrimaryKeyMixin, TenantMixin, TimestampMixin
from app.db.models.enums import BackgroundTaskStatus, BackgroundTaskType, pg_enum

if TYPE_CHECKING:
    from app.db.models.knowledge import Source


class BackgroundTask(PrimaryKeyMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "background_tasks"
    __table_args__ = (
        CheckConstraint(
            "progress IS NULL OR (progress >= 0 AND progress <= 100)",
            name="ck_background_tasks_progress_range",
        ),
    )

    task_type: Mapped[BackgroundTaskType] = mapped_column(
        pg_enum(BackgroundTaskType, name="background_task_type_enum"),
        nullable=False,
    )
    status: Mapped[BackgroundTaskStatus] = mapped_column(
        pg_enum(BackgroundTaskStatus, name="background_task_status_enum"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("sources.id"),
        nullable=True,
        index=True,
    )
    arq_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    source: Mapped[Source | None] = relationship(back_populates="background_tasks")
