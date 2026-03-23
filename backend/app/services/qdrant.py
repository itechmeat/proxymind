from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
import structlog
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
DENSE_VECTOR_NAME = "dense"
BM25_VECTOR_NAME = "bm25"
BM25_MODEL_NAME = "Qdrant/bm25"
PREFETCH_MULTIPLIER = 2
RRF_K = 60


class CollectionSchemaMismatchError(RuntimeError):
    pass


class InvalidRetrievedChunkError(RuntimeError):
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
    page_count: int | None = None
    duration_seconds: float | None = None


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
        bm25_language: str,
    ) -> None:
        self._client = client
        self._collection_name = collection_name
        self._embedding_dimensions = embedding_dimensions
        self._bm25_language = bm25_language
        self._logger = structlog.get_logger(__name__)

    @property
    def bm25_language(self) -> str:
        return self._bm25_language

    async def ensure_collection(self) -> None:
        self._logger.info(
            "qdrant.ensure_collection",
            collection_name=self._collection_name,
            bm25_language=self._bm25_language,
        )
        collection_info: Any | None = None
        if await self._client.collection_exists(self._collection_name):
            collection_info = await self._client.get_collection(self._collection_name)
        else:
            try:
                await self._create_collection()
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
            if not self._has_required_bm25_sparse_vector(collection_info):
                self._logger.warning(
                    "qdrant.collection_bm25_schema_mismatch_recreating",
                    collection_name=self._collection_name,
                    bm25_language=self._bm25_language,
                    message=(
                        "Qdrant collection is missing the required BM25 sparse vector "
                        "configuration and "
                        "will be recreated. Existing vectors will be lost."
                        " Re-ingestion is required."
                    ),
                )
                await self._recreate_collection_with_bm25()

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
                vector={
                    DENSE_VECTOR_NAME: chunk.vector,
                    BM25_VECTOR_NAME: self._build_bm25_document(chunk.text_content),
                },
                payload=self._build_payload(chunk),
            )
            for chunk in chunks
        ]
        await self._upsert_points(points)

    async def delete_chunks(self, chunk_ids: list[UUID]) -> None:
        if not chunk_ids:
            return

        await self._delete_points([str(chunk_id) for chunk_id in chunk_ids])

    async def dense_search(
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
            "using": DENSE_VECTOR_NAME,
            "query_filter": self._build_scope_filter(
                snapshot_id=snapshot_id,
                agent_id=agent_id,
                knowledge_base_id=knowledge_base_id,
            ),
            "limit": limit,
            "with_payload": True,
        }
        if score_threshold is not None:
            search_kwargs["score_threshold"] = score_threshold

        response = await self._search_points(**search_kwargs)
        return [self._to_retrieved_chunk(point) for point in response.points]

    async def hybrid_search(
        self,
        *,
        text: str,
        vector: list[float],
        snapshot_id: UUID,
        agent_id: UUID,
        knowledge_base_id: UUID,
        limit: int,
        score_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        if limit <= 0:
            return []

        scope_filter = self._build_scope_filter(
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
        )
        dense_prefetch_kwargs: dict[str, Any] = {
            "query": vector,
            "using": DENSE_VECTOR_NAME,
            "filter": scope_filter,
            "limit": limit * PREFETCH_MULTIPLIER,
        }
        if score_threshold is not None:
            dense_prefetch_kwargs["score_threshold"] = score_threshold

        response = await self._search_points(
            collection_name=self._collection_name,
            prefetch=[
                models.Prefetch(**dense_prefetch_kwargs),
                models.Prefetch(
                    query=self._build_bm25_document(text),
                    using=BM25_VECTOR_NAME,
                    filter=scope_filter,
                    limit=limit * PREFETCH_MULTIPLIER,
                ),
            ],
            query=models.RrfQuery(rrf=models.Rrf(k=RRF_K)),
            query_filter=scope_filter,
            limit=limit,
            with_payload=True,
        )
        return [self._to_retrieved_chunk(point) for point in response.points]

    async def keyword_search(
        self,
        *,
        text: str,
        snapshot_id: UUID,
        agent_id: UUID,
        knowledge_base_id: UUID,
        limit: int = 10,
    ) -> list[RetrievedChunk]:
        response = await self._search_points(
            collection_name=self._collection_name,
            query=self._build_bm25_document(text),
            using=BM25_VECTOR_NAME,
            query_filter=self._build_scope_filter(
                snapshot_id=snapshot_id,
                agent_id=agent_id,
                knowledge_base_id=knowledge_base_id,
            ),
            limit=limit,
            with_payload=True,
        )
        return [self._to_retrieved_chunk(point) for point in response.points]

    async def close(self) -> None:
        await self._client.close()

    @staticmethod
    def _build_payload(chunk: QdrantChunkPoint) -> dict[str, Any]:
        payload: dict[str, Any] = {
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
        }
        if chunk.page_count is not None:
            payload["page_count"] = chunk.page_count
        if chunk.duration_seconds is not None:
            payload["duration_seconds"] = chunk.duration_seconds
        return payload

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

    async def _create_collection(self) -> None:
        await self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config={
                DENSE_VECTOR_NAME: models.VectorParams(
                    size=self._embedding_dimensions,
                    distance=models.Distance.COSINE,
                )
            },
            sparse_vectors_config={
                BM25_VECTOR_NAME: models.SparseVectorParams(modifier=models.Modifier.IDF)
            },
        )

    async def _recreate_collection_with_bm25(self) -> None:
        for _attempt in range(3):
            if await self._client.collection_exists(self._collection_name):
                collection_info = await self._client.get_collection(self._collection_name)
                if self._has_required_bm25_sparse_vector(collection_info):
                    return
                try:
                    await self._client.delete_collection(self._collection_name)
                except UnexpectedResponse as error:
                    if not self._is_collection_missing(error):
                        raise

            try:
                await self._create_collection()
            except UnexpectedResponse as error:
                if not self._is_collection_exists_conflict(error):
                    raise

            if await self._client.collection_exists(self._collection_name):
                collection_info = await self._client.get_collection(self._collection_name)
                if self._has_required_bm25_sparse_vector(collection_info):
                    return

        raise CollectionSchemaMismatchError(
            "Qdrant collection recreation did not converge to the required BM25 schema."
        )

    def _build_bm25_document(self, text: str) -> models.Document:
        return models.Document(
            text=text,
            model=BM25_MODEL_NAME,
            options=models.Bm25Config(language=self._bm25_language),
        )

    @staticmethod
    def _build_scope_filter(
        *,
        snapshot_id: UUID,
        agent_id: UUID,
        knowledge_base_id: UUID,
    ) -> models.Filter:
        return models.Filter(
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
        )

    @staticmethod
    def _to_retrieved_chunk(point: Any) -> RetrievedChunk:
        payload = point.payload or {}
        raw_chunk_id = payload.get("chunk_id")
        raw_source_id = payload.get("source_id")
        raw_text_content = payload.get("text_content")
        raw_score = getattr(point, "score", None)
        missing_fields = [
            field_name
            for field_name, value in (
                ("chunk_id", raw_chunk_id),
                ("source_id", raw_source_id),
                ("text_content", raw_text_content),
                ("score", raw_score),
            )
            if value is None
        ]
        if missing_fields:
            raise InvalidRetrievedChunkError(
                "Qdrant point is missing retrieval fields: " + ", ".join(missing_fields)
            )

        try:
            chunk_id = UUID(str(raw_chunk_id))
            source_id = UUID(str(raw_source_id))
            score = float(raw_score)
        except (TypeError, ValueError) as error:
            raise InvalidRetrievedChunkError(
                "Qdrant point contains invalid retrieval metadata"
            ) from error

        return RetrievedChunk(
            chunk_id=chunk_id,
            source_id=source_id,
            text_content=str(raw_text_content),
            score=score,
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
    def _is_collection_missing(error: UnexpectedResponse) -> bool:
        return error.status_code == 404

    @staticmethod
    def _get_dense_vector_size(collection_info: Any) -> int:
        vectors_config = collection_info.config.params.vectors
        if isinstance(vectors_config, Mapping):
            dense_config = vectors_config.get(DENSE_VECTOR_NAME)
            if dense_config is None:
                raise CollectionSchemaMismatchError(
                    f"Qdrant collection is missing the required named vector '{DENSE_VECTOR_NAME}'."
                )
            return dense_config.size

        raise CollectionSchemaMismatchError(
            "Qdrant collection uses an anonymous vector configuration; "
            f"named vector '{DENSE_VECTOR_NAME}' is required for reindex compatibility."
        )

    @staticmethod
    def _has_required_bm25_sparse_vector(collection_info: Any) -> bool:
        sparse_vectors_config = getattr(collection_info.config.params, "sparse_vectors", None)
        if sparse_vectors_config is None:
            return False

        bm25_config: Any = None
        if isinstance(sparse_vectors_config, Mapping):
            bm25_config = sparse_vectors_config.get(BM25_VECTOR_NAME)
        elif hasattr(sparse_vectors_config, "get"):
            bm25_config = sparse_vectors_config.get(BM25_VECTOR_NAME)
        else:
            bm25_config = getattr(sparse_vectors_config, BM25_VECTOR_NAME, None)

        if bm25_config is None:
            return False

        if isinstance(bm25_config, Mapping):
            modifier = bm25_config.get("modifier")
        else:
            modifier = getattr(bm25_config, "modifier", None)
        return getattr(modifier, "value", modifier) == getattr(
            models.Modifier.IDF, "value", models.Modifier.IDF
        )
