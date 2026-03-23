from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.api.dependencies import (
    get_embedding_service,
    get_qdrant_service,
    get_snapshot_service,
)
from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models.enums import SnapshotStatus
from app.db.session import get_session
from app.services.qdrant import RetrievedChunk


def _retrieved_chunk(
    *, text_content: str = "This is test content about quantum physics."
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        text_content=text_content,
        score=0.85,
        anchor_metadata={
            "anchor_page": 5,
            "anchor_chapter": "Quantum Basics",
            "anchor_section": "Introduction",
            "anchor_timecode": None,
        },
    )


def _build_session_override(mock_session):
    async def _session_override():
        yield mock_session

    return _session_override


@pytest.mark.asyncio
async def test_draft_test_endpoint_returns_results_for_hybrid_mode(admin_app) -> None:
    draft_snapshot_id = uuid.uuid4()
    mock_snapshot = SimpleNamespace(
        id=draft_snapshot_id,
        name="Draft Snapshot",
        status=SnapshotStatus.DRAFT,
    )
    snapshot_service = SimpleNamespace(get_snapshot=AsyncMock(return_value=mock_snapshot))
    embedding_service = SimpleNamespace(embed_texts=AsyncMock(return_value=[[0.1, 0.2, 0.3]]))
    result_chunk = _retrieved_chunk()
    qdrant_service = SimpleNamespace(
        hybrid_search=AsyncMock(return_value=[result_chunk]),
        dense_search=AsyncMock(return_value=[]),
        keyword_search=AsyncMock(return_value=[]),
    )
    mock_source = SimpleNamespace(id=result_chunk.source_id, title="Test Source")
    mock_session = SimpleNamespace(
        scalar=AsyncMock(return_value=10),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [mock_source])),
    )

    admin_app.dependency_overrides[get_snapshot_service] = lambda: snapshot_service
    admin_app.dependency_overrides[get_embedding_service] = lambda: embedding_service
    admin_app.dependency_overrides[get_qdrant_service] = lambda: qdrant_service
    admin_app.dependency_overrides[get_session] = _build_session_override(mock_session)

    try:
        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                f"/api/admin/snapshots/{draft_snapshot_id}/test",
                json={"query": "  quantum physics  ", "mode": "hybrid", "top_n": 5},
            )
    finally:
        admin_app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_id"] == str(draft_snapshot_id)
    assert body["snapshot_name"] == "Draft Snapshot"
    assert body["query"] == "quantum physics"
    assert body["mode"] == "hybrid"
    assert body["total_chunks_in_draft"] == 10
    assert body["results"][0]["source_title"] == "Test Source"
    assert body["results"][0]["anchor"] == {
        "page": 5,
        "chapter": "Quantum Basics",
        "section": "Introduction",
        "timecode": None,
    }

    embedding_service.embed_texts.assert_awaited_once_with(
        ["quantum physics"],
        task_type="RETRIEVAL_QUERY",
    )
    qdrant_service.hybrid_search.assert_awaited_once_with(
        text="quantum physics",
        vector=[0.1, 0.2, 0.3],
        snapshot_id=draft_snapshot_id,
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        limit=5,
    )


@pytest.mark.asyncio
async def test_draft_test_endpoint_uses_dense_search_for_dense_mode(admin_app) -> None:
    draft_snapshot_id = uuid.uuid4()
    mock_snapshot = SimpleNamespace(
        id=draft_snapshot_id,
        name="Dense Draft",
        status=SnapshotStatus.DRAFT,
    )
    snapshot_service = SimpleNamespace(get_snapshot=AsyncMock(return_value=mock_snapshot))
    embedding_service = SimpleNamespace(embed_texts=AsyncMock(return_value=[[0.4, 0.5, 0.6]]))
    result_chunk = _retrieved_chunk()
    qdrant_service = SimpleNamespace(
        hybrid_search=AsyncMock(return_value=[]),
        dense_search=AsyncMock(return_value=[result_chunk]),
        keyword_search=AsyncMock(return_value=[]),
    )
    mock_source = SimpleNamespace(id=result_chunk.source_id, title="Dense Source")
    mock_session = SimpleNamespace(
        scalar=AsyncMock(return_value=4),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [mock_source])),
    )

    admin_app.dependency_overrides[get_snapshot_service] = lambda: snapshot_service
    admin_app.dependency_overrides[get_embedding_service] = lambda: embedding_service
    admin_app.dependency_overrides[get_qdrant_service] = lambda: qdrant_service
    admin_app.dependency_overrides[get_session] = _build_session_override(mock_session)

    try:
        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                f"/api/admin/snapshots/{draft_snapshot_id}/test",
                json={"query": "dense query", "mode": "dense", "top_n": 2},
            )
    finally:
        admin_app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["mode"] == "dense"
    embedding_service.embed_texts.assert_awaited_once()
    qdrant_service.dense_search.assert_awaited_once_with(
        vector=[0.4, 0.5, 0.6],
        snapshot_id=draft_snapshot_id,
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        limit=2,
    )
    qdrant_service.hybrid_search.assert_not_awaited()


