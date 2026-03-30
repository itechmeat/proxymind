from __future__ import annotations

import uuid
from dataclasses import replace

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
from app.services.sparse_providers import Bm25SparseProvider, SparseProviderMetadata


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


def _service(
    *,
    client: AsyncQdrantClient,
    collection_name: str,
    embedding_dimensions: int,
) -> QdrantService:
    return QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=embedding_dimensions,
        sparse_provider=Bm25SparseProvider(language="english"),
        bm25_language="english",
    )


class _StaticSparseProvider:
    def __init__(
        self,
        *,
        backend: str,
        model_name: str,
        document_vector: models.SparseVector,
        query_vector: models.SparseVector,
    ) -> None:
        self.metadata = SparseProviderMetadata(
            backend=backend,
            model_name=model_name,
            contract_version="v1",
        )
        self._document_vector = document_vector
        self._query_vector = query_vector

    async def build_document_representation(self, text: str) -> models.SparseVector:
        return self._document_vector

    async def build_query_representation(self, text: str) -> models.SparseVector:
        return self._query_vector

    async def aclose(self) -> None:
        return None


def _bge_service(
    *,
    client: AsyncQdrantClient,
    collection_name: str,
    embedding_dimensions: int,
    sparse_vector: models.SparseVector | None = None,
) -> QdrantService:
    vector = sparse_vector or models.SparseVector(indices=[1, 7], values=[0.8, 0.2])
    return QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=embedding_dimensions,
        sparse_provider=_StaticSparseProvider(
            backend="bge_m3",
            model_name="bge-m3",
            document_vector=vector,
            query_vector=vector,
        ),
        bm25_language="english",
    )


