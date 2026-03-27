import uuid
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_AGENT_ID
from app.db.session import get_session
from app.persona.loader import PersonaContext
from app.services.chat import ChatService
from app.services.catalog import CatalogService
from app.services.context_assembler import ContextAssembler
from app.services.conversation_memory import ConversationMemoryService
from app.services.embedding import EmbeddingService
from app.services.llm import LLMService
from app.services.promotions import PromotionsService
from app.services.qdrant import QdrantService
from app.services.query_rewrite import QueryRewriteService
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


def get_catalog_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogService:
    return CatalogService(session=session)


def get_snapshot_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SnapshotService:
    from app.services.snapshot import SnapshotService

    return SnapshotService(session=session)


def get_llm_service(request: Request) -> LLMService:
    return request.app.state.llm_service


def get_query_rewrite_service(request: Request) -> QueryRewriteService:
    return request.app.state.query_rewrite_service


def get_retrieval_service(request: Request) -> RetrievalService:
    return request.app.state.retrieval_service


def get_persona_context(request: Request) -> PersonaContext:
    return request.app.state.persona_context


def get_promotions_service(request: Request) -> PromotionsService:
    return request.app.state.promotions_service


def get_conversation_memory_service(request: Request) -> ConversationMemoryService | None:
    return getattr(request.app.state, "conversation_memory_service", None)


async def get_context_assembler(
    request: Request,
    persona_context: Annotated[PersonaContext, Depends(get_persona_context)],
    promotions_service: Annotated[PromotionsService, Depends(get_promotions_service)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
) -> ContextAssembler:
    settings = request.app.state.settings
    active_catalog_items = await catalog_service.get_active_items(agent_id=DEFAULT_AGENT_ID)
    return ContextAssembler(
        persona_context=persona_context,
        promotions_service=promotions_service,
        catalog_items=list(CatalogService.build_sku_map(active_catalog_items).values()),
        retrieval_context_budget=settings.retrieval_context_budget,
        max_citations=settings.max_citations_per_response,
        min_retrieved_chunks=settings.min_retrieved_chunks,
        max_promotions_per_response=settings.max_promotions_per_response,
    )


def get_sse_settings(request: Request) -> dict[str, int]:
    settings = request.app.state.settings
    return {
        "heartbeat_interval": settings.sse_heartbeat_interval_seconds,
        "inter_token_timeout": settings.sse_inter_token_timeout_seconds,
    }


def get_chat_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    retrieval_service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
    query_rewrite_service: Annotated[QueryRewriteService, Depends(get_query_rewrite_service)],
    context_assembler: Annotated[ContextAssembler, Depends(get_context_assembler)],
    conversation_memory_service: Annotated[
        ConversationMemoryService | None, Depends(get_conversation_memory_service)
    ],
) -> ChatService:
    from app.services.chat import ChatService

    arq_pool = request.app.state.arq_pool

    async def summary_enqueuer(
        session_id: str,
        window_start_message_id: str | None,
    ) -> None:
        await arq_pool.enqueue_job(
            "generate_session_summary",
            session_id,
            window_start_message_id,
            _job_id=f"summary:{session_id}",
        )

    return ChatService(
        session=session,
        snapshot_service=snapshot_service,
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        query_rewrite_service=query_rewrite_service,
        context_assembler=context_assembler,
        min_retrieved_chunks=request.app.state.settings.min_retrieved_chunks,
        max_citations_per_response=request.app.state.settings.max_citations_per_response,
        conversation_memory_service=conversation_memory_service,
        summary_enqueuer=summary_enqueuer,
    )
