from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

import httpx
import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user, verify_admin_key
from app.api.dependencies import get_storage_service
from app.api.profile_schemas import (
    AvatarUploadResponse,
    ProfileUpdateRequest,
    TwinProfileResponse,
)
from app.core.constants import DEFAULT_AGENT_ID
from app.db.models import Agent
from app.db.session import get_session
from app.services.storage import StorageService

chat_router = APIRouter(
    prefix="/api/chat",
    tags=["chat"],
    dependencies=[Depends(get_current_user)],
)
admin_router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(verify_admin_key)],
)

ALLOWED_AVATAR_CONTENT_TYPES = {
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
AVATAR_MIME_TYPE_BY_EXTENSION = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
MAX_AVATAR_SIZE_BYTES = 2 * 1024 * 1024
UPLOAD_READ_CHUNK_SIZE = 64 * 1024
logger = structlog.get_logger(__name__)


def _profile_response(agent: Agent) -> TwinProfileResponse:
    return TwinProfileResponse(name=agent.name, has_avatar=bool(agent.avatar_url))


async def _get_default_agent(session: AsyncSession) -> Agent:
    agent = await session.scalar(select(Agent).where(Agent.id == DEFAULT_AGENT_ID))
    if agent is None:
        raise HTTPException(status_code=404, detail="Default agent not found")
    return agent


async def _read_avatar_content(file: UploadFile) -> bytes:
    content = bytearray()

    while chunk := await file.read(UPLOAD_READ_CHUNK_SIZE):
        content.extend(chunk)
        if len(content) > MAX_AVATAR_SIZE_BYTES:
            raise HTTPException(status_code=422, detail="Avatar file exceeds 2 MB limit")

    if not content:
        raise HTTPException(status_code=422, detail="Avatar file must not be empty")

    return bytes(content)


def _detect_avatar_content_type(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _validate_avatar_content_type(content: bytes, declared_content_type: str | None) -> str:
    if declared_content_type not in ALLOWED_AVATAR_CONTENT_TYPES:
        raise HTTPException(status_code=422, detail="Avatar must be JPEG, PNG, WEBP, or GIF")

    detected_content_type = _detect_avatar_content_type(content)
    if detected_content_type != declared_content_type:
        raise HTTPException(
            status_code=422,
            detail="Avatar file contents must match the declared image type",
        )

    return detected_content_type


def _build_avatar_object_key(agent_id: uuid.UUID, extension: str) -> str:
    return f"agents/{agent_id}/avatar/{uuid.uuid7()}{extension}"


def _determine_avatar_mime_type(object_key: str) -> str:
    extension = Path(object_key).suffix.lower()
    mime_type = AVATAR_MIME_TYPE_BY_EXTENSION.get(extension)
    if mime_type is None:
        raise HTTPException(status_code=404, detail="Avatar format is not supported")
    return mime_type


async def _delete_avatar_with_warning(
    storage_service: StorageService,
    *,
    action: str,
    agent_id: uuid.UUID,
    avatar_key: str,
) -> None:
    try:
        await storage_service.delete(avatar_key)
    except Exception as error:
        logger.warning(
            "profile.avatar_cleanup_failed",
            action=action,
            agent_id=str(agent_id),
            avatar_key=avatar_key,
            error=str(error),
        )


@chat_router.get("/twin", response_model=TwinProfileResponse)
async def get_twin_profile(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TwinProfileResponse:
    agent = await _get_default_agent(session)
    return _profile_response(agent)


@chat_router.get("/twin/avatar")
async def get_twin_avatar(
    session: Annotated[AsyncSession, Depends(get_session)],
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
) -> Response:
    agent = await _get_default_agent(session)
    if not agent.avatar_url:
        raise HTTPException(status_code=404, detail="Avatar not found")

    try:
        content = await storage_service.download(agent.avatar_url)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            raise HTTPException(status_code=404, detail="Avatar not found") from error
        raise HTTPException(status_code=502, detail="Failed to download avatar") from error

    return Response(
        content=content,
        media_type=_determine_avatar_mime_type(agent.avatar_url),
        headers={"Cache-Control": "no-store"},
    )


@admin_router.put("/agent/profile", response_model=TwinProfileResponse)
async def update_twin_profile(
    payload: ProfileUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TwinProfileResponse:
    agent = await _get_default_agent(session)
    agent.name = payload.name
    await session.commit()
    await session.refresh(agent)
    return _profile_response(agent)


@admin_router.post("/agent/avatar", response_model=AvatarUploadResponse)
async def upload_twin_avatar(
    session: Annotated[AsyncSession, Depends(get_session)],
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
    file: UploadFile = File(...),
) -> AvatarUploadResponse:
    try:
        content = await _read_avatar_content(file)
        validated_content_type = _validate_avatar_content_type(content, file.content_type)
        agent = await _get_default_agent(session)
        extension = ALLOWED_AVATAR_CONTENT_TYPES[validated_content_type]
        previous_avatar_key = agent.avatar_url
        next_avatar_key = _build_avatar_object_key(agent.id, extension)

        try:
            await storage_service.upload(next_avatar_key, content, validated_content_type)
        except Exception as error:
            raise HTTPException(status_code=500, detail="Failed to upload avatar") from error

        agent.avatar_url = next_avatar_key
        await session.commit()

        if previous_avatar_key:
            await _delete_avatar_with_warning(
                storage_service,
                action="replace",
                agent_id=agent.id,
                avatar_key=previous_avatar_key,
            )

        return AvatarUploadResponse(has_avatar=True)
    finally:
        await file.close()


@admin_router.delete("/agent/avatar", response_model=AvatarUploadResponse)
async def delete_twin_avatar(
    session: Annotated[AsyncSession, Depends(get_session)],
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
) -> AvatarUploadResponse:
    agent = await _get_default_agent(session)
    previous_avatar_key = agent.avatar_url
    agent.avatar_url = None
    await session.commit()

    if previous_avatar_key:
        await _delete_avatar_with_warning(
            storage_service,
            action="delete",
            agent_id=agent.id,
            avatar_key=previous_avatar_key,
        )

    return AvatarUploadResponse(has_avatar=False)