@pytest.mark.asyncio
async def test_qdrant_dense_search_filters_by_snapshot_id(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = _service(client=client, collection_name=collection_name, embedding_dimensions=3)
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

        response = await service.dense_search(
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
async def test_qdrant_hybrid_search_returns_results(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = _service(client=client, collection_name=collection_name, embedding_dimensions=3)
    snapshot_id = uuid.uuid4()
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
                )
            ]
        )

        response = await service.hybrid_search(
            text="deployment",
            vector=[1.0, 0.0, 0.0],
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            limit=5,
        )

        assert response == [
            RetrievedChunk(
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
        ]
    finally:
        await _cleanup_collection(client, collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_roundtrip_preserves_parent_metadata(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = _service(client=client, collection_name=collection_name, embedding_dimensions=3)
    snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    source_id = uuid.uuid4()

    try:
        await service.ensure_collection()
        await service.upsert_chunks(
            [
                replace(
                    _point(
                        chunk_id=uuid.uuid4(),
                        snapshot_id=snapshot_id,
                        agent_id=agent_id,
                        knowledge_base_id=knowledge_base_id,
                        source_id=source_id,
                        vector=[1.0, 0.0, 0.0],
                        text_content="child text",
                    ),
                    parent_id=uuid.uuid4(),
                    parent_text_content="Chapter 1 full section",
                    parent_token_count=120,
                    parent_anchor_page=7,
                    parent_anchor_chapter="Chapter 1",
                    parent_anchor_section="Section A",
                    parent_anchor_timecode=None,
                )
            ]
        )

        response = await service.hybrid_search(
            text="child",
            vector=[1.0, 0.0, 0.0],
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            limit=5,
        )

        assert response[0].parent_text_content == "Chapter 1 full section"
        assert response[0].parent_anchor_metadata == {
            "anchor_page": 7,
            "anchor_chapter": "Chapter 1",
            "anchor_section": "Section A",
            "anchor_timecode": None,
        }
    finally:
        await _cleanup_collection(client, collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_hybrid_search_filters_by_snapshot_id(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = _service(client=client, collection_name=collection_name, embedding_dimensions=3)
    snapshot_id = uuid.uuid4()
    other_snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    matched_chunk_id = uuid.uuid4()

    try:
        await service.ensure_collection()
        await service.upsert_chunks(
            [
                _point(
                    chunk_id=matched_chunk_id,
                    snapshot_id=snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[0.4, 0.9, 0.0],
                    text_content="deployment guide",
                ),
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=other_snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[1.0, 0.0, 0.0],
                    text_content="deployment guide",
                ),
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=other_snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[1.0, 0.0, 0.0],
                    text_content="deployment guide",
                ),
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=other_snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[1.0, 0.0, 0.0],
                    text_content="deployment guide",
                ),
            ]
        )

        response = await service.hybrid_search(
            text="deployment",
            vector=[1.0, 0.0, 0.0],
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            limit=1,
        )

        assert [chunk.chunk_id for chunk in response] == [matched_chunk_id]
    finally:
        await _cleanup_collection(client, collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_hybrid_search_keyword_boost(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = _service(client=client, collection_name=collection_name, embedding_dimensions=3)
    snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    semantic_chunk_id = uuid.uuid4()
    keyword_chunk_id = uuid.uuid4()

    try:
        await service.ensure_collection()
        await service.upsert_chunks(
            [
                _point(
                    chunk_id=semantic_chunk_id,
                    snapshot_id=snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[1.0, 0.0, 0.0],
                    text_content="general platform architecture",
                ),
                _point(
                    chunk_id=keyword_chunk_id,
                    snapshot_id=snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[0.4, 0.9, 0.0],
                    text_content="deployment guide",
                ),
            ]
        )

        dense_response = await service.dense_search(
            vector=[1.0, 0.0, 0.0],
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            limit=2,
        )
        hybrid_response = await service.hybrid_search(
            text="deployment",
            vector=[1.0, 0.0, 0.0],
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            limit=2,
        )

        assert [chunk.chunk_id for chunk in dense_response] == [
            semantic_chunk_id,
            keyword_chunk_id,
        ]
        assert [chunk.chunk_id for chunk in hybrid_response] == [
            keyword_chunk_id,
            semantic_chunk_id,
        ]
    finally:
        await _cleanup_collection(client, collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_hybrid_search_sparse_only_results(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = _service(client=client, collection_name=collection_name, embedding_dimensions=3)
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
                    vector=[0.0, 1.0, 0.0],
                    text_content="deployment guide",
                )
            ]
        )

        response = await service.hybrid_search(
            text="deployment",
            vector=[1.0, 0.0, 0.0],
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            limit=5,
            score_threshold=0.95,
        )

        assert [chunk.chunk_id for chunk in response] == [chunk_id]
    finally:
        await _cleanup_collection(client, collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_hybrid_search_dense_only_results(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = _service(client=client, collection_name=collection_name, embedding_dimensions=3)
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
                    text_content="general platform architecture",
                )
            ]
        )

        response = await service.hybrid_search(
            text="deployment",
            vector=[1.0, 0.0, 0.0],
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
async def test_qdrant_hybrid_search_dedup_same_chunk_both_legs(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = _service(client=client, collection_name=collection_name, embedding_dimensions=3)
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
                    text_content="deployment guide",
                ),
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[0.0, 1.0, 0.0],
                    text_content="operations handbook",
                ),
            ]
        )

        response = await service.hybrid_search(
            text="deployment",
            vector=[1.0, 0.0, 0.0],
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            limit=5,
        )

        chunk_ids = [chunk.chunk_id for chunk in response]
        assert chunk_ids.count(chunk_id) == 1
    finally:
        await _cleanup_collection(client, collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_dimension_mismatch_raises(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service_3072 = _service(client=client, collection_name=collection_name, embedding_dimensions=3072)
    service_1024 = _service(client=client, collection_name=collection_name, embedding_dimensions=1024)

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
    service = _service(client=client, collection_name=collection_name, embedding_dimensions=3)

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
    service = _service(client=client, collection_name=collection_name, embedding_dimensions=3)
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
    service = _service(client=client, collection_name=collection_name, embedding_dimensions=3)
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
    service = _service(client=client, collection_name=collection_name, embedding_dimensions=3)

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


@pytest.mark.asyncio
async def test_qdrant_keyword_search_supports_bge_sparse_provider(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = _bge_service(client=client, collection_name=collection_name, embedding_dimensions=3)
    snapshot_id = uuid.uuid4()
    other_snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    matched_chunk_id = uuid.uuid4()

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
                ),
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=other_snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[1.0, 0.0, 0.0],
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

        assert [chunk.chunk_id for chunk in response] == [matched_chunk_id]
        assert service.sparse_backend == "bge_m3"
        assert service.sparse_model == "bge-m3"
    finally:
        await _cleanup_collection(client, collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_switch_from_bm25_to_bge_requires_explicit_reindex(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    bm25_service = _service(client=client, collection_name=collection_name, embedding_dimensions=3)
    bge_service = _bge_service(client=client, collection_name=collection_name, embedding_dimensions=3)

    try:
        await bm25_service.ensure_collection()
        await bm25_service.upsert_chunks(
            [
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=uuid.uuid4(),
                    agent_id=uuid.uuid4(),
                    knowledge_base_id=uuid.uuid4(),
                    vector=[1.0, 0.0, 0.0],
                    text_content="deployment guide",
                )
            ]
        )

        with pytest.raises(CollectionSchemaMismatchError, match="Explicit reindex is required"):
            await bge_service.ensure_collection()
    finally:
        await _cleanup_collection(client, collection_name)
        await client.close()
