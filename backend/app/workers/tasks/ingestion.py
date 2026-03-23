from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import (
    BackgroundTask,
    Chunk,
    Document,
    DocumentVersion,
    EmbeddingProfile,
    KnowledgeSnapshot,
    Source,
)
from app.db.models.enums import (
    BackgroundTaskStatus,
    ChunkStatus,
    DocumentStatus,
    DocumentVersionStatus,
    ProcessingPath,
    SourceStatus,
    TaskType,
)
from app.services.path_router import determine_path, inspect_file
from app.workers.tasks.pipeline import (
    BatchSubmittedResult,
    PipelineServices,
    SkipEmbeddingResult,
    cleanup_qdrant_chunks,
    mark_persisted_records_failed,
)

logger = structlog.get_logger(__name__)


def _load_pipeline_services(ctx: dict[str, Any]) -> PipelineServices:
    try:
        storage_service = ctx["storage_service"]
        docling_parser = ctx["docling_parser"]
        embedding_service = ctx["embedding_service"]
        qdrant_service = ctx["qdrant_service"]
        snapshot_service = ctx["snapshot_service"]
        gemini_content_service = ctx["gemini_content_service"]
        tokenizer = ctx["tokenizer"]
        settings = ctx["settings"]
        path_a_text_threshold_pdf = ctx["path_a_text_threshold_pdf"]
        path_a_text_threshold_media = ctx["path_a_text_threshold_media"]
        path_a_max_pdf_pages = ctx["path_a_max_pdf_pages"]
        path_a_max_audio_duration_sec = ctx["path_a_max_audio_duration_sec"]
        path_a_max_video_duration_sec = ctx["path_a_max_video_duration_sec"]
        batch_orchestrator = ctx.get("batch_orchestrator")
    except KeyError as error:
        raise RuntimeError(
            f"Worker context is missing required pipeline service: {error.args[0]}"
        ) from error

    if not hasattr(storage_service, "download"):
        raise RuntimeError("Worker context contains an invalid storage service")
    if not hasattr(docling_parser, "parse_and_chunk"):
        raise RuntimeError("Worker context contains an invalid Docling parser")
    if not hasattr(embedding_service, "embed_texts") or not hasattr(
        embedding_service, "embed_file"
    ):
        raise RuntimeError("Worker context contains an invalid embedding service")
    if not hasattr(qdrant_service, "upsert_chunks") or not hasattr(qdrant_service, "delete_chunks"):
        raise RuntimeError("Worker context contains an invalid Qdrant service")
    if not hasattr(snapshot_service, "get_or_create_draft") or not hasattr(
        snapshot_service, "ensure_draft_or_rebind"
    ):
        raise RuntimeError("Worker context contains an invalid snapshot service")
    if not hasattr(gemini_content_service, "extract_text_content"):
        raise RuntimeError("Worker context contains an invalid Gemini content service")
    if not hasattr(tokenizer, "count_tokens"):
        raise RuntimeError("Worker context contains an invalid tokenizer")
    if not hasattr(settings, "bm25_language"):
        raise RuntimeError("Worker context contains invalid settings for ingestion")

    return PipelineServices(
        storage_service=storage_service,
        docling_parser=docling_parser,
        embedding_service=embedding_service,
        qdrant_service=qdrant_service,
        snapshot_service=snapshot_service,
        gemini_content_service=gemini_content_service,
        tokenizer=tokenizer,
        settings=settings,
        default_language=settings.bm25_language,
        path_a_text_threshold_pdf=path_a_text_threshold_pdf,
        path_a_text_threshold_media=path_a_text_threshold_media,
        path_a_max_pdf_pages=path_a_max_pdf_pages,
        path_a_max_audio_duration_sec=path_a_max_audio_duration_sec,
        path_a_max_video_duration_sec=path_a_max_video_duration_sec,
        batch_orchestrator=batch_orchestrator,
    )


async def process_ingestion(ctx: dict[str, Any], task_id: str) -> None:
    session_factory = ctx["session_factory"]
    if not isinstance(session_factory, async_sessionmaker):
        raise RuntimeError("Worker context is missing a valid session factory")

    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        logger.warning("worker.ingestion.invalid_task_id", task_id=task_id)
        return

    async with session_factory() as session:
        await _process_task(ctx, session, task_uuid)


