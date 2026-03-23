from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BackgroundTask, Chunk, Source
from app.db.models.enums import (
    ChunkStatus,
    ProcessingPath,
    SourceType,
)
from app.services.path_router import FileMetadata
from app.services.qdrant import QdrantChunkPoint
from app.services.storage import determine_mime_type
from app.workers.tasks.pipeline import (
    PersistedPipelineState,
    PipelineServices,
    SkipEmbeddingResult,
    cleanup_qdrant_chunks,
    initialize_pipeline_records,
    mark_persisted_records_failed,
)


@dataclass(slots=True, frozen=True)
class PathAResult:
    snapshot_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_ids: list[uuid.UUID]
    chunk_count: int
    token_count_total: int
    processing_path: ProcessingPath
    pipeline_version: str


@dataclass(slots=True, frozen=True)
class PathAFallback:
    reason: str


async def handle_path_a(
    session: AsyncSession,
    task: BackgroundTask,
    source: Source,
    file_bytes: bytes,
    file_metadata: FileMetadata,
    services: PipelineServices,
) -> PathAResult | PathAFallback | SkipEmbeddingResult:
    mime_type = source.mime_type or determine_mime_type(source.file_path)
    text_content = await services.gemini_content_service.extract_text_content(
        file_bytes,
        mime_type,
        source.source_type,
    )
    token_count = services.tokenizer.count_tokens(text_content)

    if source.source_type is SourceType.PDF and token_count > services.path_a_text_threshold_pdf:
        return PathAFallback(
            reason="PDF text content exceeds the Path A threshold; falling back to Path B"
        )
    if source.source_type in {SourceType.AUDIO, SourceType.VIDEO}:
        if token_count > services.path_a_text_threshold_media:
            source_kind = "audio" if source.source_type is SourceType.AUDIO else "video"
            raise ValueError(
                f"{source_kind.capitalize()} content is too dense for single-chunk indexing "
                "and Path B is unavailable"
            )

    task.progress = 40
    await session.commit()

    persisted_state: PersistedPipelineState | None = None
    qdrant_write_may_have_happened = False
    try:
        initialized = await initialize_pipeline_records(
            session,
            source=source,
            snapshot_service=services.snapshot_service,
            processing_path=ProcessingPath.PATH_A,
        )
        document = initialized.document
        document_version = initialized.document_version
        snapshot_id = initialized.snapshot_id

        anchor_page, anchor_timecode = _anchor_metadata(source.source_type, file_metadata)
        chunk = Chunk(
            id=uuid.uuid7(),
            owner_id=source.owner_id,
            agent_id=source.agent_id,
            knowledge_base_id=source.knowledge_base_id,
            document_version_id=document_version.id,
            snapshot_id=snapshot_id,
            source_id=source.id,
            chunk_index=0,
            text_content=text_content,
            token_count=token_count,
            anchor_page=anchor_page,
            anchor_chapter=None,
            anchor_section=None,
            anchor_timecode=anchor_timecode,
            status=ChunkStatus.PENDING,
        )
        session.add(chunk)

        persisted_state = PersistedPipelineState(
            snapshot_id=snapshot_id,
            document_id=document.id,
            document_version_id=document_version.id,
            chunk_ids=[chunk.id],
            token_count_total=token_count,
        )

        task.progress = 50
        await session.commit()

        skip_embedding = bool((task.result_metadata or {}).get("skip_embedding"))
        if skip_embedding:
            return SkipEmbeddingResult(
                snapshot_id=snapshot_id,
                document_id=document.id,
                document_version_id=document_version.id,
                chunk_ids=[chunk.id],
                chunk_count=1,
                token_count_total=token_count,
                processing_path=ProcessingPath.PATH_A,
                pipeline_version="s3-04-path-a",
            )

        vector = await services.embedding_service.embed_file(
            file_bytes,
            mime_type,
            task_type="RETRIEVAL_DOCUMENT",
        )
        task.progress = 85
        await session.commit()

        qdrant_write_may_have_happened = True
        await services.qdrant_service.upsert_chunks(
            [
                QdrantChunkPoint(
                    chunk_id=chunk.id,
                    vector=vector,
                    snapshot_id=snapshot_id,
                    source_id=source.id,
                    document_version_id=document_version.id,
                    agent_id=source.agent_id,
                    knowledge_base_id=source.knowledge_base_id,
                    text_content=text_content,
                    chunk_index=0,
                    token_count=token_count,
                    anchor_page=anchor_page,
                    anchor_chapter=None,
                    anchor_section=None,
                    anchor_timecode=anchor_timecode,
                    source_type=source.source_type,
                    language=source.language or services.default_language,
                    status=ChunkStatus.INDEXED,
                    page_count=file_metadata.page_count,
                    duration_seconds=file_metadata.duration_seconds,
                )
            ]
        )
        task.progress = 95
        await session.commit()

        return PathAResult(
            snapshot_id=snapshot_id,
            document_id=document.id,
            document_version_id=document_version.id,
            chunk_ids=[chunk.id],
            chunk_count=1,
            token_count_total=token_count,
            processing_path=ProcessingPath.PATH_A,
            pipeline_version="s3-04-path-a",
        )
    except Exception:
        await session.rollback()
        if qdrant_write_may_have_happened and persisted_state is not None:
            await cleanup_qdrant_chunks(services.qdrant_service, persisted_state.chunk_ids)
        if persisted_state is not None:
            await mark_persisted_records_failed(
                session,
                source_id=source.id,
                document_id=persisted_state.document_id,
                document_version_id=persisted_state.document_version_id,
                chunk_ids=persisted_state.chunk_ids,
            )
        raise


def _anchor_metadata(
    source_type: SourceType,
    file_metadata: FileMetadata,
) -> tuple[int | None, str | None]:
    if source_type is SourceType.PDF:
        return 1, None
    if source_type in {SourceType.AUDIO, SourceType.VIDEO}:
        if file_metadata.duration_seconds is None:
            return None, None
        return None, _format_timecode(file_metadata.duration_seconds)
    return None, None


def _format_timecode(duration_seconds: float) -> str:
    total_seconds = max(0, int(round(duration_seconds)))
    minutes, seconds = divmod(total_seconds, 60)
    return f"0:00-{minutes}:{seconds:02d}"
