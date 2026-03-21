from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from qdrant_client import models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from app.db.models.enums import ChunkStatus, SourceType
from app.services.qdrant import (
    PAYLOAD_INDEX_FIELDS,
    CollectionSchemaMismatchError,
    QdrantChunkPoint,
    QdrantService,
    RetrievedChunk,
)


def _collection_info(size: int) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(vectors={"dense": SimpleNamespace(size=size)})
        )
    )


@pytest.mark.asyncio
async def test_ensure_collection_creates_named_dense_vector_and_indexes() -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=False),
        create_collection=AsyncMock(),
        create_payload_index=AsyncMock(),
    )
    service = QdrantService(
        client=client,  # type: ignore[arg-type]
        collection_name="proxymind_chunks",
        embedding_dimensions=3072,
    )

    await service.ensure_collection()

    client.create_collection.assert_awaited_once()
    kwargs = client.create_collection.await_args.kwargs
    assert kwargs["collection_name"] == "proxymind_chunks"
    assert kwargs["vectors_config"]["dense"].size == 3072
    assert kwargs["vectors_config"]["dense"].distance is models.Distance.COSINE
    assert client.create_payload_index.await_count == len(PAYLOAD_INDEX_FIELDS)


@pytest.mark.asyncio
async def test_ensure_collection_is_idempotent_for_matching_schema() -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=_collection_info(3072)),
        create_collection=AsyncMock(),
        create_payload_index=AsyncMock(),
    )
    service = QdrantService(
        client=client,  # type: ignore[arg-type]
        collection_name="proxymind_chunks",
        embedding_dimensions=3072,
    )

    await service.ensure_collection()

    client.create_collection.assert_not_awaited()
    assert client.create_payload_index.await_count == len(PAYLOAD_INDEX_FIELDS)


@pytest.mark.asyncio
async def test_ensure_collection_handles_duplicate_create_race() -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=False),
        create_collection=AsyncMock(
            side_effect=UnexpectedResponse(
                status_code=409,
                reason_phrase="Conflict",
                content=b'{"status":{"error":"Collection already exists"}}',
                headers=httpx.Headers(),
            )
        ),
        get_collection=AsyncMock(return_value=_collection_info(3072)),
        create_payload_index=AsyncMock(),
    )
    service = QdrantService(
        client=client,  # type: ignore[arg-type]
        collection_name="proxymind_chunks",
        embedding_dimensions=3072,
    )

    await service.ensure_collection()

    client.create_collection.assert_awaited_once()
    client.get_collection.assert_awaited_once_with("proxymind_chunks")
    assert client.create_payload_index.await_count == len(PAYLOAD_INDEX_FIELDS)


@pytest.mark.asyncio
async def test_ensure_collection_raises_on_dimension_mismatch() -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=_collection_info(3072)),
        create_payload_index=AsyncMock(),
    )
    service = QdrantService(
        client=client,  # type: ignore[arg-type]
        collection_name="proxymind_chunks",
        embedding_dimensions=1024,
    )

    with pytest.raises(CollectionSchemaMismatchError, match="existing=3072, required=1024"):
        await service.ensure_collection()


@pytest.mark.asyncio
async def test_upsert_chunks_sends_named_vector_payload() -> None:
    client = SimpleNamespace(upsert=AsyncMock())
    service = QdrantService(
        client=client,  # type: ignore[arg-type]
        collection_name="proxymind_chunks",
        embedding_dimensions=3,
    )
    point = QdrantChunkPoint(
        chunk_id=uuid.uuid4(),
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        text_content="chunk body",
        chunk_index=0,
        token_count=12,
        anchor_page=None,
        anchor_chapter="Chapter",
        anchor_section="Section",
        anchor_timecode=None,
        source_type=SourceType.MARKDOWN,
        language="english",
        status=ChunkStatus.INDEXED,
    )

    await service.upsert_chunks([point])

    client.upsert.assert_awaited_once()
    points = client.upsert.await_args.kwargs["points"]
    assert len(points) == 1
    assert points[0].vector == {"dense": [0.1, 0.2, 0.3]}
    assert points[0].payload["text_content"] == "chunk body"
    assert points[0].payload["source_type"] == "markdown"


