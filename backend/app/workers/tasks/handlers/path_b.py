from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BackgroundTask, Chunk, Source
from app.db.models.enums import ChunkStatus, ProcessingPath
from app.services.document_processing import ChunkData
from app.services.path_router import FileMetadata
from app.workers.tasks.pipeline import (
    BatchSubmittedResult,
    PersistedPipelineState,
    PipelineServices,
    SkipEmbeddingResult,
    TextChunkPipelineError,
    cleanup_qdrant_chunks,
    embed_and_index_chunks,
    initialize_pipeline_records,
    mark_persisted_records_failed,
)

logger = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class PathBResult:
    snapshot_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_ids: list[uuid.UUID]
    chunk_count: int
    token_count_total: int
    processing_path: ProcessingPath
    pipeline_version: str


async def handle_path_b(
    session: AsyncSession,
    task: BackgroundTask,
    source: Source,
    file_bytes: bytes,
    file_metadata: FileMetadata,
    services: PipelineServices,
    processing_hint: str = "auto",
) -> PathBResult | SkipEmbeddingResult | BatchSubmittedResult:
    persisted_state: PersistedPipelineState | None = None

    try:
        chunk_data = await services.document_processor.parse_and_chunk(
            file_bytes,
            source.file_path.rsplit("/", maxsplit=1)[-1],
            source.source_type,
        )

        if _is_suspected_scan(
            chunk_data,
            page_count=file_metadata.page_count,
            min_chars_per_page=services.path_c_min_chars_per_page,
        ):
            if services.has_document_ai:
                from app.workers.tasks.handlers.path_c import handle_path_c

                return await handle_path_c(
                    session,
                    task,
                    source,
                    file_bytes,
                    file_metadata,
                    services,
                    processing_hint=processing_hint,
                )
            if processing_hint == "auto":
                logger.warning(
                    "worker.ingestion.scan_detected_path_c_unavailable",
                    source_id=str(source.id),
                    page_count=file_metadata.page_count,
                )

        if not chunk_data:
            raise ValueError("Parsed document produced no chunks")

        task.progress = 40
        await session.commit()

        initialized = await initialize_pipeline_records(
            session,
            source=source,
            snapshot_service=services.snapshot_service,
            processing_path=ProcessingPath.PATH_B,
            processing_hint=processing_hint,
        )
        document = initialized.document
        document_version = initialized.document_version
        snapshot_id = initialized.snapshot_id

        chunk_rows = [
            Chunk(
                id=uuid.uuid7(),
                owner_id=source.owner_id,
                agent_id=source.agent_id,
                knowledge_base_id=source.knowledge_base_id,
                document_version_id=document_version.id,
                snapshot_id=snapshot_id,
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
        persisted_state = PersistedPipelineState(
            snapshot_id=snapshot_id,
            document_id=document.id,
            document_version_id=document_version.id,
            chunk_ids=[chunk.id for chunk in chunk_rows],
            token_count_total=sum(chunk.token_count for chunk in chunk_data),
        )

        embed_result = await embed_and_index_chunks(
            session,
            task=task,
            source=source,
            services=services,
            chunk_data=chunk_data,
            chunk_rows=chunk_rows,
            snapshot_id=snapshot_id,
            document_id=document.id,
            document_version_id=document_version.id,
            processing_path=ProcessingPath.PATH_B,
            pipeline_version="s2-02-path-b",
            page_count=file_metadata.page_count,
            duration_seconds=file_metadata.duration_seconds,
        )

        if not isinstance(embed_result, PersistedPipelineState):
            return embed_result

        persisted_state = embed_result

        return PathBResult(
            snapshot_id=snapshot_id,
            document_id=document.id,
            document_version_id=document_version.id,
            chunk_ids=persisted_state.chunk_ids,
            chunk_count=len(chunk_rows),
            token_count_total=persisted_state.token_count_total,
            processing_path=ProcessingPath.PATH_B,
            pipeline_version="s2-02-path-b",
        )
    except TextChunkPipelineError as error:
        await session.rollback()
        persisted_state = error.persisted_state
        if error.qdrant_write_may_have_happened:
            await cleanup_qdrant_chunks(services.qdrant_service, persisted_state.chunk_ids)
        await mark_persisted_records_failed(
            session,
            source_id=source.id,
            document_id=persisted_state.document_id,
            document_version_id=persisted_state.document_version_id,
            chunk_ids=persisted_state.chunk_ids,
        )
        raise error.cause
    except Exception:
        await session.rollback()
        raise


def _is_suspected_scan(
    chunk_data: list[ChunkData],
    *,
    page_count: int | None,
    min_chars_per_page: int,
) -> bool:
    if page_count is None or page_count <= 0:
        return False

    total_chars = sum(len(chunk.text_content.strip()) for chunk in chunk_data)
    return (total_chars / page_count) < min_chars_per_page
