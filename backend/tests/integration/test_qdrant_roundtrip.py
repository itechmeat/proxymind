from __future__ import annotations

import uuid

import pytest
from qdrant_client import AsyncQdrantClient, models

from app.db.models.enums import ChunkStatus, SourceType
from app.services.qdrant import CollectionSchemaMismatchError, QdrantChunkPoint, QdrantService


def _point(
    *,
    chunk_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    vector: list[float],
    text_content: str,
) -> QdrantChunkPoint:
    return QdrantChunkPoint(
        chunk_id=chunk_id,
        vector=vector,
        snapshot_id=snapshot_id,
        source_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
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


@pytest.mark.asyncio
async def test_qdrant_round_trip_filters_by_snapshot_id(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=3,
    )
    snapshot_id = uuid.uuid4()
    other_snapshot_id = uuid.uuid4()

    try:
        await service.ensure_collection()
        await service.upsert_chunks(
            [
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=snapshot_id,
                    vector=[1.0, 0.0, 0.0],
                    text_content="matched chunk",
                ),
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=other_snapshot_id,
                    vector=[0.0, 1.0, 0.0],
                    text_content="other chunk",
                ),
            ]
        )

        response = await client.query_points(
            collection_name=collection_name,
            query=[1.0, 0.0, 0.0],
            using="dense",
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="snapshot_id",
                        match=models.MatchValue(value=str(snapshot_id)),
                    )
                ]
            ),
            limit=5,
            with_payload=True,
        )

        assert len(response.points) == 1
        assert response.points[0].payload["snapshot_id"] == str(snapshot_id)
        assert response.points[0].payload["text_content"] == "matched chunk"
    finally:
        await client.delete_collection(collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_dimension_mismatch_raises(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service_3072 = QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=3072,
    )
    service_1024 = QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=1024,
    )

    try:
        await service_3072.ensure_collection()
        with pytest.raises(CollectionSchemaMismatchError, match="existing=3072, required=1024"):
            await service_1024.ensure_collection()
    finally:
        await client.delete_collection(collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_qdrant_ensure_collection_is_idempotent(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_chunks_{uuid.uuid4().hex}"
    service = QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=3,
    )

    try:
        await service.ensure_collection()
        await service.ensure_collection()
    finally:
        await client.delete_collection(collection_name)
        await client.close()
