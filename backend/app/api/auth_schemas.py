from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.db.models import User, UserProfile
from app.db.models.enums import UserStatus


def _normalize_optional_string(value: Any) -> Any:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=255)
    display_name: str | None = Field(default=None, max_length=255)

    _normalize_display_name = field_validator("display_name", mode="before")(
        _normalize_optional_string
    )


class SignInRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=255)


class RefreshRequest(BaseModel):
    refresh_token: str | None = None


class SignOutRequest(BaseModel):
    refresh_token: str | None = None


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=255)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MessageResponse(BaseModel):
    detail: str


class ProfilePayload(BaseModel):
    display_name: str | None
    avatar_url: str | None


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    status: UserStatus
    email_verified_at: datetime | None
    created_at: datetime
    profile: ProfilePayload

    @classmethod
    def from_models(cls, user: User, profile: UserProfile) -> UserProfileResponse:
        return cls(
            id=user.id,
            email=user.email,
            status=user.status,
            email_verified_at=user.email_verified_at,
            created_at=user.created_at,
            profile=ProfilePayload(
                display_name=profile.display_name,
                avatar_url=profile.avatar_url,
            ),
        )


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=2048)

    _normalize_display_name = field_validator("display_name", mode="before")(
        _normalize_optional_string
    )
    _normalize_avatar_url = field_validator("avatar_url", mode="before")(
        _normalize_optional_string
    )
