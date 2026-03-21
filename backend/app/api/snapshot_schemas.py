from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

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
