from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BackgroundTask, Chunk, Source
from app.db.models.enums import ChunkStatus, ProcessingPath
from app.services.qdrant import QdrantChunkPoint
from app.workers.tasks.pipeline import (
    BatchSubmittedResult,
    PersistedPipelineState,
    PipelineServices,
    SkipEmbeddingResult,
    cleanup_qdrant_chunks,
    initialize_pipeline_records,
    mark_persisted_records_failed,
)

DEFAULT_EMBEDDING_TASK_TYPE = "RETRIEVAL_DOCUMENT"


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
    services: PipelineServices,
) -> PathBResult | SkipEmbeddingResult | BatchSubmittedResult:
    persisted_state: PersistedPipelineState | None = None
    qdrant_write_may_have_happened = False

    try:
        chunk_data = await services.docling_parser.parse_and_chunk(
            file_bytes,
            source.file_path.rsplit("/", maxsplit=1)[-1],
            source.source_type,
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

        task.progress = 50
        await session.commit()

        skip_embedding = bool((task.result_metadata or {}).get("skip_embedding"))
        if skip_embedding:
            return SkipEmbeddingResult(
                snapshot_id=snapshot_id,
                document_id=document.id,
                document_version_id=document_version.id,
                chunk_ids=[chunk.id for chunk in chunk_rows],
                chunk_count=len(chunk_rows),
                token_count_total=persisted_state.token_count_total,
                processing_path=ProcessingPath.PATH_B,
                pipeline_version="s2-02-path-b",
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
                chunk_ids=[chunk.id for chunk in chunk_rows],
                document_id=document.id,
                document_version_id=document_version.id,
                chunk_count=len(chunk_rows),
                token_count_total=persisted_state.token_count_total,
                processing_path=ProcessingPath.PATH_B.value,
                pipeline_version="s2-02-path-b",
            )
            await services.batch_orchestrator.submit_to_gemini(
                session,
                background_task_id=task.id,
                texts=[chunk.text_content for chunk in chunk_rows],
                chunk_ids=[chunk.id for chunk in chunk_rows],
                display_name=source.title,
            )
            task.progress = 60
            await session.commit()
            return BatchSubmittedResult(
                snapshot_id=snapshot_id,
                document_id=document.id,
                document_version_id=document_version.id,
                chunk_ids=[chunk.id for chunk in chunk_rows],
                chunk_count=len(chunk_rows),
                token_count_total=persisted_state.token_count_total,
                processing_path=ProcessingPath.PATH_B,
                pipeline_version="s2-02-path-b",
            )

        vectors = await services.embedding_service.embed_texts(
            [chunk.text_content for chunk in chunk_data],
            task_type=getattr(
                services.settings,
                "embedding_task_type",
                DEFAULT_EMBEDDING_TASK_TYPE,
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

        return PathBResult(
            snapshot_id=snapshot_id,
            document_id=document.id,
            document_version_id=document_version.id,
            chunk_ids=[chunk.id for chunk in chunk_rows],
            chunk_count=len(chunk_rows),
            token_count_total=persisted_state.token_count_total,
            processing_path=ProcessingPath.PATH_B,
            pipeline_version="s2-02-path-b",
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
