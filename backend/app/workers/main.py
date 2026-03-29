from __future__ import annotations

from typing import Any

import httpx
import structlog
from arq import cron
from arq.connections import RedisSettings
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import create_database_engine, create_session_factory
from app.services.telemetry import init_telemetry, instrument_sqlalchemy, shutdown_telemetry
from app.workers.observability import probe_queue_depth, update_queue_depth
from app.workers.tasks import (
    generate_session_summary,
    poll_active_batches,
    process_batch_embed,
    process_ingestion,
)

settings = get_settings()
logger = structlog.get_logger(__name__)
DEFAULT_EMBEDDING_TASK_TYPE = "RETRIEVAL_DOCUMENT"


async def on_startup(ctx: dict[str, Any]) -> None:
    from app.services.batch_embedding import BatchEmbeddingClient
    from app.services.batch_orchestrator import BatchOrchestrator
    from app.services.document_ai_parser import DocumentAIParser
    from app.services.embedding import EmbeddingService
    from app.services.enrichment import EnrichmentService
    from app.services.gemini_content import GeminiContentService
    from app.services.lightweight_parser import LightweightParser
    from app.services.llm import LLMService
    from app.services.qdrant import QdrantService
    from app.services.snapshot import SnapshotService
    from app.services.storage import StorageService
    from app.services.token_counter import ApproximateTokenizer

    configure_logging(settings.log_level)
    logger.info("worker.startup.begin")
    init_telemetry(settings, service_name="proxymind-worker")
    engine = create_database_engine(settings)
    instrument_sqlalchemy(engine)
    storage_http_client = httpx.AsyncClient(
        base_url=settings.seaweedfs_filer_url,
        timeout=30.0,
    )
    worker_redis_client = Redis.from_url(settings.redis_url)
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
        use_vertexai=settings.google_genai_use_vertexai,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        file_upload_threshold_bytes=settings.gemini_file_upload_threshold_bytes,
    )
    gemini_content_service = GeminiContentService(
        model=settings.gemini_content_model,
        upload_threshold_bytes=settings.gemini_file_upload_threshold_bytes,
        api_key=settings.gemini_api_key,
        use_vertexai=settings.google_genai_use_vertexai,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
    )
    enrichment_service = (
        EnrichmentService(
            model=settings.enrichment_model,
            temperature=settings.enrichment_temperature,
            max_output_tokens=settings.enrichment_max_output_tokens,
            min_chunk_tokens=settings.enrichment_min_chunk_tokens,
            max_concurrency=settings.enrichment_max_concurrency,
            api_key=settings.gemini_api_key,
            use_vertexai=settings.google_genai_use_vertexai,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
        )
        if settings.enrichment_enabled
        else None
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
        use_vertexai=settings.google_genai_use_vertexai,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
    )
    batch_orchestrator = BatchOrchestrator(
        batch_client=batch_embedding_client,
        qdrant_service=qdrant_service,
    )
    summary_llm_service = LLMService(
        model=settings.conversation_summary_model or settings.llm_model,
        api_key=settings.llm_api_key,
        api_base=settings.llm_api_base,
        temperature=settings.conversation_summary_temperature,
    )
    tokenizer = ApproximateTokenizer()
    document_ai_parser = (
        DocumentAIParser(
            project_id=settings.document_ai_project_id,
            location=settings.document_ai_location,
            processor_id=settings.document_ai_processor_id,
            chunk_max_tokens=settings.chunk_max_tokens,
        )
        if settings.document_ai_enabled
        else None
    )
    session_factory = create_session_factory(engine)
    ctx["db_engine"] = engine
    ctx["db_session_factory"] = session_factory
    ctx["session_factory"] = session_factory
    ctx["settings"] = settings
    ctx["worker_redis_client"] = worker_redis_client
    ctx["storage_http_client"] = storage_http_client
    ctx["storage_service"] = storage_service
    ctx["document_processor"] = LightweightParser(chunk_max_tokens=settings.chunk_max_tokens)
    ctx["document_ai_parser"] = document_ai_parser
    ctx["embedding_service"] = embedding_service
    ctx["gemini_content_service"] = gemini_content_service
    ctx["enrichment_service"] = enrichment_service
    ctx["batch_embedding_client"] = batch_embedding_client
    ctx["batch_orchestrator"] = batch_orchestrator
    ctx["summary_llm_service"] = summary_llm_service
    ctx["tokenizer"] = tokenizer
    ctx["qdrant_service"] = qdrant_service
    ctx["snapshot_service"] = SnapshotService()
    ctx["path_a_text_threshold_pdf"] = settings.path_a_text_threshold_pdf
    ctx["path_a_text_threshold_media"] = settings.path_a_text_threshold_media
    ctx["path_a_max_pdf_pages"] = settings.path_a_max_pdf_pages
    ctx["path_a_max_audio_duration_sec"] = settings.path_a_max_audio_duration_sec
    ctx["path_a_max_video_duration_sec"] = settings.path_a_max_video_duration_sec
    ctx["path_c_min_chars_per_page"] = settings.path_c_min_chars_per_page
    await qdrant_service.ensure_collection()
    await storage_service.ensure_storage_root()
    await update_queue_depth(worker_redis_client)
    logger.info("worker.startup.complete")


async def on_shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("db_engine")
    qdrant_service = ctx.get("qdrant_service")
    storage_http_client = ctx.get("storage_http_client")
    worker_redis_client = ctx.get("worker_redis_client")
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
    if worker_redis_client is not None:
        try:
            await worker_redis_client.aclose()
        except Exception:
            logger.exception("worker.shutdown.redis_client_close_failed")
    if engine is None:
        try:
            shutdown_telemetry()
        except Exception:
            logger.exception("worker.shutdown.telemetry_failed")
        logger.info("worker.shutdown.complete", disposed=False)
        return

    try:
        shutdown_telemetry()
    except Exception:
        logger.exception("worker.shutdown.telemetry_failed")
    try:
        await engine.dispose()
    except Exception:
        logger.exception("worker.shutdown.failed")
        raise

    logger.info("worker.shutdown.complete", disposed=True)


class WorkerSettings:
    functions = [
        process_ingestion,
        process_batch_embed,
        poll_active_batches,
        generate_session_summary,
        probe_queue_depth,
    ]
    cron_jobs = [
        cron(
            probe_queue_depth,
            second={0, 30},
        ),
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