@pytest.mark.asyncio
async def test_upsert_chunks_retries_transient_connection_errors() -> None:
    client = SimpleNamespace(
        upsert=AsyncMock(
            side_effect=[
                ResponseHandlingException(httpx.ConnectError("boom")),
                None,
            ]
        )
    )
    service = QdrantService(
        client=client,  # type: ignore[arg-type]
        collection_name="proxymind_chunks",
        embedding_dimensions=3,
    )
    point = QdrantChunkPoint(
        chunk_id=uuid.uuid4(),
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        text_content="chunk body",
        chunk_index=0,
        token_count=12,
        anchor_page=None,
        anchor_chapter=None,
        anchor_section=None,
        anchor_timecode=None,
        source_type=SourceType.MARKDOWN,
        language=None,
        status=ChunkStatus.INDEXED,
    )

    await service.upsert_chunks([point])

    assert client.upsert.await_count == 2


@pytest.mark.asyncio
async def test_delete_chunks_sends_point_ids_to_qdrant() -> None:
    client = SimpleNamespace(delete=AsyncMock())
    service = QdrantService(
        client=client,  # type: ignore[arg-type]
        collection_name="proxymind_chunks",
        embedding_dimensions=3,
    )
    chunk_ids = [uuid.uuid4(), uuid.uuid4()]

    await service.delete_chunks(chunk_ids)

    client.delete.assert_awaited_once()
    kwargs = client.delete.await_args.kwargs
    assert kwargs["collection_name"] == "proxymind_chunks"
    assert kwargs["wait"] is True
    assert kwargs["points_selector"].points == [str(chunk_id) for chunk_id in chunk_ids]


@pytest.mark.asyncio
async def test_search_builds_dense_query_with_scope_filters() -> None:
    snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    source_id = uuid.uuid4()
    client = SimpleNamespace(
        query_points=AsyncMock(
            return_value=SimpleNamespace(
                points=[
                    SimpleNamespace(
                        score=0.91,
                        payload={
                            "chunk_id": str(chunk_id),
                            "source_id": str(source_id),
                            "text_content": "retrieved body",
                            "anchor_page": 7,
                            "anchor_chapter": "Ch. 1",
                            "anchor_section": "Intro",
                            "anchor_timecode": None,
                        },
                    )
                ]
            )
        )
    )
    service = QdrantService(
        client=client,  # type: ignore[arg-type]
        collection_name="proxymind_chunks",
        embedding_dimensions=3,
    )

    results = await service.search(
        vector=[0.1, 0.2, 0.3],
        snapshot_id=snapshot_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        limit=5,
        score_threshold=0.5,
    )

    assert results == [
        RetrievedChunk(
            chunk_id=chunk_id,
            source_id=source_id,
            text_content="retrieved body",
            score=0.91,
            anchor_metadata={
                "anchor_page": 7,
                "anchor_chapter": "Ch. 1",
                "anchor_section": "Intro",
                "anchor_timecode": None,
            },
        )
    ]
    kwargs = client.query_points.await_args.kwargs
    assert kwargs["query"] == [0.1, 0.2, 0.3]
    assert kwargs["using"] == "dense"
    assert kwargs["limit"] == 5
    assert kwargs["score_threshold"] == 0.5
    filters = kwargs["query_filter"].must
    assert [(condition.key, condition.match.value) for condition in filters] == [
        ("snapshot_id", str(snapshot_id)),
        ("agent_id", str(agent_id)),
        ("knowledge_base_id", str(knowledge_base_id)),
    ]


@pytest.mark.asyncio
async def test_search_omits_score_threshold_when_disabled() -> None:
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service = QdrantService(
        client=client,  # type: ignore[arg-type]
        collection_name="proxymind_chunks",
        embedding_dimensions=3,
    )

    results = await service.search(
        vector=[0.3, 0.2, 0.1],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=3,
        score_threshold=None,
    )

    assert results == []
    kwargs = client.query_points.await_args.kwargs
    assert "score_threshold" not in kwargs


@pytest.mark.asyncio
async def test_search_returns_empty_list_when_qdrant_finds_nothing() -> None:
    client = SimpleNamespace(query_points=AsyncMock(return_value=SimpleNamespace(points=[])))
    service = QdrantService(
        client=client,  # type: ignore[arg-type]
        collection_name="proxymind_chunks",
        embedding_dimensions=3,
    )

    results = await service.search(
        vector=[0.9, 0.1, 0.0],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=2,
    )

    assert results == []
