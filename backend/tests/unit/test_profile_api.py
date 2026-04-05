from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import profile as profile_api
from app.core.constants import DEFAULT_AGENT_ID
from app.db.models import Agent

PNG_BYTES = b"\x89PNG\r\n\x1a\navatar-bytes"


async def _load_agent(session_factory: async_sessionmaker[AsyncSession]) -> Agent:
    async with session_factory() as session:
        agent = await session.scalar(select(Agent).where(Agent.id == DEFAULT_AGENT_ID))
        assert agent is not None
        return agent


async def _update_agent(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    name: str | None = None,
    avatar_url: str | None = None,
) -> None:
    async with session_factory() as session:
        agent = await session.scalar(select(Agent).where(Agent.id == DEFAULT_AGENT_ID))
        assert agent is not None
        if name is not None:
            agent.name = name
        agent.avatar_url = avatar_url
        await session.commit()


@pytest.fixture
async def restore_twin_profile(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    agent = await _load_agent(session_factory)
    original_name = agent.name
    original_avatar_url = agent.avatar_url

    await _update_agent(
        session_factory,
        name=original_name,
        avatar_url=original_avatar_url,
    )
    yield
    await _update_agent(
        session_factory,
        name=original_name,
        avatar_url=original_avatar_url,
    )


@pytest.mark.asyncio
async def test_get_twin_profile_returns_name_and_avatar_state(
    user_profile_client,
    session_factory: async_sessionmaker[AsyncSession],
    restore_twin_profile,
) -> None:
    await _update_agent(
        session_factory,
        name="Marcus Aurelius",
        avatar_url="agents/00000000-0000-0000-0000-000000000001/avatar/test.png",
    )

    response = await user_profile_client.get("/api/chat/twin")

    assert response.status_code == 200
    assert response.json() == {
        "name": "Marcus Aurelius",
        "has_avatar": True,
    }


@pytest.mark.asyncio
async def test_update_profile_name_persists_change(
    profile_client,
    session_factory: async_sessionmaker[AsyncSession],
    restore_twin_profile,
) -> None:
    response = await profile_client.put(
        "/api/admin/agent/profile",
        json={"name": "  Seneca  "},
    )

    assert response.status_code == 200
    assert response.json() == {
        "name": "Seneca",
        "has_avatar": False,
    }

    agent = await _load_agent(session_factory)
    assert agent.name == "Seneca"


@pytest.mark.asyncio
async def test_update_profile_rejects_blank_name(
    profile_client,
    restore_twin_profile,
) -> None:
    response = await profile_client.put(
        "/api/admin/agent/profile",
        json={"name": "   "},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_profile_rejects_name_longer_than_255_chars(
    profile_client,
    restore_twin_profile,
) -> None:
    response = await profile_client.put(
        "/api/admin/agent/profile",
        json={"name": "x" * 256},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_upload_avatar_rejects_non_image_file(
    profile_client,
    mock_storage_service: SimpleNamespace,
    restore_twin_profile,
) -> None:
    response = await profile_client.post(
        "/api/admin/agent/avatar",
        files={"file": ("notes.txt", b"not an image", "text/plain")},
    )

    assert response.status_code == 422
    mock_storage_service.upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_avatar_rejects_spoofed_content_type(
    profile_client,
    mock_storage_service: SimpleNamespace,
    restore_twin_profile,
) -> None:
    response = await profile_client.post(
        "/api/admin/agent/avatar",
        files={"file": ("avatar.png", b"not-a-real-png", "image/png")},
    )

    assert response.status_code == 422
    mock_storage_service.upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_avatar_rejects_oversized_file(
    profile_client,
    mock_storage_service: SimpleNamespace,
    restore_twin_profile,
) -> None:
    response = await profile_client.post(
        "/api/admin/agent/avatar",
        files={
            "file": (
                "big.png",
                b"x" * (2 * 1024 * 1024 + 1),
                "image/png",
            )
        },
    )

    assert response.status_code == 422
    mock_storage_service.upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_avatar_persists_object_key_and_replaces_previous_avatar(
    profile_client,
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
    restore_twin_profile,
) -> None:
    await _update_agent(
        session_factory,
        avatar_url="agents/00000000-0000-0000-0000-000000000001/avatar/old.png",
    )

    response = await profile_client.post(
        "/api/admin/agent/avatar",
        files={"file": ("avatar.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 200
    assert response.json() == {"has_avatar": True}
    mock_storage_service.upload.assert_awaited_once()
    mock_storage_service.delete.assert_awaited_once_with(
        "agents/00000000-0000-0000-0000-000000000001/avatar/old.png"
    )

    agent = await _load_agent(session_factory)
    assert agent.avatar_url is not None
    assert re.fullmatch(
        r"agents/00000000-0000-0000-0000-000000000001/avatar/[0-9a-f-]+\.png",
        agent.avatar_url,
    )


@pytest.mark.asyncio
async def test_upload_avatar_logs_warning_when_previous_avatar_cleanup_fails(
    profile_client,
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
    restore_twin_profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning = Mock()
    monkeypatch.setattr(profile_api.logger, "warning", warning)
    mock_storage_service.delete.side_effect = RuntimeError("storage delete failed")
    await _update_agent(
        session_factory,
        avatar_url="agents/00000000-0000-0000-0000-000000000001/avatar/old.png",
    )

    response = await profile_client.post(
        "/api/admin/agent/avatar",
        files={"file": ("avatar.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 200
    warning.assert_called_once_with(
        "profile.avatar_cleanup_failed",
        action="replace",
        agent_id=str(DEFAULT_AGENT_ID),
        avatar_key="agents/00000000-0000-0000-0000-000000000001/avatar/old.png",
        error="storage delete failed",
    )


@pytest.mark.asyncio
async def test_get_avatar_returns_404_when_missing(
    user_profile_client,
    session_factory: async_sessionmaker[AsyncSession],
    restore_twin_profile,
) -> None:
    await _update_agent(session_factory, avatar_url=None)

    response = await user_profile_client.get("/api/chat/twin/avatar")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_avatar_returns_bytes_and_content_type(
    user_profile_client,
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
    restore_twin_profile,
) -> None:
    await _update_agent(
        session_factory,
        avatar_url="agents/00000000-0000-0000-0000-000000000001/avatar/test.png",
    )
    mock_storage_service.download.return_value = b"png-avatar"

    response = await user_profile_client.get("/api/chat/twin/avatar")

    assert response.status_code == 200
    assert response.content == b"png-avatar"
    assert response.headers["content-type"] == "image/png"
    mock_storage_service.download.assert_awaited_once_with(
        "agents/00000000-0000-0000-0000-000000000001/avatar/test.png"
    )


@pytest.mark.asyncio
async def test_guest_cannot_access_twin_profile(profile_app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=profile_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/chat/twin")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_guest_cannot_access_twin_avatar(profile_app: FastAPI) -> None:
    transport = httpx.ASGITransport(app=profile_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/chat/twin/avatar")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_delete_avatar_clears_profile_and_deletes_file(
    profile_client,
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
    restore_twin_profile,
) -> None:
    await _update_agent(
        session_factory,
        avatar_url="agents/00000000-0000-0000-0000-000000000001/avatar/old.png",
    )

    response = await profile_client.delete("/api/admin/agent/avatar")

    assert response.status_code == 200
    assert response.json() == {"has_avatar": False}
    mock_storage_service.delete.assert_awaited_once_with(
        "agents/00000000-0000-0000-0000-000000000001/avatar/old.png"
    )

    agent = await _load_agent(session_factory)
    assert agent.avatar_url is None


@pytest.mark.asyncio
async def test_delete_avatar_logs_warning_when_storage_cleanup_fails(
    profile_client,
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
    restore_twin_profile,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning = Mock()
    monkeypatch.setattr(profile_api.logger, "warning", warning)
    mock_storage_service.delete.side_effect = RuntimeError("storage delete failed")
    await _update_agent(
        session_factory,
        avatar_url="agents/00000000-0000-0000-0000-000000000001/avatar/old.png",
    )

    response = await profile_client.delete("/api/admin/agent/avatar")

    assert response.status_code == 200
    warning.assert_called_once_with(
        "profile.avatar_cleanup_failed",
        action="delete",
        agent_id=str(DEFAULT_AGENT_ID),
        avatar_key="agents/00000000-0000-0000-0000-000000000001/avatar/old.png",
        error="storage delete failed",
    )

    agent = await _load_agent(session_factory)
    assert agent.avatar_url is None


@pytest.mark.asyncio
async def test_delete_avatar_without_existing_avatar_is_still_successful(
    profile_client,
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
    restore_twin_profile,
) -> None:
    await _update_agent(session_factory, avatar_url=None)

    response = await profile_client.delete("/api/admin/agent/avatar")

    assert response.status_code == 200
    assert response.json() == {"has_avatar": False}
    mock_storage_service.delete.assert_not_awaited()
