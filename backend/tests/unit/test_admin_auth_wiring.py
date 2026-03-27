from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_API_KEY = "wiring-test-key-xyz"


@pytest.fixture
def authed_admin_app(
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
    mock_arq_pool: SimpleNamespace,
) -> FastAPI:
    from app.api.admin import router as admin_router
    from app.api.profile import admin_router as profile_admin_router

    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(profile_admin_router)
    app.state.settings = SimpleNamespace(
        admin_api_key=TEST_API_KEY,
        upload_max_file_size_mb=100,
        seaweedfs_sources_path="/sources",
        bm25_language="english",
        batch_max_items_per_request=1000,
    )
    app.state.session_factory = session_factory
    app.state.storage_service = mock_storage_service
    app.state.arq_pool = mock_arq_pool
    app.state.embedding_service = SimpleNamespace(
        model="gemini-embedding-2-preview",
        dimensions=3,
    )
    app.state.qdrant_service = SimpleNamespace(bm25_language="english")
    return app


@pytest_asyncio.fixture
async def authed_client(authed_admin_app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=authed_admin_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_admin_sources_without_key_returns_401(authed_client: httpx.AsyncClient) -> None:
    response = await authed_client.get("/api/admin/sources")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_sources_with_key_passes_auth(authed_client: httpx.AsyncClient) -> None:
    response = await authed_client.get(
        "/api/admin/sources",
        headers={"Authorization": f"Bearer {TEST_API_KEY}"},
    )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_profile_without_key_returns_401(authed_client: httpx.AsyncClient) -> None:
    response = await authed_client.put(
        "/api/admin/agent/profile",
        json={"name": "Test"},
    )

    assert response.status_code == 401
