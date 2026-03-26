from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BackgroundTask, Chunk, Document, DocumentVersion, Source
from app.db.models.enums import (
    ChunkStatus,
    DocumentStatus,
    DocumentVersionStatus,
    ProcessingPath,
    SourceStatus,
)

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from app.core.config import Settings
    from app.services.batch_orchestrator import BatchOrchestrator
    from app.services.document_ai_parser import DocumentAIParser
    from app.services.document_processing import ChunkData
    from app.services.document_processing import DocumentProcessor
    from app.services.embedding import EmbeddingService
    from app.services.gemini_content import GeminiContentService
    from app.services.qdrant import QdrantService
    from app.services.snapshot import SnapshotService
    from app.services.storage import StorageService
    from app.services.token_counter import ApproximateTokenizer

from app.services.qdrant import QdrantChunkPoint


@dataclass(slots=True)
class PipelineServices:
    storage_service: StorageService
    document_processor: DocumentProcessor
    document_ai_parser: DocumentAIParser | None
    embedding_service: EmbeddingService
    qdrant_service: QdrantService
    snapshot_service: SnapshotService
    gemini_content_service: GeminiContentService
    tokenizer: ApproximateTokenizer
    settings: Settings
    default_language: str
    path_a_text_threshold_pdf: int
    path_a_text_threshold_media: int
    path_a_max_pdf_pages: int
    path_a_max_audio_duration_sec: int
    path_a_max_video_duration_sec: int
    path_c_min_chars_per_page: int
    document_ai_enabled: bool
    batch_orchestrator: BatchOrchestrator | None = None

    @property
    def has_document_ai(self) -> bool:
        return self.document_ai_enabled and self.document_ai_parser is not None


@dataclass(slots=True)
class PersistedPipelineState:
    snapshot_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_ids: list[uuid.UUID]
    token_count_total: int


@dataclass(slots=True, frozen=True)
class SkipEmbeddingResult:
    snapshot_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_ids: list[uuid.UUID]
    chunk_count: int
    token_count_total: int
    processing_path: ProcessingPath
    pipeline_version: str


@dataclass(slots=True, frozen=True)
class BatchSubmittedResult:
    snapshot_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_ids: list[uuid.UUID]
    chunk_count: int
    token_count_total: int
    processing_path: ProcessingPath
    pipeline_version: str


@dataclass(slots=True, frozen=True)
class InitializedPipelineRecords:
    snapshot_id: uuid.UUID
    document: Document
    document_version: DocumentVersion


class TextChunkPipelineError(RuntimeError):
    def __init__(
        self,
        *,
        persisted_state: PersistedPipelineState,
        qdrant_write_may_have_happened: bool,
        cause: Exception,
    ) -> None:
        super().__init__(str(cause))
        self.persisted_state = persisted_state
        self.qdrant_write_may_have_happened = qdrant_write_may_have_happened
        self.cause = cause


async def initialize_pipeline_records(
    session: AsyncSession,
    *,
    source: Source,
    snapshot_service: SnapshotService,
    processing_path: ProcessingPath,
    processing_hint: str,
) -> InitializedPipelineRecords:
    snapshot = await snapshot_service.get_or_create_draft(
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
        processing_path=processing_path,
        processing_hint=processing_hint,
        status=DocumentVersionStatus.PROCESSING,
    )
    session.add_all([document, document_version])

    snapshot = await snapshot_service.ensure_draft_or_rebind(
        session,
        snapshot_id=snapshot.id,
        agent_id=source.agent_id,
        knowledge_base_id=source.knowledge_base_id,
    )
    return InitializedPipelineRecords(
        snapshot_id=snapshot.id,
        document=document,
        document_version=document_version,
    )