async def _process_task(
    ctx: dict[str, Any],
    session: AsyncSession,
    task_id: uuid.UUID,
) -> None:
    task = await session.get(BackgroundTask, task_id)
    if task is None:
        logger.warning("worker.ingestion.task_missing", task_id=str(task_id))
        return

    if task.status is not BackgroundTaskStatus.PENDING:
        logger.warning(
            "worker.ingestion.task_skipped",
            task_id=str(task_id),
            status=task.status.value,
        )
        return

    source = await session.get(Source, task.source_id) if task.source_id else None
    if source is not None and source.status is SourceStatus.DELETED:
        task.status = BackgroundTaskStatus.FAILED
        task.progress = 0
        task.started_at = datetime.now(UTC)
        task.completed_at = datetime.now(UTC)
        task.error_message = "Source was deleted before processing completed"
        await session.commit()
        logger.warning(
            "worker.ingestion.source_deleted", task_id=str(task_id), source_id=str(source.id)
        )
        return

    services = _load_pipeline_services(ctx)

    try:
        task.status = BackgroundTaskStatus.PROCESSING
        task.progress = 0
        task.started_at = datetime.now(UTC)
        if source is not None:
            source.status = SourceStatus.PROCESSING
        await session.commit()

        result = await _run_ingestion_pipeline(session, task, source, services)
        if result is None:
            return
        if isinstance(result, BatchSubmittedResult):
            return

        if isinstance(result, SkipEmbeddingResult):
            await _finalize_skip_embedding(
                session=session,
                task=task,
                source=source,
                result=result,
            )
            return

        try:
            await _finalize_pipeline_success(
                session=session,
                task=task,
                source=source,
                snapshot_id=result.snapshot_id,
                document_id=result.document_id,
                document_version_id=result.document_version_id,
                chunk_ids=result.chunk_ids,
                chunk_count=result.chunk_count,
                token_count_total=result.token_count_total,
                processing_path=result.processing_path,
                pipeline_version=result.pipeline_version,
                embedding_service=services.embedding_service,
            )
        except Exception:
            await session.rollback()
            await cleanup_qdrant_chunks(services.qdrant_service, result.chunk_ids)
            await mark_persisted_records_failed(
                session,
                source_id=source.id,
                document_id=result.document_id,
                document_version_id=result.document_version_id,
                chunk_ids=result.chunk_ids,
            )
            raise
    except Exception as error:
        await session.rollback()
        failed_task = await session.get(BackgroundTask, task_id)
        if failed_task is None:
            logger.error("worker.ingestion.fail_fast_task_missing", task_id=str(task_id))
            return

        failed_task.status = BackgroundTaskStatus.FAILED
        failed_task.error_message = str(error) or type(error).__name__
        failed_task.completed_at = datetime.now(UTC)
        if failed_task.source_id is not None:
            failed_source = await session.get(Source, failed_task.source_id)
            if failed_source is not None:
                failed_source.status = SourceStatus.FAILED

        # TODO(ops-backlog): Add stale PROCESSING task detection and recovery for worker crashes.
        # This is an operational concern outside the current story sequence.
        # See docs/architecture.md § Operational circuit for context.
        await session.commit()
        logger.exception("worker.ingestion.failed", task_id=str(task_id))


async def _run_ingestion_pipeline(
    session: AsyncSession,
    task: BackgroundTask,
    source: Source | None,
    services: PipelineServices,
) -> object | None:
    if source is None:
        raise RuntimeError("Ingestion task is missing a source")

    file_bytes = await services.storage_service.download(source.file_path)
    task.progress = 10
    await session.commit()

    file_metadata = inspect_file(file_bytes, source.source_type)
    path_decision = determine_path(source.source_type, file_metadata, services)
    task.progress = 20
    await session.commit()

    if path_decision.rejected:
        source.status = SourceStatus.FAILED
        task.status = BackgroundTaskStatus.FAILED
        task.error_message = path_decision.reason
        task.completed_at = datetime.now(UTC)
        await session.commit()
        return

    from app.workers.tasks.handlers.path_a import PathAFallback, handle_path_a
    from app.workers.tasks.handlers.path_b import handle_path_b

    if path_decision.path is ProcessingPath.PATH_A:
        result = await handle_path_a(
            session,
            task,
            source,
            file_bytes,
            file_metadata,
            services,
        )
        if isinstance(result, PathAFallback):
            result = await handle_path_b(session, task, source, file_bytes, services)
    else:
        result = await handle_path_b(session, task, source, file_bytes, services)

    return result


