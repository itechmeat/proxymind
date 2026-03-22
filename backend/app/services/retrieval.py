from __future__ import annotations

import uuid

import structlog

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.services.embedding import EmbeddingService
from app.services.qdrant import QdrantService, RetrievedChunk


class RetrievalError(RuntimeError):
    pass


class RetrievalService:
    def __init__(
        self,
        *,
        embedding_service: EmbeddingService,
        qdrant_service: QdrantService,
        top_n: int,
        min_dense_similarity: float | None,
        agent_id: uuid.UUID = DEFAULT_AGENT_ID,
        knowledge_base_id: uuid.UUID = DEFAULT_KNOWLEDGE_BASE_ID,
    ) -> None:
        self._embedding_service = embedding_service
        self._qdrant_service = qdrant_service
        self._top_n = top_n
        self._min_dense_similarity = min_dense_similarity
        self._agent_id = agent_id
        self._knowledge_base_id = knowledge_base_id
        self._logger = structlog.get_logger(__name__)

    async def search(
        self,
        query: str,
        *,
        snapshot_id: uuid.UUID,
        top_n: int | None = None,
    ) -> list[RetrievedChunk]:
        try:
            embeddings = await self._embedding_service.embed_texts(
                [query],
                task_type="RETRIEVAL_QUERY",
            )
            if not embeddings:
                return []
            return await self._qdrant_service.hybrid_search(
                text=query,
                vector=embeddings[0],
                snapshot_id=snapshot_id,
                agent_id=self._agent_id,
                knowledge_base_id=self._knowledge_base_id,
                limit=self._top_n if top_n is None else top_n,
                score_threshold=self._min_dense_similarity,
            )
        except Exception as error:
            self._logger.error(
                "retrieval.search_failed",
                snapshot_id=str(snapshot_id),
                error=str(error),
            )
            raise RetrievalError("Retrieval failed") from error
