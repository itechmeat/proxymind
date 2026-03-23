from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.operations import BatchJob


class BatchEmbedRequest(BaseModel):
    source_ids: list[uuid.UUID] = Field(min_length=1)


class BatchEmbedResponse(BaseModel):
    task_id: uuid.UUID
    batch_job_id: uuid.UUID
    chunk_count: int
    message: str


class BatchJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    operation_type: str
    status: str
    item_count: int | None
    processed_count: int | None
    succeeded_count: int | None
    failed_count: int | None
    created_at: datetime
    last_polled_at: datetime | None

    @classmethod
    def from_batch_job(cls, obj: BatchJob) -> BatchJobResponse:
        return cls(
            id=obj.id,
            operation_type=obj.operation_type.value,
            status=obj.status.value,
            item_count=obj.item_count,
            processed_count=obj.processed_count,
            succeeded_count=obj.succeeded_count,
            failed_count=obj.failed_count,
            created_at=obj.created_at,
            last_polled_at=obj.last_polled_at,
        )


class BatchJobListResponse(BaseModel):
    items: list[BatchJobResponse]
    total: int


class BatchJobDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID
    knowledge_base_id: uuid.UUID | None
    snapshot_id: uuid.UUID | None
    task_id: str | None
    source_ids: list[uuid.UUID] | None
    background_task_id: uuid.UUID | None
    batch_operation_name: str | None
    operation_type: str
    status: str
    item_count: int | None
    processed_count: int | None
    request_count: int | None
    succeeded_count: int | None
    failed_count: int | None
    error_message: str | None
    result_metadata: dict[str, Any] | None
    last_polled_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_batch_job(cls, obj: BatchJob) -> BatchJobDetailResponse:
        return cls(
            id=obj.id,
            agent_id=obj.agent_id,
            knowledge_base_id=obj.knowledge_base_id,
            snapshot_id=obj.snapshot_id,
            task_id=obj.task_id,
            source_ids=obj.source_ids,
            background_task_id=obj.background_task_id,
            batch_operation_name=obj.batch_operation_name,
            operation_type=obj.operation_type.value,
            status=obj.status.value,
            item_count=obj.item_count,
            processed_count=obj.processed_count,
            request_count=obj.request_count,
            succeeded_count=obj.succeeded_count,
            failed_count=obj.failed_count,
            error_message=obj.error_message,
            result_metadata=obj.result_metadata,
            last_polled_at=obj.last_polled_at,
            started_at=obj.started_at,
            completed_at=obj.completed_at,
            created_at=obj.created_at,
            updated_at=obj.updated_at,
        )
