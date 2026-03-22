from contextlib import asynccontextmanager

import httpx
import structlog
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from minio import Minio
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis

from app.api.admin import router as admin_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import create_database_engine, create_session_factory
from app.services import (
    EmbeddingService,
    LLMService,
    QdrantService,
    RetrievalService,
    StorageService,
)


async def _close_app_resources(app: FastAPI, logger: structlog.stdlib.BoundLogger) -> None:
    resources = (
        ("arq_pool", "close", "app.shutdown.arq_pool_close_failed"),
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
        db_engine = create_database_engine(settings)
        app.state.settings = settings
        app.state.db_engine = db_engine
        app.state.session_factory = create_session_factory(db_engine)
        app.state.redis_client = Redis.from_url(settings.redis_url)
        app.state.http_client = httpx.AsyncClient(timeout=5.0)
        app.state.embedding_service = EmbeddingService(
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            batch_size=settings.embedding_batch_size,
            api_key=settings.gemini_api_key,
        )
        app.state.qdrant_service = QdrantService(
            client=AsyncQdrantClient(url=settings.qdrant_url),
            collection_name=settings.qdrant_collection,
            embedding_dimensions=settings.embedding_dimensions,
        )
        await app.state.qdrant_service.ensure_collection()
        app.state.retrieval_service = RetrievalService(
            embedding_service=app.state.embedding_service,
            qdrant_service=app.state.qdrant_service,
            top_n=settings.retrieval_top_n,
            min_dense_similarity=settings.min_dense_similarity,
        )
        app.state.llm_service = LLMService(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            api_base=settings.llm_api_base,
            temperature=settings.llm_temperature,
        )
        app.state.storage_service = StorageService(
            Minio(
                endpoint=f"{settings.minio_host}:{settings.minio_port}",
                access_key=settings.minio_root_user,
                secret_key=settings.minio_root_password,
                secure=False,
            ),
            settings.minio_bucket_sources,
        )
        await app.state.storage_service.ensure_bucket()
        app.state.arq_pool = await create_pool(
            RedisSettings(host=settings.redis_host, port=settings.redis_port)
        )
    except Exception as error:
        logger.error("app.startup_failed", error=str(error))
        await _close_app_resources(app, logger)
        raise

    logger.info("app.startup", log_level=settings.log_level)
    try:
        yield
    finally:
        await _close_app_resources(app, logger)
        logger.info("app.shutdown")


app = FastAPI(title="ProxyMind API", version="0.1.0", lifespan=lifespan)
app.include_router(admin_router)
app.include_router(chat_router)
app.include_router(health_router)
