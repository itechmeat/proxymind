from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, UrlConstraints, field_validator

from app.db.models.background_task import BackgroundTask


class SourceUploadMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    public_url: Annotated[AnyHttpUrl, UrlConstraints(max_length=2048)] | None = None
    catalog_item_id: uuid.UUID | None = None
    language: str | None = Field(default=None, max_length=32)

    @field_validator("language", mode="before")
    @classmethod
    def normalize_language(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value


class SourceUploadResponse(BaseModel):
    source_id: uuid.UUID
    task_id: uuid.UUID
    status: str
    file_path: str
    message: str


class TaskStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_type: str
    status: str
    source_id: uuid.UUID | None
    progress: int | None
    error_message: str | None
    result_metadata: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None

    @classmethod
    def from_task(cls, task: BackgroundTask) -> TaskStatusResponse:
        return cls(
            id=task.id,
            task_type=task.task_type.value.lower(),
            status=task.status.value.lower(),
            source_id=task.source_id,
            progress=task.progress,
            error_message=task.error_message,
            result_metadata=task.result_metadata,
            created_at=task.created_at,
            started_at=task.started_at,
            completed_at=task.completed_at,
        )
