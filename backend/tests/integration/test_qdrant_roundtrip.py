from __future__ import annotations

import uuid

import pytest
from qdrant_client import AsyncQdrantClient, models

from app.db.models.enums import ChunkStatus, SourceType
from app.services.qdrant import (
    BM25_VECTOR_NAME,
    CollectionSchemaMismatchError,
    QdrantChunkPoint,
    QdrantService,
    RetrievedChunk,
)


def _point(
    *,
    chunk_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    agent_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    vector: list[float],
    text_content: str,
    source_id: uuid.UUID | None = None,
) -> QdrantChunkPoint:
    return QdrantChunkPoint(
        chunk_id=chunk_id,
        vector=vector,
        snapshot_id=snapshot_id,
        source_id=source_id or uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        text_content=text_content,
        chunk_index=0,
        token_count=4,
        anchor_page=None,
        anchor_chapter="Chapter",
        anchor_section="Section",
        anchor_timecode=None,
        source_type=SourceType.MARKDOWN,
        language="english",
        status=ChunkStatus.INDEXED,
    )


async def _cleanup_collection(client: AsyncQdrantClient, collection_name: str) -> None:
    if await client.collection_exists(collection_name):
        await client.delete_collection(collection_name)


@pytest.mark.asyncio
async def test_qdrant_round_trip_filters_by_snapshot_id(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=3,
        bm25_language="english",
    )
    snapshot_id = uuid.uuid4()
    other_snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    other_agent_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    other_knowledge_base_id = uuid.uuid4()
    matched_chunk_id = uuid.uuid4()
    matched_source_id = uuid.uuid4()

    try:
        await service.ensure_collection()
        await service.upsert_chunks(
            [
                _point(
                    chunk_id=matched_chunk_id,
                    snapshot_id=snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[1.0, 0.0, 0.0],
                    text_content="matched chunk",
                    source_id=matched_source_id,
                ),
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=other_snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[0.0, 1.0, 0.0],
                    text_content="other chunk",
                ),
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=snapshot_id,
                    agent_id=other_agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[1.0, 0.0, 0.0],
                    text_content="other agent chunk",
                ),
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=other_knowledge_base_id,
                    vector=[1.0, 0.0, 0.0],
                    text_content="other knowledge base chunk",
                ),
            ]
        )

        response = await service.search(
            vector=[1.0, 0.0, 0.0],
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            limit=5,
        )

        assert len(response) == 1
        assert response[0] == RetrievedChunk(
            chunk_id=matched_chunk_id,
            source_id=matched_source_id,
            text_content="matched chunk",
            score=response[0].score,
            anchor_metadata={
                "anchor_page": None,
                "anchor_chapter": "Chapter",
                "anchor_section": "Section",
                "anchor_timecode": None,
            },
        )
    finally:
        await _cleanup_collection(client, collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_dimension_mismatch_raises(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service_3072 = QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=3072,
        bm25_language="english",
    )
    service_1024 = QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=1024,
        bm25_language="english",
    )

    try:
        await service_3072.ensure_collection()
        with pytest.raises(CollectionSchemaMismatchError, match="existing=3072, required=1024"):
            await service_1024.ensure_collection()
    finally:
        await _cleanup_collection(client, collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_ensure_collection_is_idempotent(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=3,
        bm25_language="english",
    )

    try:
        await service.ensure_collection()
        await service.ensure_collection()
    finally:
        await _cleanup_collection(client, collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_keyword_search_filters_by_snapshot_id(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=3,
        bm25_language="english",
    )
    snapshot_id = uuid.uuid4()
    other_snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    matched_chunk_id = uuid.uuid4()
    matched_source_id = uuid.uuid4()

    try:
        await service.ensure_collection()
        await service.upsert_chunks(
            [
                _point(
                    chunk_id=matched_chunk_id,
                    snapshot_id=snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[1.0, 0.0, 0.0],
                    text_content="deployment guide",
                    source_id=matched_source_id,
                ),
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=other_snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[0.0, 1.0, 0.0],
                    text_content="deployment guide",
                ),
            ]
        )

        response = await service.keyword_search(
            text="deployment",
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            limit=5,
        )

        assert len(response) == 1
        assert response[0] == RetrievedChunk(
            chunk_id=matched_chunk_id,
            source_id=matched_source_id,
            text_content="deployment guide",
            score=response[0].score,
            anchor_metadata={
                "anchor_page": None,
                "anchor_chapter": "Chapter",
                "anchor_section": "Section",
                "anchor_timecode": None,
            },
        )
    finally:
        await _cleanup_collection(client, collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_keyword_search_applies_english_stemming(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=3,
        bm25_language="english",
    )
    snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    try:
        await service.ensure_collection()
        await service.upsert_chunks(
            [
                _point(
                    chunk_id=chunk_id,
                    snapshot_id=snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[1.0, 0.0, 0.0],
                    text_content="the service runs nightly",
                )
            ]
        )

        response = await service.keyword_search(
            text="running",
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            limit=5,
        )

        assert [chunk.chunk_id for chunk in response] == [chunk_id]
    finally:
        await _cleanup_collection(client, collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_ensure_collection_recreates_dense_only_schema(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=3,
        bm25_language="english",
    )

    try:
        await client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": models.VectorParams(size=3, distance=models.Distance.COSINE)
            },
        )

        await service.ensure_collection()

        collection_info = await client.get_collection(collection_name)
        sparse_vectors = collection_info.config.params.sparse_vectors
        if hasattr(sparse_vectors, "get"):
            assert sparse_vectors.get(BM25_VECTOR_NAME) is not None
        else:
            assert getattr(sparse_vectors, BM25_VECTOR_NAME, None) is not None
    finally:
        await _cleanup_collection(client, collection_name)
        await client.close()
