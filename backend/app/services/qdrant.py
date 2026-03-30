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
from app.services.sparse_providers import (
    SparseProvider,
    SparseProviderMetadata,
    sparse_backend_change_requires_reindex,
)

PAYLOAD_INDEX_FIELDS = (
    "snapshot_id",
    "agent_id",
    "knowledge_base_id",
    "source_id",
    "status",
    "source_type",
    "language",
    "sparse_backend",
    "sparse_model",
    "sparse_contract_version",
)
DENSE_VECTOR_NAME = "dense"
BM25_VECTOR_NAME = "bm25"
BM25_MODEL_NAME = "Qdrant/bm25"
PREFETCH_MULTIPLIER = 2
RRF_K = 60
SPARSE_BACKEND_PAYLOAD_KEY = "sparse_backend"
SPARSE_MODEL_PAYLOAD_KEY = "sparse_model"
SPARSE_CONTRACT_VERSION_PAYLOAD_KEY = "sparse_contract_version"


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
    parent_id: UUID | None = None
    parent_text_content: str | None = None
    parent_token_count: int | None = None
    parent_anchor_page: int | None = None
    parent_anchor_chapter: str | None = None
    parent_anchor_section: str | None = None
    parent_anchor_timecode: str | None = None
    page_count: int | None = None
    duration_seconds: float | None = None
    enriched_summary: str | None = None
    enriched_keywords: list[str] | None = None
    enriched_questions: list[str] | None = None
    enriched_text: str | None = None
    enrichment_model: str | None = None
    enrichment_pipeline_version: str | None = None

    @property
    def bm25_text(self) -> str:
        return self.enriched_text or self.text_content


