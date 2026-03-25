from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models.enums import SourceStatus, SourceType


class SourceListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_type: SourceType
    status: SourceStatus
    description: str | None
    public_url: str | None
    file_size_bytes: int | None
    language: str | None
    created_at: datetime


class SourceDeleteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_type: SourceType
    status: SourceStatus
    deleted_at: datetime | None
    warnings: list[str]