@pytest.mark.asyncio
async def test_draft_test_endpoint_skips_embeddings_for_sparse_mode(admin_app) -> None:
    draft_snapshot_id = uuid.uuid4()
    mock_snapshot = SimpleNamespace(
        id=draft_snapshot_id,
        name="Sparse Draft",
        status=SnapshotStatus.DRAFT,
    )
    snapshot_service = SimpleNamespace(get_snapshot=AsyncMock(return_value=mock_snapshot))
    embedding_service = SimpleNamespace(embed_texts=AsyncMock())
    qdrant_service = SimpleNamespace(
        hybrid_search=AsyncMock(return_value=[]),
        dense_search=AsyncMock(return_value=[]),
        keyword_search=AsyncMock(return_value=[]),
    )
    mock_session = SimpleNamespace(
        scalar=AsyncMock(return_value=5),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [])),
    )

    admin_app.dependency_overrides[get_snapshot_service] = lambda: snapshot_service
    admin_app.dependency_overrides[get_embedding_service] = lambda: embedding_service
    admin_app.dependency_overrides[get_qdrant_service] = lambda: qdrant_service
    admin_app.dependency_overrides[get_session] = _build_session_override(mock_session)

    try:
        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                f"/api/admin/snapshots/{draft_snapshot_id}/test",
                json={"query": "sparse query", "mode": "sparse"},
            )
    finally:
        admin_app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["mode"] == "sparse"
    embedding_service.embed_texts.assert_not_awaited()
    qdrant_service.keyword_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_draft_test_endpoint_truncates_text_content_to_500_unicode_chars(admin_app) -> None:
    draft_snapshot_id = uuid.uuid4()
    mock_snapshot = SimpleNamespace(
        id=draft_snapshot_id,
        name="Unicode Draft",
        status=SnapshotStatus.DRAFT,
    )
    long_text = "界" * 700
    result_chunk = _retrieved_chunk(text_content=long_text)
    snapshot_service = SimpleNamespace(get_snapshot=AsyncMock(return_value=mock_snapshot))
    embedding_service = SimpleNamespace(embed_texts=AsyncMock(return_value=[[0.7, 0.8, 0.9]]))
    qdrant_service = SimpleNamespace(
        hybrid_search=AsyncMock(return_value=[result_chunk]),
        dense_search=AsyncMock(return_value=[]),
        keyword_search=AsyncMock(return_value=[]),
    )
    mock_source = SimpleNamespace(id=result_chunk.source_id, title="Unicode Source")
    mock_session = SimpleNamespace(
        scalar=AsyncMock(return_value=1),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [mock_source])),
    )

    admin_app.dependency_overrides[get_snapshot_service] = lambda: snapshot_service
    admin_app.dependency_overrides[get_embedding_service] = lambda: embedding_service
    admin_app.dependency_overrides[get_qdrant_service] = lambda: qdrant_service
    admin_app.dependency_overrides[get_session] = _build_session_override(mock_session)

    try:
        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                f"/api/admin/snapshots/{draft_snapshot_id}/test",
                json={"query": "unicode query", "mode": "hybrid"},
            )
    finally:
        admin_app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["results"][0]["text_content"] == long_text[:500]
