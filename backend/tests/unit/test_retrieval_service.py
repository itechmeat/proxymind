from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.services.qdrant import RetrievedChunk
from app.services.retrieval import RetrievalError, RetrievalService


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        text_content="retrieved",
        score=0.88,
        anchor_metadata={
            "anchor_page": None,
            "anchor_chapter": None,
            "anchor_section": None,
            "anchor_timecode": None,
        },
    )


@pytest.mark.asyncio
async def test_search_calls_hybrid_search_with_text_and_vector() -> None:
    embedding_service = AsyncMock()
    embedding_service.embed_texts.return_value = [[0.1, 0.2, 0.3]]
    qdrant_service = AsyncMock()
    qdrant_service.hybrid_search.return_value = [_chunk()]
    service = RetrievalService(
        embedding_service=embedding_service,
        qdrant_service=qdrant_service,
        top_n=5,
        min_dense_similarity=0.4,
    )
    snapshot_id = uuid.uuid4()

    results = await service.search("Where is the answer?", snapshot_id=snapshot_id)

    assert results == qdrant_service.hybrid_search.return_value
    embedding_service.embed_texts.assert_awaited_once_with(
        ["Where is the answer?"],
        task_type="RETRIEVAL_QUERY",
    )
    qdrant_service.hybrid_search.assert_awaited_once_with(
        text="Where is the answer?",
        vector=[0.1, 0.2, 0.3],
        snapshot_id=snapshot_id,
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        limit=5,
        score_threshold=0.4,
    )


@pytest.mark.asyncio
async def test_search_supports_empty_results() -> None:
    embedding_service = AsyncMock()
    embedding_service.embed_texts.return_value = [[0.1, 0.2, 0.3]]
    qdrant_service = AsyncMock()
    qdrant_service.hybrid_search.return_value = []
    service = RetrievalService(
        embedding_service=embedding_service,
        qdrant_service=qdrant_service,
        top_n=3,
        min_dense_similarity=None,
    )

    results = await service.search("No hits", snapshot_id=uuid.uuid4())

    assert results == []


@pytest.mark.asyncio
async def test_search_respects_explicit_zero_top_n() -> None:
    embedding_service = AsyncMock()
    embedding_service.embed_texts.return_value = [[0.1, 0.2, 0.3]]
    qdrant_service = AsyncMock()
    qdrant_service.hybrid_search.return_value = []
    service = RetrievalService(
        embedding_service=embedding_service,
        qdrant_service=qdrant_service,
        top_n=3,
        min_dense_similarity=None,
    )
    snapshot_id = uuid.uuid4()

    await service.search("No hits", snapshot_id=snapshot_id, top_n=0)

    qdrant_service.hybrid_search.assert_awaited_once_with(
        text="No hits",
        vector=[0.1, 0.2, 0.3],
        snapshot_id=snapshot_id,
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        limit=0,
        score_threshold=None,
    )


@pytest.mark.asyncio
async def test_search_wraps_failures_in_retrieval_error() -> None:
    embedding_service = AsyncMock()
    embedding_service.embed_texts.side_effect = RuntimeError("embedding failed")
    service = RetrievalService(
        embedding_service=embedding_service,
        qdrant_service=AsyncMock(),
        top_n=3,
        min_dense_similarity=None,
    )

    with pytest.raises(RetrievalError, match="Retrieval failed"):
        await service.search("boom", snapshot_id=uuid.uuid4())