async def cleanup_qdrant_chunks(
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


async def embed_and_index_chunks(
    session: AsyncSession,
    *,
    task: BackgroundTask,
    source: Source,
    services: PipelineServices,
    chunk_data: list[ChunkData],
    chunk_rows: list[Chunk],
    snapshot_id: uuid.UUID,
    document_id: uuid.UUID,
    document_version_id: uuid.UUID,
    processing_path: ProcessingPath,
    pipeline_version: str,
    page_count: int | None = None,
    duration_seconds: float | None = None,
) -> SkipEmbeddingResult | BatchSubmittedResult | PersistedPipelineState:
    persisted_state = PersistedPipelineState(
        snapshot_id=snapshot_id,
        document_id=document_id,
        document_version_id=document_version_id,
        chunk_ids=[chunk.id for chunk in chunk_rows],
        token_count_total=sum(chunk.token_count for chunk in chunk_data),
    )

    task.progress = 50
    await session.commit()

    qdrant_write_may_have_happened = False

    try:
        skip_embedding = bool((task.result_metadata or {}).get("skip_embedding"))
        if skip_embedding:
            return SkipEmbeddingResult(
                snapshot_id=snapshot_id,
                document_id=document_id,
                document_version_id=document_version_id,
                chunk_ids=persisted_state.chunk_ids,
                chunk_count=len(chunk_rows),
                token_count_total=persisted_state.token_count_total,
                processing_path=processing_path,
                pipeline_version=pipeline_version,
            )

        if (
            services.batch_orchestrator is not None
            and len(chunk_rows) > services.settings.batch_embed_chunk_threshold
        ):
            await services.batch_orchestrator.create_batch_job_for_threshold(
                session,
                task=task,
                source=source,
                snapshot_id=snapshot_id,
                chunk_ids=persisted_state.chunk_ids,
                document_id=document_id,
                document_version_id=document_version_id,
                chunk_count=len(chunk_rows),
                token_count_total=persisted_state.token_count_total,
                processing_path=processing_path.value,
                pipeline_version=pipeline_version,
            )
            await services.batch_orchestrator.submit_to_gemini(
                session,
                background_task_id=task.id,
                texts=[chunk.text_content for chunk in chunk_rows],
                chunk_ids=persisted_state.chunk_ids,
                display_name=source.title,
            )
            task.progress = 60
            await session.commit()
            return BatchSubmittedResult(
                snapshot_id=snapshot_id,
                document_id=document_id,
                document_version_id=document_version_id,
                chunk_ids=persisted_state.chunk_ids,
                chunk_count=len(chunk_rows),
                token_count_total=persisted_state.token_count_total,
                processing_path=processing_path,
                pipeline_version=pipeline_version,
            )

        vectors = await services.embedding_service.embed_texts(
            [chunk.text_content for chunk in chunk_data],
            task_type=getattr(
                services.settings,
                "embedding_task_type",
                "RETRIEVAL_DOCUMENT",
            ),
            title=source.title,
        )
        task.progress = 85
        await session.commit()

        qdrant_points = [
            QdrantChunkPoint(
                chunk_id=row.id,
                vector=vector,
                snapshot_id=snapshot_id,
                source_id=source.id,
                document_version_id=document_version_id,
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
                page_count=page_count,
                duration_seconds=duration_seconds,
            )
            for row, vector in zip(chunk_rows, vectors, strict=True)
        ]
        qdrant_write_may_have_happened = True
        await services.qdrant_service.upsert_chunks(qdrant_points)
        task.progress = 95
        await session.commit()
        return persisted_state
    except Exception as error:
        raise TextChunkPipelineError(
            persisted_state=persisted_state,
            qdrant_write_may_have_happened=qdrant_write_may_have_happened,
            cause=error,
        ) from error


async def mark_persisted_records_failed(
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

    if source is not None and source.status is not SourceStatus.DELETED:
        source.status = SourceStatus.FAILED
    if document is not None:
        document.status = DocumentStatus.FAILED
    if document_version is not None:
        document_version.status = DocumentVersionStatus.FAILED

    if chunk_ids:
        await session.execute(
            update(Chunk).where(Chunk.id.in_(chunk_ids)).values(status=ChunkStatus.FAILED)
        )
    await session.commit()
