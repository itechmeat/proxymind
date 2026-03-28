from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import structlog
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis

from app.api.admin import router as admin_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.metrics import router as metrics_router
from app.api.profile import admin_router as profile_admin_router
from app.api.profile import chat_router as profile_chat_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import create_database_engine, create_session_factory
from app.middleware.observability import ObservabilityMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.persona import PersonaLoader
from app.services.telemetry import (
    init_telemetry,
    instrument_fastapi,
    instrument_sqlalchemy,
    shutdown_telemetry,
)


def _create_embedding_service(settings):
    from app.services.embedding import EmbeddingService

    return EmbeddingService(
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.embedding_batch_size,
        api_key=settings.gemini_api_key,
        use_vertexai=settings.google_genai_use_vertexai,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
    )


def _create_qdrant_service(settings):
    from app.services.qdrant import QdrantService

    return QdrantService(
        client=AsyncQdrantClient(url=settings.qdrant_url),
        collection_name=settings.qdrant_collection,
        embedding_dimensions=settings.embedding_dimensions,
        bm25_language=settings.bm25_language,
    )


def _create_retrieval_service(settings, embedding_service, qdrant_service):
    from app.services.retrieval import RetrievalService

    return RetrievalService(
        embedding_service=embedding_service,
        qdrant_service=qdrant_service,
        top_n=settings.retrieval_top_n,
        min_dense_similarity=settings.min_dense_similarity,
    )


def _create_llm_service(settings):
    from app.services.llm import LLMService

    return LLMService(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        api_base=settings.llm_api_base,
        temperature=settings.llm_temperature,
    )


def _create_query_rewrite_service(settings, llm_service):
    from app.services.query_rewrite import QueryRewriteService

    if settings.rewrite_llm_model is not None:
        from app.services.llm import LLMService

        rewrite_llm_service = LLMService(
            model=settings.rewrite_llm_model,
            api_key=settings.rewrite_llm_api_key or settings.llm_api_key,
            api_base=settings.rewrite_llm_api_base or settings.llm_api_base,
            temperature=settings.rewrite_temperature,
        )
    else:
        rewrite_llm_service = llm_service

    return QueryRewriteService(
        llm_service=rewrite_llm_service,
        rewrite_enabled=settings.rewrite_enabled,
        timeout_ms=settings.rewrite_timeout_ms,
        token_budget=settings.rewrite_token_budget,
        history_messages=settings.rewrite_history_messages,
        temperature=settings.rewrite_temperature,
    )


def _create_promotions_service(settings):
    from app.services.promotions import PromotionsService

    return PromotionsService.from_file(Path(settings.promotions_file_path))


def _create_conversation_memory_service(settings):
    from app.services.conversation_memory import ConversationMemoryService

    return ConversationMemoryService(
        budget=settings.conversation_memory_budget,
        summary_ratio=settings.conversation_summary_ratio,
    )


def _create_storage_service(settings, storage_http_client):
    from app.services.storage import StorageService

    return StorageService(
        storage_http_client,
        settings.seaweedfs_sources_path,
    )


async def _close_app_resources(app: FastAPI, logger: structlog.stdlib.BoundLogger) -> None:
    resources = (
        ("arq_pool", "close", "app.shutdown.arq_pool_close_failed"),
        ("storage_http_client", "aclose", "app.shutdown.storage_http_client_close_failed"),
        ("http_client", "aclose", "app.shutdown.http_client_close_failed"),
        ("qdrant_service", "close", "app.shutdown.qdrant_close_failed"),
        ("redis_client", "aclose", "app.shutdown.redis_client_close_failed"),
        ("db_engine", "dispose", "app.shutdown.db_engine_dispose_failed"),
    )
    for attribute, close_method, event_name in resources:
        resource = getattr(app.state, attribute, None)
        if resource is None:
            continue
        try:
            await getattr(resource, close_method)()
        except Exception as error:
            logger.error(event_name, error=str(error))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger = structlog.get_logger(__name__)
    configure_logging(settings.log_level)
    try:
        init_telemetry(settings)
        instrument_fastapi(app)
        db_engine = create_database_engine(settings)
        instrument_sqlalchemy(db_engine)
        app.state.settings = settings
        app.state.db_engine = db_engine
        app.state.session_factory = create_session_factory(db_engine)
        app.state.redis_client = Redis.from_url(settings.redis_url)
        app.state.http_client = httpx.AsyncClient(timeout=5.0)
        app.state.storage_http_client = httpx.AsyncClient(
            base_url=settings.seaweedfs_filer_url,
            timeout=30.0,
        )
        app.state.embedding_service = _create_embedding_service(settings)
        app.state.qdrant_service = _create_qdrant_service(settings)
        await app.state.qdrant_service.ensure_collection()
        app.state.retrieval_service = _create_retrieval_service(
            settings,
            app.state.embedding_service,
            app.state.qdrant_service,
        )
        app.state.llm_service = _create_llm_service(settings)
        app.state.query_rewrite_service = _create_query_rewrite_service(
            settings,
            app.state.llm_service,
        )
        app.state.storage_service = _create_storage_service(
            settings,
            app.state.storage_http_client,
        )
        await app.state.storage_service.ensure_storage_root()
        app.state.arq_pool = await create_pool(
            RedisSettings(host=settings.redis_host, port=settings.redis_port)
        )
        persona_loader = PersonaLoader(
            persona_dir=Path(settings.persona_dir),
            config_dir=Path(settings.config_dir),
        )
        app.state.persona_context = persona_loader.load()
        app.state.promotions_service = _create_promotions_service(settings)
        app.state.conversation_memory_service = _create_conversation_memory_service(settings)
    except Exception as error:
        logger.error("app.startup_failed", error=str(error))
        await _close_app_resources(app, logger)
        shutdown_telemetry()
        raise

    logger.info("app.startup", log_level=settings.log_level)
    try:
        yield
    finally:
        await _close_app_resources(app, logger)
        logger.info("app.shutdown")
        shutdown_telemetry()


app = FastAPI(title="ProxyMind API", version="0.1.0", lifespan=lifespan)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ObservabilityMiddleware)
app.include_router(admin_router)
app.include_router(profile_admin_router)
app.include_router(chat_router)
app.include_router(profile_chat_router)
app.include_router(health_router)
app.include_router(metrics_router)