async def _finalize_skip_embedding(
    *,
    session: AsyncSession,
    task: BackgroundTask,
    source: Source,
    result: SkipEmbeddingResult,
) -> None:
    source.status = SourceStatus.READY

    document = await session.get(Document, result.document_id)
    document_version = await session.get(DocumentVersion, result.document_version_id)
    if document is None or document_version is None:
        raise RuntimeError("Persisted document records could not be loaded for skip finalization")

    document.status = DocumentStatus.READY
    document_version.status = DocumentVersionStatus.READY
    task.status = BackgroundTaskStatus.COMPLETE
    task.progress = 100
    task.completed_at = datetime.now(UTC)
    task.result_metadata = {
        "chunk_count": result.chunk_count,
        "processing_path": result.processing_path.value,
        "snapshot_id": str(result.snapshot_id),
        "document_id": str(result.document_id),
        "document_version_id": str(result.document_version_id),
        "token_count_total": result.token_count_total,
        "skip_embedding": True,
    }
    await session.commit()


async def _apply_pipeline_success_state(
    *,
    session: AsyncSession,
    source: Source,
    snapshot_id: uuid.UUID,
    document_id: uuid.UUID,
    document_version_id: uuid.UUID,
    chunk_ids: list[uuid.UUID],
    chunk_count: int,
    pipeline_version: str,
    embedding_model: str,
    embedding_dimensions: int,
) -> None:
    source.status = SourceStatus.READY

    document = await session.get(Document, document_id)
    document_version = await session.get(DocumentVersion, document_version_id)
    if document is None or document_version is None:
        raise RuntimeError("Persisted document records could not be loaded for finalization")

    document.status = DocumentStatus.READY
    document_version.status = DocumentVersionStatus.READY

    chunk_result = await session.scalars(
        select(Chunk).where(Chunk.id.in_(chunk_ids)).order_by(Chunk.chunk_index.asc())
    )
    for chunk in chunk_result:
        chunk.status = ChunkStatus.INDEXED

    embedding_profile = EmbeddingProfile(
        id=uuid.uuid7(),
        model_name=embedding_model,
        dimensions=embedding_dimensions,
        task_type=TaskType.RETRIEVAL,
        pipeline_version=pipeline_version,
        knowledge_base_id=source.knowledge_base_id,
        snapshot_id=snapshot_id,
    )
    session.add(embedding_profile)

    snapshot_update = await session.execute(
        update(KnowledgeSnapshot)
        .where(KnowledgeSnapshot.id == snapshot_id)
        .values(chunk_count=KnowledgeSnapshot.chunk_count + chunk_count)
    )
    if snapshot_update.rowcount != 1:
        raise RuntimeError("Persisted draft snapshot could not be updated during finalization")


async def _finalize_pipeline_success(
    *,
    session: AsyncSession,
    task: BackgroundTask,
    source: Source,
    snapshot_id: uuid.UUID,
    document_id: uuid.UUID,
    document_version_id: uuid.UUID,
    chunk_ids: list[uuid.UUID],
    chunk_count: int,
    token_count_total: int,
    processing_path: ProcessingPath,
    pipeline_version: str,
    embedding_service,
) -> None:
    await _apply_pipeline_success_state(
        session=session,
        source=source,
        snapshot_id=snapshot_id,
        document_id=document_id,
        document_version_id=document_version_id,
        chunk_ids=chunk_ids,
        chunk_count=chunk_count,
        pipeline_version=pipeline_version,
        embedding_model=embedding_service.model,
        embedding_dimensions=embedding_service.dimensions,
    )

    task.status = BackgroundTaskStatus.COMPLETE
    task.progress = 100
    task.completed_at = datetime.now(UTC)
    task.result_metadata = {
        "chunk_count": chunk_count,
        "embedding_model": embedding_service.model,
        "embedding_dimensions": embedding_service.dimensions,
        "processing_path": processing_path.value,
        "snapshot_id": str(snapshot_id),
        "document_id": str(document_id),
        "document_version_id": str(document_version_id),
        "token_count_total": token_count_total,
    }
    await session.commit()
