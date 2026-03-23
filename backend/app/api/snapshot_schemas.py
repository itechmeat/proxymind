from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models.enums import SnapshotStatus


class SnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agent_id: uuid.UUID | None
    knowledge_base_id: uuid.UUID | None
    name: str
    description: str | None
    status: SnapshotStatus
    published_at: datetime | None
    activated_at: datetime | None
    archived_at: datetime | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class RollbackSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    status: SnapshotStatus
    published_at: datetime | None
    activated_at: datetime | None


class RollbackResponse(BaseModel):
    rolled_back_from: RollbackSnapshotResponse
    rolled_back_to: RollbackSnapshotResponse


class RetrievalMode(StrEnum):
    HYBRID = "hybrid"
    DENSE = "dense"
    SPARSE = "sparse"


class DraftTestRequest(BaseModel):
    query: str
    top_n: int = Field(default=5, ge=1, le=100)
    mode: RetrievalMode = RetrievalMode.HYBRID

    @field_validator("query")
    @classmethod
    def strip_query(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("query must not be empty")
        return trimmed


class DraftTestAnchor(BaseModel):
    page: int | None = None
    chapter: str | None = None
    section: str | None = None
    timecode: str | None = None


class DraftTestResult(BaseModel):
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    source_title: str | None = None
    text_content: str
    score: float
    anchor: DraftTestAnchor


class DraftTestResponse(BaseModel):
    snapshot_id: uuid.UUID
    snapshot_name: str
    query: str
    mode: RetrievalMode
    results: list[DraftTestResult]
    total_chunks_in_draft: int
