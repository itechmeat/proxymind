from __future__ import annotations

from typing import Any

import httpx
import structlog
from arq.connections import RedisSettings
from qdrant_client import AsyncQdrantClient

from app.core.config import get_settings
from app.db import create_database_engine, create_session_factory
from app.workers.tasks import process_ingestion

settings = get_settings()
logger = structlog.get_logger(__name__)


async def on_startup(ctx: dict[str, Any]) -> None:
    from app.services.docling_parser import DoclingParser
    from app.services.embedding import EmbeddingService
    from app.services.qdrant import QdrantService
    from app.services.snapshot import SnapshotService
    from app.services.storage import StorageService

    logger.info("worker.startup.begin")
    engine = create_database_engine(settings)
    storage_http_client = httpx.AsyncClient(
        base_url=settings.seaweedfs_filer_url,
        timeout=30.0,
    )
    storage_service = StorageService(
        storage_http_client,
        settings.seaweedfs_sources_path,
    )
    qdrant_service = QdrantService(
        client=AsyncQdrantClient(url=settings.qdrant_url),
        collection_name=settings.qdrant_collection,
        embedding_dimensions=settings.embedding_dimensions,
    )
    embedding_service = EmbeddingService(
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.embedding_batch_size,
        api_key=settings.gemini_api_key,
    )
    ctx["db_engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    ctx["settings"] = settings
    ctx["storage_http_client"] = storage_http_client
    ctx["storage_service"] = storage_service
    ctx["docling_parser"] = DoclingParser(chunk_max_tokens=settings.chunk_max_tokens)
    ctx["embedding_service"] = embedding_service
    ctx["qdrant_service"] = qdrant_service
    ctx["snapshot_service"] = SnapshotService()
    await qdrant_service.ensure_collection()
    await storage_service.ensure_storage_root()
    logger.info("worker.startup.complete")


async def on_shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("db_engine")
    qdrant_service = ctx.get("qdrant_service")
    storage_http_client = ctx.get("storage_http_client")
    logger.info("worker.shutdown.begin", has_engine=engine is not None)
    if qdrant_service is not None:
        try:
            await qdrant_service.close()
        except Exception:
            logger.exception("worker.shutdown.qdrant_close_failed")
    if storage_http_client is not None:
        try:
            await storage_http_client.aclose()
        except Exception:
            logger.exception("worker.shutdown.storage_http_client_close_failed")
    if engine is None:
        logger.info("worker.shutdown.complete", disposed=False)
        return

    try:
        await engine.dispose()
    except Exception:
        logger.exception("worker.shutdown.failed")
        raise

    logger.info("worker.shutdown.complete", disposed=True)


class WorkerSettings:
    functions = [process_ingestion]
    redis_settings = RedisSettings(host=settings.redis_host, port=settings.redis_port)
    max_jobs = 10
    job_timeout = 600
    retry_jobs = False
    on_startup = on_startup
    on_shutdown = on_shutdown
