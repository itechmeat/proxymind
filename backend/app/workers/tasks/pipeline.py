from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk, Document, DocumentVersion, Source
from app.db.models.enums import (
    ChunkStatus,
    DocumentStatus,
    DocumentVersionStatus,
    ProcessingPath,
    SourceStatus,
)

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer

    from app.core.config import Settings
    from app.services.batch_orchestrator import BatchOrchestrator
    from app.services.docling_parser import DoclingParser
    from app.services.embedding import EmbeddingService
    from app.services.gemini_content import GeminiContentService
    from app.services.qdrant import QdrantService
    from app.services.snapshot import SnapshotService
    from app.services.storage import StorageService


@dataclass(slots=True)
class PipelineServices:
    storage_service: StorageService
    docling_parser: DoclingParser
    embedding_service: EmbeddingService
    qdrant_service: QdrantService
    snapshot_service: SnapshotService
    gemini_content_service: GeminiContentService
    tokenizer: HuggingFaceTokenizer
    settings: Settings
    default_language: str
    path_a_text_threshold_pdf: int
    path_a_text_threshold_media: int
    path_a_max_pdf_pages: int
    path_a_max_audio_duration_sec: int
    path_a_max_video_duration_sec: int
    batch_orchestrator: BatchOrchestrator | None = None


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


async def initialize_pipeline_records(
    session: AsyncSession,
    *,
    source: Source,
    snapshot_service: SnapshotService,
    processing_path: ProcessingPath,
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
