from __future__ import annotations

import uuid
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.persona.loader import PersonaContext
from app.services.chat import ChatService
from app.services.embedding import EmbeddingService
from app.services.llm import LLMService
from app.services.qdrant import QdrantService
from app.services.retrieval import RetrievalService
from app.services.snapshot import SnapshotService
from app.services.source import SourceService, TaskEnqueuer
from app.services.storage import StorageService


def get_storage_service(request: Request) -> StorageService:
    return request.app.state.storage_service


def get_qdrant_service(request: Request) -> QdrantService:
    return request.app.state.qdrant_service


def get_embedding_service(request: Request) -> EmbeddingService:
    return request.app.state.embedding_service


class ArqTaskEnqueuer(TaskEnqueuer):
    def __init__(self, arq_pool: ArqRedis) -> None:
        self._arq_pool = arq_pool

    async def enqueue_ingestion(self, task_id: uuid.UUID) -> str:
        job = await self._arq_pool.enqueue_job("process_ingestion", str(task_id))
        if job is None:
            raise RuntimeError("arq returned no job handle")
        return job.job_id

    async def enqueue_batch_embed(self, task_id: uuid.UUID) -> str:
        job = await self._arq_pool.enqueue_job("process_batch_embed", str(task_id))
        if job is None:
            raise RuntimeError("arq returned no job handle")
        return job.job_id


def get_task_enqueuer(request: Request) -> TaskEnqueuer:
    return ArqTaskEnqueuer(request.app.state.arq_pool)


def get_source_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    task_enqueuer: Annotated[TaskEnqueuer, Depends(get_task_enqueuer)],
) -> SourceService:
    from app.services.source import SourceService

    return SourceService(session=session, task_enqueuer=task_enqueuer)


def get_snapshot_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SnapshotService:
    from app.services.snapshot import SnapshotService

    return SnapshotService(session=session)


def get_llm_service(request: Request) -> LLMService:
    return request.app.state.llm_service


def get_retrieval_service(request: Request) -> RetrievalService:
    return request.app.state.retrieval_service


def get_persona_context(request: Request) -> PersonaContext:
    return request.app.state.persona_context


def get_chat_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    retrieval_service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
    persona_context: Annotated[PersonaContext, Depends(get_persona_context)],
) -> ChatService:
    from app.services.chat import ChatService

    return ChatService(
        session=session,
        snapshot_service=snapshot_service,
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        persona_context=persona_context,
        min_retrieved_chunks=request.app.state.settings.min_retrieved_chunks,
    )
