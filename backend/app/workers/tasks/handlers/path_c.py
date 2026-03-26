from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BackgroundTask, Chunk, Source
from app.db.models.enums import ChunkStatus, ProcessingPath
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


@dataclass(slots=True, frozen=True)
class PathCResult:
    snapshot_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_ids: list[uuid.UUID]
    chunk_count: int
    token_count_total: int
    processing_path: ProcessingPath
    pipeline_version: str


async def handle_path_c(
    session: AsyncSession,
    task: BackgroundTask,
    source: Source,
    file_bytes: bytes,
    file_metadata: FileMetadata,
    services: PipelineServices,
    processing_hint: str = "auto",
) -> PathCResult | SkipEmbeddingResult | BatchSubmittedResult:
    if services.document_ai_parser is None:
        raise RuntimeError("Document AI parser is not configured")

    persisted_state: PersistedPipelineState | None = None

    try:
        chunk_data = await services.document_ai_parser.parse_and_chunk(
            file_bytes,
            source.file_path.rsplit("/", maxsplit=1)[-1],
            source.source_type,
        )
        if not chunk_data:
            raise ValueError("Document AI produced no chunks")

        task.progress = 40
        await session.commit()

        initialized = await initialize_pipeline_records(
            session,
            source=source,
            snapshot_service=services.snapshot_service,
            processing_path=ProcessingPath.PATH_C,
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
            processing_path=ProcessingPath.PATH_C,
            pipeline_version="s4-06-path-c",
            page_count=file_metadata.page_count,
            duration_seconds=file_metadata.duration_seconds,
        )

        if not isinstance(embed_result, PersistedPipelineState):
            return embed_result

        persisted_state = embed_result
        return PathCResult(
            snapshot_id=snapshot_id,
            document_id=document.id,
            document_version_id=document_version.id,
            chunk_ids=persisted_state.chunk_ids,
            chunk_count=len(chunk_rows),
            token_count_total=persisted_state.token_count_total,
            processing_path=ProcessingPath.PATH_C,
            pipeline_version="s4-06-path-c",
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
