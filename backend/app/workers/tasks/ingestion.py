from __future__ import annotations

import uuid
from dataclasses import dataclass
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
from app.services import (
    DoclingParser,
    EmbeddingService,
    QdrantChunkPoint,
    QdrantService,
    SnapshotService,
    StorageService,
)

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class PipelineServices:
    storage_service: StorageService
    docling_parser: DoclingParser
    embedding_service: EmbeddingService
    qdrant_service: QdrantService
    snapshot_service: SnapshotService
    default_language: str


@dataclass(slots=True)
class PersistedPipelineState:
    snapshot_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_ids: list[uuid.UUID]
    token_count_total: int


def _load_pipeline_services(ctx: dict[str, Any]) -> PipelineServices:
    try:
        storage_service = ctx["storage_service"]
        docling_parser = ctx["docling_parser"]
        embedding_service = ctx["embedding_service"]
        qdrant_service = ctx["qdrant_service"]
        snapshot_service = ctx["snapshot_service"]
        settings = ctx["settings"]
    except KeyError as error:
        raise RuntimeError(
            f"Worker context is missing required pipeline service: {error.args[0]}"
        ) from error

    if not hasattr(storage_service, "download"):
        raise RuntimeError("Worker context contains an invalid storage service")
    if not hasattr(docling_parser, "parse_and_chunk"):
        raise RuntimeError("Worker context contains an invalid Docling parser")
    if not hasattr(embedding_service, "embed_texts"):
        raise RuntimeError("Worker context contains an invalid embedding service")
    if not hasattr(qdrant_service, "upsert_chunks") or not hasattr(qdrant_service, "delete_chunks"):
        raise RuntimeError("Worker context contains an invalid Qdrant service")
    if not hasattr(snapshot_service, "get_or_create_draft") or not hasattr(
        snapshot_service, "ensure_draft_or_rebind"
    ):
        raise RuntimeError("Worker context contains an invalid snapshot service")
    if not hasattr(settings, "bm25_language"):
        raise RuntimeError("Worker context contains invalid settings for ingestion")

    return PipelineServices(
        storage_service=storage_service,
        docling_parser=docling_parser,
        embedding_service=embedding_service,
        qdrant_service=qdrant_service,
        snapshot_service=snapshot_service,
        default_language=settings.bm25_language,
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
    services = _load_pipeline_services(ctx)

    try:
        task.status = BackgroundTaskStatus.PROCESSING
        task.progress = 0
        task.started_at = datetime.now(UTC)
        if source is not None:
            source.status = SourceStatus.PROCESSING
        await session.commit()

        await _run_ingestion_pipeline(session, task, source, services)
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

        # TODO(S7-04): Add stale PROCESSING task detection and recovery for worker crashes.
        await session.commit()
        logger.exception("worker.ingestion.failed", task_id=str(task_id))


async def _run_ingestion_pipeline(
    session: AsyncSession,
    task: BackgroundTask,
    source: Source | None,
    services: PipelineServices,
) -> None:
    if source is None:
        raise RuntimeError("Ingestion task is missing a source")

    persisted_state: PersistedPipelineState | None = None
    qdrant_write_may_have_happened = False

    try:
        file_bytes = await services.storage_service.download(source.file_path)
        task.progress = 10
        await session.commit()

        chunk_data = await services.docling_parser.parse_and_chunk(
            file_bytes,
            _source_filename(source),
            source.source_type,
        )
        if not chunk_data:
            raise ValueError("Parsed document produced no chunks")
        task.progress = 40
        await session.commit()

        snapshot = await services.snapshot_service.get_or_create_draft(
            session,
            agent_id=source.agent_id,
            knowledge_base_id=source.knowledge_base_id,
        )
        document = Document(
            id=uuid.uuid7(),
            owner_id=source.owner_id,
            agent_id=source.agent_id,
            source_id=source.id,
            title=source.title,
            status=DocumentStatus.PROCESSING,
        )
        document_version = DocumentVersion(
            id=uuid.uuid7(),
            document_id=document.id,
            version_number=1,
            file_path=source.file_path,
            processing_path=ProcessingPath.PATH_B,
            status=DocumentVersionStatus.PROCESSING,
        )
        session.add_all([document, document_version])

        snapshot = await services.snapshot_service.ensure_draft_or_rebind(
            session,
            snapshot_id=snapshot.id,
            agent_id=source.agent_id,
            knowledge_base_id=source.knowledge_base_id,
        )

        chunk_rows = [
            Chunk(
                id=uuid.uuid7(),
                owner_id=source.owner_id,
                agent_id=source.agent_id,
                knowledge_base_id=source.knowledge_base_id,
                document_version_id=document_version.id,
                snapshot_id=snapshot.id,
                source_id=source.id,
                chunk_index=chunk.chunk_index,
                text_content=chunk.text_content,
                token_count=chunk.token_count,
                anchor_page=chunk.anchor_page,
                anchor_chapter=chunk.anchor_chapter,
                anchor_section=chunk.anchor_section,
                anchor_timecode=chunk.anchor_timecode,
                status=ChunkStatus.PENDING,
            )
            for chunk in chunk_data
        ]
        session.add_all(chunk_rows)
        task.progress = 50
        await session.commit()

        persisted_state = PersistedPipelineState(
            snapshot_id=snapshot.id,
            document_id=document.id,
            document_version_id=document_version.id,
            chunk_ids=[chunk.id for chunk in chunk_rows],
            token_count_total=sum(chunk.token_count for chunk in chunk_data),
        )

        vectors = await services.embedding_service.embed_texts(
            [chunk.text_content for chunk in chunk_data],
            task_type="RETRIEVAL_DOCUMENT",
            title=source.title,
        )
        task.progress = 85
        await session.commit()

        qdrant_points = [
            QdrantChunkPoint(
                chunk_id=row.id,
                vector=vector,
                snapshot_id=snapshot.id,
                source_id=source.id,
                document_version_id=document_version.id,
                agent_id=source.agent_id,
                knowledge_base_id=source.knowledge_base_id,
                text_content=row.text_content,
                chunk_index=row.chunk_index,
                token_count=row.token_count,
                anchor_page=row.anchor_page,
                anchor_chapter=row.anchor_chapter,
                anchor_section=row.anchor_section,
                anchor_timecode=row.anchor_timecode,
                source_type=source.source_type,
                language=source.language or services.default_language,
                status=ChunkStatus.INDEXED,
            )
            for row, vector in zip(chunk_rows, vectors, strict=True)
        ]
        qdrant_write_may_have_happened = True
        await services.qdrant_service.upsert_chunks(qdrant_points)
        task.progress = 95
        await session.commit()

        await _finalize_pipeline_success(
            session=session,
            task=task,
            source=source,
            snapshot_id=snapshot.id,
            document_id=document.id,
            document_version_id=document_version.id,
            chunk_ids=[chunk.id for chunk in chunk_rows],
            chunk_count=len(chunk_rows),
            token_count_total=persisted_state.token_count_total,
            embedding_service=services.embedding_service,
        )
    except Exception:
        await session.rollback()
        if qdrant_write_may_have_happened and persisted_state is not None:
            await _cleanup_qdrant_chunks(services.qdrant_service, persisted_state.chunk_ids)
        if persisted_state is not None:
            await _mark_persisted_records_failed(
                session,
                source_id=source.id,
                document_id=persisted_state.document_id,
                document_version_id=persisted_state.document_version_id,
                chunk_ids=persisted_state.chunk_ids,
            )
        raise


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
    embedding_service: EmbeddingService,
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
        model_name=embedding_service.model,
        dimensions=embedding_service.dimensions,
        task_type=TaskType.RETRIEVAL,
        pipeline_version="s2-02-path-b",
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

    task.status = BackgroundTaskStatus.COMPLETE
    task.progress = 100
    task.completed_at = datetime.now(UTC)
    task.result_metadata = {
        "chunk_count": chunk_count,
        "embedding_model": embedding_service.model,
        "embedding_dimensions": embedding_service.dimensions,
        "processing_path": ProcessingPath.PATH_B.value,
        "snapshot_id": str(snapshot_id),
        "document_id": str(document_id),
        "document_version_id": str(document_version_id),
        "token_count_total": token_count_total,
    }
    await session.commit()


async def _cleanup_qdrant_chunks(
    qdrant_service: QdrantService,
    chunk_ids: list[uuid.UUID],
) -> None:
    try:
        await qdrant_service.delete_chunks(chunk_ids)
    except Exception:
        logger.exception(
            "worker.ingestion.qdrant_cleanup_failed",
            chunk_ids=[str(chunk_id) for chunk_id in chunk_ids],
        )


async def _mark_persisted_records_failed(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    document_id: uuid.UUID,
    document_version_id: uuid.UUID,
    chunk_ids: list[uuid.UUID],
) -> None:
    source = await session.get(Source, source_id)
    document = await session.get(Document, document_id)
    document_version = await session.get(DocumentVersion, document_version_id)

    if source is not None:
        source.status = SourceStatus.FAILED
    if document is not None:
        document.status = DocumentStatus.FAILED
    if document_version is not None:
        document_version.status = DocumentVersionStatus.FAILED

    await session.execute(
        update(Chunk).where(Chunk.id.in_(chunk_ids)).values(status=ChunkStatus.FAILED)
    )
    await session.commit()


def _source_filename(source: Source) -> str:
    return source.file_path.rsplit("/", maxsplit=1)[-1]
