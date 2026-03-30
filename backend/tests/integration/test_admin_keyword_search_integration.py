from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.api.dependencies import get_qdrant_service, get_snapshot_service
from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.services.qdrant import RetrievedChunk


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
async def test_keyword_search_endpoint_exposes_bge_metadata_with_scoped_lookup(admin_app) -> None:
    active_snapshot_id = uuid.uuid4()
    qdrant_service = SimpleNamespace(
        keyword_search=AsyncMock(return_value=[_retrieved_chunk()]),
        bm25_language="english",
        sparse_backend="bge_m3",
        sparse_model="bge-m3",
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
            headers={"Authorization": f"Bearer {admin_app.state.settings.admin_api_key}"},
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
    assert body["language"] is None
    assert body["bm25_language"] == "english"
    assert body["sparse_backend"] == "bge_m3"
    assert body["sparse_model"] == "bge-m3"
    assert body["total"] == 1
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
