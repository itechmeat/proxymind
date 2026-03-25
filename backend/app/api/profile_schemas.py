from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class TwinProfileResponse(BaseModel):
    name: str
    has_avatar: bool


class ProfileUpdateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                raise ValueError("name must not be empty")
            return normalized
        return value


class AvatarUploadResponse(BaseModel):
    has_avatar: bool
