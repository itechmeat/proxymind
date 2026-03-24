from __future__ import annotations

from typing import Any

import httpx
import structlog
from arq import cron
from arq.connections import RedisSettings
from qdrant_client import AsyncQdrantClient

from app.core.config import get_settings
from app.db import create_database_engine, create_session_factory
from app.workers.tasks import poll_active_batches, process_batch_embed, process_ingestion

settings = get_settings()
logger = structlog.get_logger(__name__)
DEFAULT_EMBEDDING_TASK_TYPE = "RETRIEVAL_DOCUMENT"


async def on_startup(ctx: dict[str, Any]) -> None:
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer

    from app.services.batch_embedding import BatchEmbeddingClient
    from app.services.batch_orchestrator import BatchOrchestrator
    from app.services.docling_parser import DoclingParser
    from app.services.embedding import EmbeddingService
    from app.services.gemini_content import GeminiContentService
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
        bm25_language=settings.bm25_language,
    )
    embedding_service = EmbeddingService(
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.embedding_batch_size,
        api_key=settings.gemini_api_key,
        file_upload_threshold_bytes=settings.gemini_file_upload_threshold_bytes,
    )
    gemini_content_service = GeminiContentService(
        model=settings.gemini_content_model,
        upload_threshold_bytes=settings.gemini_file_upload_threshold_bytes,
        api_key=settings.gemini_api_key,
    )
    batch_embedding_client = BatchEmbeddingClient(
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
        embedding_task_type=getattr(
            settings,
            "embedding_task_type",
            DEFAULT_EMBEDDING_TASK_TYPE,
        ),
        api_key=settings.gemini_api_key,
    )
    batch_orchestrator = BatchOrchestrator(
        batch_client=batch_embedding_client,
        qdrant_service=qdrant_service,
    )
    tokenizer = HuggingFaceTokenizer.from_pretrained(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        max_tokens=settings.chunk_max_tokens,
    )
    ctx["db_engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    ctx["settings"] = settings
    ctx["storage_http_client"] = storage_http_client
    ctx["storage_service"] = storage_service
    ctx["docling_parser"] = DoclingParser(chunk_max_tokens=settings.chunk_max_tokens)
    ctx["embedding_service"] = embedding_service
    ctx["gemini_content_service"] = gemini_content_service
    ctx["batch_embedding_client"] = batch_embedding_client
    ctx["batch_orchestrator"] = batch_orchestrator
    ctx["tokenizer"] = tokenizer
    ctx["qdrant_service"] = qdrant_service
    ctx["snapshot_service"] = SnapshotService()
    ctx["path_a_text_threshold_pdf"] = settings.path_a_text_threshold_pdf
    ctx["path_a_text_threshold_media"] = settings.path_a_text_threshold_media
    ctx["path_a_max_pdf_pages"] = settings.path_a_max_pdf_pages
    ctx["path_a_max_audio_duration_sec"] = settings.path_a_max_audio_duration_sec
    ctx["path_a_max_video_duration_sec"] = settings.path_a_max_video_duration_sec
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
    functions = [process_ingestion, process_batch_embed, poll_active_batches]
    cron_jobs = [
        cron(
            poll_active_batches,
            second=set(range(0, 60, settings.batch_poll_interval_seconds)),
        )
    ]
    redis_settings = RedisSettings(host=settings.redis_host, port=settings.redis_port)
    max_jobs = 10
    job_timeout = 600
    retry_jobs = False
    on_startup = on_startup
    on_shutdown = on_shutdown
