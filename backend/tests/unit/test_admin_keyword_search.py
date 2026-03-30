from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.api.dependencies import get_qdrant_service, get_snapshot_service
from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.services.qdrant import RetrievedChunk


def _admin_headers(admin_app) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_app.state.settings.admin_api_key}"}


def _retrieved_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        text_content="deployment guide",
        score=3.5,
        anchor_metadata={
            "anchor_page": 12,
            "anchor_chapter": "Operations",
            "anchor_section": "Deploy",
            "anchor_timecode": None,
        },
    )


@pytest.mark.asyncio
async def test_keyword_search_endpoint_returns_results_using_active_snapshot_defaults(
    admin_app,
) -> None:
    active_snapshot_id = uuid.uuid4()
    qdrant_service = SimpleNamespace(
        keyword_search=AsyncMock(return_value=[_retrieved_chunk()]),
        bm25_language="english",
        sparse_backend="bm25",
        sparse_model="Qdrant/bm25",
    )
    snapshot_service = SimpleNamespace(
        get_active_snapshot=AsyncMock(return_value=SimpleNamespace(id=active_snapshot_id))
    )
    admin_app.dependency_overrides[get_qdrant_service] = lambda: qdrant_service
    admin_app.dependency_overrides[get_snapshot_service] = lambda: snapshot_service

    try:
        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers=_admin_headers(admin_app),
        ) as client:
            response = await client.post(
                "/api/admin/search/keyword",
                json={"query": "deployment"},
            )
    finally:
        admin_app.dependency_overrides.pop(get_qdrant_service, None)
        admin_app.dependency_overrides.pop(get_snapshot_service, None)

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "deployment"
    assert body["language"] == "english"
    assert body["bm25_language"] == "english"
    assert body["sparse_backend"] == "bm25"
    assert body["sparse_model"] == "Qdrant/bm25"
    assert body["total"] == 1
    assert body["results"][0]["text_content"] == "deployment guide"
    assert body["results"][0]["anchor"] == {
        "page": 12,
        "chapter": "Operations",
        "section": "Deploy",
        "timecode": None,
    }
    snapshot_service.get_active_snapshot.assert_awaited_once_with(
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
    )
    qdrant_service.keyword_search.assert_awaited_once_with(
        text="deployment",
        snapshot_id=active_snapshot_id,
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        limit=10,
    )


@pytest.mark.asyncio
async def test_keyword_search_endpoint_returns_422_when_active_snapshot_missing(
    admin_app,
) -> None:
    qdrant_service = SimpleNamespace(
        keyword_search=AsyncMock(return_value=[]),
        bm25_language="english",
        sparse_backend="bm25",
        sparse_model="Qdrant/bm25",
    )
    snapshot_service = SimpleNamespace(get_active_snapshot=AsyncMock(return_value=None))
    admin_app.dependency_overrides[get_qdrant_service] = lambda: qdrant_service
    admin_app.dependency_overrides[get_snapshot_service] = lambda: snapshot_service

    try:
        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers=_admin_headers(admin_app),
        ) as client:
            response = await client.post(
                "/api/admin/search/keyword",
                json={"query": "deployment"},
            )
    finally:
        admin_app.dependency_overrides.pop(get_qdrant_service, None)
        admin_app.dependency_overrides.pop(get_snapshot_service, None)

    assert response.status_code == 422
    assert response.json()["detail"] == "No active snapshot found for the requested scope"
    qdrant_service.keyword_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_keyword_search_endpoint_uses_explicit_snapshot_id_without_active_lookup(
    admin_app,
) -> None:
    explicit_snapshot_id = uuid.uuid4()
    qdrant_service = SimpleNamespace(
        keyword_search=AsyncMock(return_value=[]),
        bm25_language="english",
        sparse_backend="bm25",
        sparse_model="Qdrant/bm25",
    )
    snapshot_service = SimpleNamespace(get_active_snapshot=AsyncMock(return_value=None))
    admin_app.dependency_overrides[get_qdrant_service] = lambda: qdrant_service
    admin_app.dependency_overrides[get_snapshot_service] = lambda: snapshot_service

    try:
        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers=_admin_headers(admin_app),
        ) as client:
            response = await client.post(
                "/api/admin/search/keyword",
                json={
                    "query": "deployment",
                    "snapshot_id": str(explicit_snapshot_id),
                },
            )
    finally:
        admin_app.dependency_overrides.pop(get_qdrant_service, None)
        admin_app.dependency_overrides.pop(get_snapshot_service, None)

    assert response.status_code == 200
    snapshot_service.get_active_snapshot.assert_not_awaited()
    qdrant_service.keyword_search.assert_awaited_once_with(
        text="deployment",
        snapshot_id=explicit_snapshot_id,
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        limit=10,
    )


@pytest.mark.asyncio
async def test_keyword_search_endpoint_rejects_empty_query(admin_app) -> None:
    qdrant_service = SimpleNamespace(
        keyword_search=AsyncMock(return_value=[]),
        bm25_language="english",
        sparse_backend="bm25",
        sparse_model="Qdrant/bm25",
    )
    snapshot_service = SimpleNamespace(get_active_snapshot=AsyncMock(return_value=None))
    admin_app.dependency_overrides[get_qdrant_service] = lambda: qdrant_service
    admin_app.dependency_overrides[get_snapshot_service] = lambda: snapshot_service

    try:
        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers=_admin_headers(admin_app),
        ) as client:
            response = await client.post(
                "/api/admin/search/keyword",
                json={"query": "   "},
            )
    finally:
        admin_app.dependency_overrides.pop(get_qdrant_service, None)
        admin_app.dependency_overrides.pop(get_snapshot_service, None)

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "string_too_short"
    qdrant_service.keyword_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_keyword_search_endpoint_rejects_client_supplied_sparse_fields(admin_app) -> None:
    qdrant_service = SimpleNamespace(
        keyword_search=AsyncMock(return_value=[]),
        bm25_language="english",
        sparse_backend="bm25",
        sparse_model="Qdrant/bm25",
    )
    snapshot_service = SimpleNamespace(get_active_snapshot=AsyncMock(return_value=None))
    admin_app.dependency_overrides[get_qdrant_service] = lambda: qdrant_service
    admin_app.dependency_overrides[get_snapshot_service] = lambda: snapshot_service

    try:
        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            headers=_admin_headers(admin_app),
        ) as client:
            response = await client.post(
                "/api/admin/search/keyword",
                json={"query": "deployment", "sparse_backend": "bge_m3"},
            )
    finally:
        admin_app.dependency_overrides.pop(get_qdrant_service, None)
        admin_app.dependency_overrides.pop(get_snapshot_service, None)

    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"
    qdrant_service.keyword_search.assert_not_awaited()
