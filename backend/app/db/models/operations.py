from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PrimaryKeyMixin, TimestampMixin
from app.db.models.enums import BatchOperationType, BatchStatus, pg_enum


class AuditLog(PrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"

    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    source_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=True,
    )
    config_commit_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config_content_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    token_count_prompt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count_completion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retrieval_chunks_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class BatchJob(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "batch_jobs"

    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    knowledge_base_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    batch_operation_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation_type: Mapped[BatchOperationType] = mapped_column(
        pg_enum(BatchOperationType, name="batch_operation_type_enum"),
        nullable=False,
    )
    status: Mapped[BatchStatus] = mapped_column(
        pg_enum(BatchStatus, name="batch_status_enum"),
        nullable=False,
    )
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)