@dataclass(slots=True, frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    source_id: UUID
    text_content: str
    score: float
    anchor_metadata: dict[str, int | str | None]
    parent_id: UUID | None = None
    parent_text_content: str | None = None
    parent_token_count: int | None = None
    parent_anchor_metadata: dict[str, int | str | None] | None = None


class QdrantService:
    def __init__(
        self,
        *,
        client: AsyncQdrantClient,
        collection_name: str,
        embedding_dimensions: int,
        sparse_provider: SparseProvider,
        bm25_language: str,
    ) -> None:
        self._client = client
        self._collection_name = collection_name
        self._embedding_dimensions = embedding_dimensions
        self._sparse_provider = sparse_provider
        self._bm25_language = bm25_language
        self._logger = structlog.get_logger(__name__)

    @property
    def bm25_language(self) -> str:
        return self._bm25_language

    @property
    def sparse_backend(self) -> str:
        return self._sparse_provider.metadata.backend

    @property
    def sparse_model(self) -> str:
        return self._sparse_provider.metadata.model_name

    @property
    def sparse_contract_version(self) -> str:
        return self._sparse_provider.metadata.contract_version

    async def ensure_collection(self) -> None:
        self._logger.info(
            "qdrant.ensure_collection",
            collection_name=self._collection_name,
            bm25_language=self._bm25_language,
            sparse_backend=self.sparse_backend,
            sparse_model=self.sparse_model,
            sparse_contract_version=self.sparse_contract_version,
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

        if collection_info is None:
            collection_info = await self._client.get_collection(self._collection_name)

        existing_dimensions = self._get_dense_vector_size(collection_info)
        if existing_dimensions != self._embedding_dimensions:
            raise CollectionSchemaMismatchError(
                "Qdrant collection dimension mismatch: "
                f"existing={existing_dimensions}, required={self._embedding_dimensions}. "
                "Delete the collection and re-run ingestion to reindex."
            )
        if not self._has_required_sparse_vector(collection_info):
            if self.sparse_backend == "bm25":
                self._logger.warning(
                    "qdrant.collection_sparse_schema_mismatch_recreating",
                    collection_name=self._collection_name,
                    bm25_language=self._bm25_language,
                    sparse_backend=self.sparse_backend,
                    sparse_model=self.sparse_model,
                    sparse_contract_version=self.sparse_contract_version,
                    message=(
                        "Qdrant collection is missing the required sparse vector configuration "
                        "for the active backend and will be recreated. Existing vectors will be lost. "
                        "Re-ingestion is required."
                    ),
                )
                await self._recreate_collection_with_required_sparse_config()
            else:
                raise CollectionSchemaMismatchError(
                    "Qdrant collection sparse vector configuration does not match the active "
                    f"sparse backend contract '{self.sparse_backend}'. Explicit reindex is required."
                )

        await self._assert_sparse_backend_contract()

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
                    BM25_VECTOR_NAME: await self._build_sparse_document(chunk.bm25_text),
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
                    query=await self._build_sparse_query(text),
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
            query=await self._build_sparse_query(text),
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
        close_errors: list[Exception] = []

        try:
            await self._sparse_provider.aclose()
        except Exception as error:
            close_errors.append(error)

        try:
            await self._client.close()
        except Exception as error:
            close_errors.append(error)

        if close_errors:
            raise ExceptionGroup("Failed to close Qdrant service resources.", close_errors)

    def _build_payload(self, chunk: QdrantChunkPoint) -> dict[str, Any]:
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
            "parent_id": str(chunk.parent_id) if chunk.parent_id is not None else None,
            "parent_text_content": chunk.parent_text_content,
            "parent_token_count": chunk.parent_token_count,
            "parent_anchor_page": chunk.parent_anchor_page,
            "parent_anchor_chapter": chunk.parent_anchor_chapter,
            "parent_anchor_section": chunk.parent_anchor_section,
            "parent_anchor_timecode": chunk.parent_anchor_timecode,
            "source_type": chunk.source_type.value,
            "language": chunk.language,
            "status": chunk.status.value,
            "enriched_summary": chunk.enriched_summary,
            "enriched_keywords": chunk.enriched_keywords,
            "enriched_questions": chunk.enriched_questions,
            "enriched_text": chunk.enriched_text,
            "enrichment_model": chunk.enrichment_model,
            "enrichment_pipeline_version": chunk.enrichment_pipeline_version,
            SPARSE_BACKEND_PAYLOAD_KEY: self.sparse_backend,
            SPARSE_MODEL_PAYLOAD_KEY: self.sparse_model,
            SPARSE_CONTRACT_VERSION_PAYLOAD_KEY: self.sparse_contract_version,
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

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, ResponseHandlingException)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _scroll_points(self, **kwargs: Any) -> Any:
        return await self._client.scroll(**kwargs)

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
                BM25_VECTOR_NAME: self._required_sparse_vector_params()
            },
        )

    async def _recreate_collection_with_required_sparse_config(self) -> None:
        for _attempt in range(3):
            if await self._client.collection_exists(self._collection_name):
                collection_info = await self._client.get_collection(self._collection_name)
                if self._has_required_sparse_vector(collection_info):
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
                if self._has_required_sparse_vector(collection_info):
                    return

        raise CollectionSchemaMismatchError(
            "Qdrant collection recreation did not converge to the required sparse schema."
        )

    async def _build_sparse_document(self, text: str) -> models.Document | models.SparseVector:
        return await self._sparse_provider.build_document_representation(text)

    async def _build_sparse_query(self, text: str) -> models.Document | models.SparseVector:
        return await self._sparse_provider.build_query_representation(text)

    def _required_sparse_vector_params(self) -> models.SparseVectorParams:
        if self.sparse_backend == "bm25":
            return models.SparseVectorParams(modifier=models.Modifier.IDF)
        return models.SparseVectorParams()

    async def _assert_sparse_backend_contract(self) -> None:
        offset: Any | None = None
        legacy_payload_detected = False
        current_metadata: SparseProviderMetadata | None = None

        while True:
            points, offset = await self._scroll_points(
                collection_name=self._collection_name,
                limit=256,
                offset=offset,
                with_payload=[
                    SPARSE_BACKEND_PAYLOAD_KEY,
                    SPARSE_MODEL_PAYLOAD_KEY,
                    SPARSE_CONTRACT_VERSION_PAYLOAD_KEY,
                ],
                with_vectors=False,
            )
            if not points:
                break

            for point in points:
                payload = getattr(point, "payload", None) or {}
                payload_backend = payload.get(SPARSE_BACKEND_PAYLOAD_KEY)
                payload_model = payload.get(SPARSE_MODEL_PAYLOAD_KEY)
                payload_contract_version = payload.get(SPARSE_CONTRACT_VERSION_PAYLOAD_KEY)

                if (
                    payload_backend is None
                    or payload_model is None
                    or payload_contract_version is None
                ):
                    legacy_payload_detected = True
                    continue

                point_metadata = SparseProviderMetadata(
                    backend=str(payload_backend),
                    model_name=str(payload_model),
                    contract_version=str(payload_contract_version),
                )
                if current_metadata is None:
                    current_metadata = point_metadata
                    continue

                if current_metadata != point_metadata:
                    raise CollectionSchemaMismatchError(
                        "Qdrant sparse backend contract mismatch detected across indexed "
                        "payload metadata. Explicit reindex is required. "
                        f"observed={current_metadata.backend}/{current_metadata.model_name}/"
                        f"{current_metadata.contract_version}, "
                        f"conflicting={point_metadata.backend}/{point_metadata.model_name}/"
                        f"{point_metadata.contract_version}."
                    )

            if offset is None:
                break

        if current_metadata is None:
            if legacy_payload_detected and self.sparse_backend == "bm25":
                return
            if legacy_payload_detected:
                raise CollectionSchemaMismatchError(
                    "Qdrant sparse backend compatibility could not be proven from indexed "
                    "payload metadata. Explicit reindex is required before switching "
                    "sparse_backend."
                )
            return

        if legacy_payload_detected:
            raise CollectionSchemaMismatchError(
                "Qdrant sparse backend compatibility could not be proven because indexed "
                "payload metadata is in a mixed legacy/annotated state. Explicit reindex is "
                "required."
            )

        if sparse_backend_change_requires_reindex(current_metadata, self._sparse_provider.metadata):
            raise CollectionSchemaMismatchError(
                "Qdrant sparse backend contract mismatch detected: "
                f"existing={current_metadata.backend}/{current_metadata.model_name}/"
                f"{current_metadata.contract_version}, "
                f"required={self.sparse_backend}/{self.sparse_model}/{self.sparse_contract_version}. "
                "Explicit reindex is required."
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

        raw_parent_id = payload.get("parent_id")
        parent_id: UUID | None = None
        if raw_parent_id is not None:
            try:
                parent_id = UUID(str(raw_parent_id))
            except (TypeError, ValueError) as error:
                raise InvalidRetrievedChunkError(
                    "Qdrant point contains invalid parent retrieval metadata"
                ) from error

        raw_parent_token_count = payload.get("parent_token_count")
        parent_token_count: int | None = None
        if raw_parent_token_count is not None:
            try:
                parent_token_count = int(raw_parent_token_count)
            except (TypeError, ValueError) as error:
                raise InvalidRetrievedChunkError(
                    "Qdrant point contains invalid parent token metadata"
                ) from error

        parent_anchor_metadata = {
            "anchor_page": payload.get("parent_anchor_page"),
            "anchor_chapter": payload.get("parent_anchor_chapter"),
            "anchor_section": payload.get("parent_anchor_section"),
            "anchor_timecode": payload.get("parent_anchor_timecode"),
        }
        has_parent_metadata = parent_id is not None or any(
            value is not None
            for value in (
                payload.get("parent_text_content"),
                parent_token_count,
                *parent_anchor_metadata.values(),
            )
        )

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
            parent_id=parent_id,
            parent_text_content=payload.get("parent_text_content"),
            parent_token_count=parent_token_count,
            parent_anchor_metadata=parent_anchor_metadata if has_parent_metadata else None,
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

    def _has_required_sparse_vector(self, collection_info: Any) -> bool:
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
        if self.sparse_backend == "bm25":
            return getattr(modifier, "value", modifier) == getattr(
                models.Modifier.IDF, "value", models.Modifier.IDF
            )
        return modifier is None
