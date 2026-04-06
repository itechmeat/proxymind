from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.persona.loader import PersonaContext
from app.services.conversation_memory import ConversationMemoryService
from app.services.promotions import PromotionsService

from tests.unit.test_rate_limit import FakeRedis

TEST_KEY = "integration-test-key-456"


def _ok_response(url: str) -> httpx.Response:
    request = httpx.Request("GET", url)
    return httpx.Response(200, request=request)


@pytest.fixture
def secure_app(
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
    mock_arq_pool: SimpleNamespace,
    mock_retrieval_service: SimpleNamespace,
    mock_llm_service: SimpleNamespace,
    mock_rewrite_service: SimpleNamespace,
) -> FastAPI:
    from app.api.admin import router as admin_router
    from app.api.chat import router as chat_router
    from app.api.health import router as health_router
    from app.middleware.rate_limit import RateLimitMiddleware

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        admin_api_key=TEST_KEY,
        chat_rate_limit=3,
        chat_rate_window_seconds=60,
        jwt_access_token_expire_minutes=15,
        jwt_secret_key=SecretStr("test-jwt-secret-key-with-32-plus-chars"),
        trusted_proxy_depth=1,
        upload_max_file_size_mb=100,
        seaweedfs_sources_path="/sources",
        bm25_language="english",
        batch_max_items_per_request=1000,
        min_retrieved_chunks=1,
        max_citations_per_response=5,
        retrieval_context_budget=4096,
        max_promotions_per_response=1,
        sse_heartbeat_interval_seconds=15,
        sse_inter_token_timeout_seconds=30,
        conversation_memory_budget=4096,
        conversation_summary_ratio=0.3,
        qdrant_url="http://qdrant:6333",
        seaweedfs_filer_url="http://seaweedfs:8888",
    )
    app.state.session_factory = session_factory
    app.state.storage_service = mock_storage_service
    app.state.arq_pool = mock_arq_pool
    app.state.embedding_service = SimpleNamespace(
        model="gemini-embedding-2-preview",
        dimensions=3,
    )
    app.state.qdrant_service = SimpleNamespace(
        bm25_language="english",
        hybrid_search=AsyncMock(return_value=[]),
        dense_search=AsyncMock(return_value=[]),
    )
    app.state.retrieval_service = mock_retrieval_service
    app.state.llm_service = mock_llm_service
    app.state.query_rewrite_service = mock_rewrite_service
    app.state.persona_context = PersonaContext(
        identity="Test identity",
        soul="Test soul",
        behavior="Test behavior",
        config_commit_hash="test-commit",
        config_content_hash="test-content-hash",
    )
    app.state.promotions_service = PromotionsService(promotions_text="")
    app.state.conversation_memory_service = ConversationMemoryService(
        budget=4096,
        summary_ratio=0.3,
    )
    app.state.redis_client = FakeRedis()
    app.state.http_client = SimpleNamespace(
        get=AsyncMock(side_effect=lambda url: _ok_response(url)),
    )
    app.add_middleware(RateLimitMiddleware)
    app.include_router(admin_router)
    app.include_router(chat_router)
    app.include_router(health_router)
    return app


@pytest_asyncio.fixture
async def secure_client(secure_app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=secure_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture
async def secure_chat_client(
    secure_app: FastAPI,
    create_user,
    make_user_auth_headers,
) -> httpx.AsyncClient:
    user = await create_user()
    transport = httpx.ASGITransport(app=secure_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=make_user_auth_headers(user),
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_admin_auth_full_flow(secure_client: httpx.AsyncClient) -> None:
    no_key_response = await secure_client.get("/api/admin/sources")
    wrong_key_response = await secure_client.get(
        "/api/admin/sources",
        headers={"Authorization": "Bearer wrong"},
    )
    ok_response = await secure_client.get(
        "/api/admin/sources",
        headers={"Authorization": f"Bearer {TEST_KEY}"},
    )

    assert no_key_response.status_code == 401
    assert wrong_key_response.status_code == 401
    assert ok_response.status_code == 200


@pytest.mark.asyncio
async def test_admin_auth_me_endpoint_requires_a_valid_key(
    secure_client: httpx.AsyncClient,
) -> None:
    no_key_response = await secure_client.get("/api/admin/auth/me")
    wrong_key_response = await secure_client.get(
        "/api/admin/auth/me",
        headers={"Authorization": "Bearer wrong"},
    )
    ok_response = await secure_client.get(
        "/api/admin/auth/me",
        headers={"Authorization": f"Bearer {TEST_KEY}"},
    )

    assert no_key_response.status_code == 401
    assert wrong_key_response.status_code == 401
    assert ok_response.status_code == 200
    assert ok_response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_chat_rate_limit_full_flow(secure_chat_client: httpx.AsyncClient) -> None:
    for _ in range(3):
        response = await secure_chat_client.post("/api/chat/sessions", json={})
        assert response.status_code == 201

    limited_response = await secure_chat_client.post("/api/chat/sessions", json={})

    assert limited_response.status_code == 429
    assert "retry-after" in limited_response.headers


@pytest.mark.asyncio
async def test_service_endpoints_not_affected(secure_client: httpx.AsyncClient) -> None:
    health_response = await secure_client.get("/health")
    ready_response = await secure_client.get("/ready")

    assert health_response.status_code == 200
    assert ready_response.status_code == 200
    assert "x-ratelimit-limit" not in health_response.headers
    assert "x-ratelimit-limit" not in ready_response.headers
    assert ready_response.status_code != 401
