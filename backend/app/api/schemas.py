from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, UrlConstraints, field_validator

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models.background_task import BackgroundTask
from app.services.qdrant import RetrievedChunk


class SourceUploadMetadata(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    public_url: Annotated[AnyHttpUrl, UrlConstraints(max_length=2048)] | None = None
    catalog_item_id: uuid.UUID | None = None
    language: str | None = Field(default=None, max_length=32)
    processing_hint: Literal["auto", "external"] = "auto"

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


class KeywordSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    snapshot_id: uuid.UUID | None = None
    agent_id: uuid.UUID = Field(default=DEFAULT_AGENT_ID)
    knowledge_base_id: uuid.UUID = Field(default=DEFAULT_KNOWLEDGE_BASE_ID)
    limit: int = Field(default=10, ge=1, le=100)

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized
        return value


class KeywordSearchAnchor(BaseModel):
    page: int | None = None
    chapter: str | None = None
    section: str | None = None
    timecode: str | None = None


class KeywordSearchResult(BaseModel):
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    text_content: str
    score: float
    anchor: KeywordSearchAnchor

    @classmethod
    def from_retrieved_chunk(cls, chunk: RetrievedChunk) -> KeywordSearchResult:
        return cls(
            chunk_id=chunk.chunk_id,
            source_id=chunk.source_id,
            text_content=chunk.text_content,
            score=chunk.score,
            anchor=KeywordSearchAnchor(
                page=chunk.anchor_metadata.get("anchor_page"),
                chapter=chunk.anchor_metadata.get("anchor_chapter"),
                section=chunk.anchor_metadata.get("anchor_section"),
                timecode=chunk.anchor_metadata.get("anchor_timecode"),
            ),
        )


class KeywordSearchResponse(BaseModel):
    query: str
    language: str | None
    bm25_language: str
    sparse_backend: str
    sparse_model: str
    total: int
    results: list[KeywordSearchResult]
