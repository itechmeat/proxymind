from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.db.models.enums import ChunkStatus, SourceType

PAYLOAD_INDEX_FIELDS = (
    "snapshot_id",
    "agent_id",
    "knowledge_base_id",
    "source_id",
    "status",
    "source_type",
    "language",
)


class CollectionSchemaMismatchError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class QdrantChunkPoint:
    chunk_id: UUID
    vector: list[float]
    snapshot_id: UUID
    source_id: UUID
    document_version_id: UUID
    agent_id: UUID
    knowledge_base_id: UUID
    text_content: str
    chunk_index: int
    token_count: int | None
    anchor_page: int | None
    anchor_chapter: str | None
    anchor_section: str | None
    anchor_timecode: str | None
    source_type: SourceType
    language: str | None
    status: ChunkStatus


@dataclass(slots=True, frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    source_id: UUID
    text_content: str
    score: float
    anchor_metadata: dict[str, int | str | None]


class QdrantService:
    def __init__(
        self,
        *,
        client: AsyncQdrantClient,
        collection_name: str,
        embedding_dimensions: int,
    ) -> None:
        self._client = client
        self._collection_name = collection_name
        self._embedding_dimensions = embedding_dimensions

    async def ensure_collection(self) -> None:
        collection_info: Any | None = None
        if await self._client.collection_exists(self._collection_name):
            collection_info = await self._client.get_collection(self._collection_name)
        else:
            try:
                await self._client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config={
                        "dense": models.VectorParams(
                            size=self._embedding_dimensions,
                            distance=models.Distance.COSINE,
                        )
                    },
                )
            except UnexpectedResponse as error:
                if not self._is_collection_exists_conflict(error):
                    raise
                collection_info = await self._client.get_collection(self._collection_name)

        if collection_info is not None:
            existing_dimensions = self._get_dense_vector_size(collection_info)
            if existing_dimensions != self._embedding_dimensions:
                raise CollectionSchemaMismatchError(
                    "Qdrant collection dimension mismatch: "
                    f"existing={existing_dimensions}, required={self._embedding_dimensions}. "
                    "Delete the collection and re-run ingestion to reindex."
                )

        for field_name in PAYLOAD_INDEX_FIELDS:
            await self._client.create_payload_index(
                collection_name=self._collection_name,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

    async def upsert_chunks(self, chunks: list[QdrantChunkPoint]) -> None:
        if not chunks:
            return

        points = [
            models.PointStruct(
                id=str(chunk.chunk_id),
                vector={"dense": chunk.vector},
                payload={
                    "snapshot_id": str(chunk.snapshot_id),
                    "source_id": str(chunk.source_id),
                    "chunk_id": str(chunk.chunk_id),
                    "document_version_id": str(chunk.document_version_id),
                    "agent_id": str(chunk.agent_id),
                    "knowledge_base_id": str(chunk.knowledge_base_id),
                    "text_content": chunk.text_content,
                    "chunk_index": chunk.chunk_index,
                    "token_count": chunk.token_count,
                    "anchor_page": chunk.anchor_page,
                    "anchor_chapter": chunk.anchor_chapter,
                    "anchor_section": chunk.anchor_section,
                    "anchor_timecode": chunk.anchor_timecode,
                    "source_type": chunk.source_type.value,
                    "language": chunk.language,
                    "status": chunk.status.value,
                },
            )
            for chunk in chunks
        ]
        await self._upsert_points(points)

    async def delete_chunks(self, chunk_ids: list[UUID]) -> None:
        if not chunk_ids:
            return

        await self._delete_points([str(chunk_id) for chunk_id in chunk_ids])

    async def search(
        self,
        *,
        vector: list[float],
        snapshot_id: UUID,
        agent_id: UUID,
        knowledge_base_id: UUID,
        limit: int,
        score_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        search_kwargs: dict[str, Any] = {
            "collection_name": self._collection_name,
            "query": vector,
            "using": "dense",
            "query_filter": models.Filter(
                must=[
                    models.FieldCondition(
                        key="snapshot_id",
                        match=models.MatchValue(value=str(snapshot_id)),
                    ),
                    models.FieldCondition(
                        key="agent_id",
                        match=models.MatchValue(value=str(agent_id)),
                    ),
                    models.FieldCondition(
                        key="knowledge_base_id",
                        match=models.MatchValue(value=str(knowledge_base_id)),
                    ),
                ]
            ),
            "limit": limit,
            "with_payload": True,
        }
        if score_threshold is not None:
            search_kwargs["score_threshold"] = score_threshold

        response = await self._search_points(**search_kwargs)
        return [self._to_retrieved_chunk(point) for point in response.points]

    async def close(self) -> None:
        await self._client.close()

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, ResponseHandlingException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _upsert_points(self, points: list[models.PointStruct]) -> None:
        await self._client.upsert(
            collection_name=self._collection_name,
            points=points,
        )

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, ResponseHandlingException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _delete_points(self, point_ids: list[str]) -> None:
        await self._client.delete(
            collection_name=self._collection_name,
            points_selector=models.PointIdsList(points=point_ids),
            wait=True,
        )

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, ResponseHandlingException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _search_points(self, **kwargs: Any) -> models.QueryResponse:
        return await self._client.query_points(**kwargs)

    @staticmethod
    def _to_retrieved_chunk(point: Any) -> RetrievedChunk:
        payload = point.payload or {}
        return RetrievedChunk(
            chunk_id=UUID(str(payload["chunk_id"])),
            source_id=UUID(str(payload["source_id"])),
            text_content=str(payload["text_content"]),
            score=float(point.score),
            anchor_metadata={
                "anchor_page": payload.get("anchor_page"),
                "anchor_chapter": payload.get("anchor_chapter"),
                "anchor_section": payload.get("anchor_section"),
                "anchor_timecode": payload.get("anchor_timecode"),
            },
        )

    @staticmethod
    def _is_collection_exists_conflict(error: UnexpectedResponse) -> bool:
        return error.status_code == 409

    @staticmethod
    def _get_dense_vector_size(collection_info: Any) -> int:
        vectors_config = collection_info.config.params.vectors
        if isinstance(vectors_config, dict):
            dense_config = vectors_config.get("dense")
            if dense_config is None:
                raise CollectionSchemaMismatchError(
                    "Qdrant collection is missing the required named vector 'dense'."
                )
            return dense_config.size

        raise CollectionSchemaMismatchError(
            "Qdrant collection uses an anonymous vector configuration; "
            "named vector 'dense' is required for reindex compatibility."
        )
