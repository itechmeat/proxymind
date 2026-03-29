from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator


class EvalRetrieveRequest(BaseModel):
    query: str = Field(min_length=1)
    snapshot_id: uuid.UUID
    top_n: int = Field(default=5, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def validate_query_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query must not be blank")
        return normalized


class EvalChunkResponse(BaseModel):
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    score: float
    text: str
    rank: int = Field(ge=1)


class EvalRetrieveResponse(BaseModel):
    chunks: list[EvalChunkResponse]
    timing_ms: float
