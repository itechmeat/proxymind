from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import BackgroundTask, Chunk, Document, DocumentVersion, Source
from app.db.models.enums import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    ChunkStatus,
    DocumentStatus,
    DocumentVersionStatus,
    SourceStatus,
    SourceType,
)
from app.services.docling_parser import ChunkData
from app.services.snapshot import SnapshotService
from app.workers.tasks.handlers.path_b import PathBResult, handle_path_b
from app.workers.tasks.pipeline import BatchSubmittedResult, PipelineServices


async def _seed_source_and_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    source_id = uuid.uuid7()
    task_id = uuid.uuid7()
    async with session_factory() as session:
        source = Source(
            id=source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            source_type=SourceType.MARKDOWN,
            title="Path B source",
            file_path=f"{DEFAULT_AGENT_ID}/{source_id}/doc.md",
            file_size_bytes=256,
            mime_type="text/markdown",
            status=SourceStatus.PENDING,
        )
        task = BackgroundTask(
            id=task_id,
            agent_id=DEFAULT_AGENT_ID,
            task_type=BackgroundTaskType.INGESTION,
            status=BackgroundTaskStatus.PROCESSING,
            source_id=source_id,
        )
        session.add_all([source, task])
        await session.commit()
    return source_id, task_id


def _chunk_data(count: int) -> list[ChunkData]:
    return [
        ChunkData(
            text_content=f"chunk-{index}",
            token_count=1,
            chunk_index=index,
            anchor_page=None,
            anchor_chapter=None,
            anchor_section=None,
        )
        for index in range(count)
    ]


def _services(
    *,
    chunk_count: int,
    batch_orchestrator: object | None = None,
) -> PipelineServices:
    return PipelineServices(
        storage_service=SimpleNamespace(download=AsyncMock()),
        docling_parser=SimpleNamespace(parse_and_chunk=AsyncMock(return_value=_chunk_data(chunk_count))),
        embedding_service=SimpleNamespace(
            model="gemini-embedding-2-preview",
            dimensions=3,
            embed_texts=AsyncMock(return_value=[[0.1, 0.2, 0.3]] * chunk_count),
        ),
        qdrant_service=SimpleNamespace(
            upsert_chunks=AsyncMock(),
            delete_chunks=AsyncMock(),
        ),
        snapshot_service=SnapshotService(),
        gemini_content_service=SimpleNamespace(extract_text_content=AsyncMock()),
        tokenizer=SimpleNamespace(count_tokens=lambda _text: 1),
        settings=SimpleNamespace(
            batch_embed_chunk_threshold=50,
            embedding_task_type="RETRIEVAL_DOCUMENT",
        ),
        default_language="english",
        path_a_text_threshold_pdf=2000,
        path_a_text_threshold_media=500,
        path_a_max_pdf_pages=6,
        path_a_max_audio_duration_sec=80,
        path_a_max_video_duration_sec=120,
        batch_orchestrator=batch_orchestrator,
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_b_uses_interactive_embedding_at_threshold(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(session_factory)
    batch_orchestrator = SimpleNamespace(
        create_batch_job_for_threshold=AsyncMock(),
        submit_to_gemini=AsyncMock(),
    )
    services = _services(chunk_count=50, batch_orchestrator=batch_orchestrator)

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        result = await handle_path_b(session, task, source, b"markdown-bytes", services)

    assert isinstance(result, PathBResult)
    assert result.chunk_count == 50
    services.embedding_service.embed_texts.assert_awaited_once()  # type: ignore[attr-defined]
    services.qdrant_service.upsert_chunks.assert_awaited_once()  # type: ignore[attr-defined]
    batch_orchestrator.create_batch_job_for_threshold.assert_not_awaited()
    batch_orchestrator.submit_to_gemini.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_b_submits_batch_above_threshold(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(session_factory)
    batch_orchestrator = SimpleNamespace(
        create_batch_job_for_threshold=AsyncMock(return_value=SimpleNamespace()),
        submit_to_gemini=AsyncMock(return_value=SimpleNamespace()),
    )
    services = _services(chunk_count=51, batch_orchestrator=batch_orchestrator)

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        result = await handle_path_b(session, task, source, b"markdown-bytes", services)

        chunks = (await session.scalars(select(Chunk).order_by(Chunk.chunk_index.asc()))).all()

    assert isinstance(result, BatchSubmittedResult)
    assert result.chunk_count == 51
    assert len(chunks) == 51
    assert all(chunk.status is ChunkStatus.PENDING for chunk in chunks)
    services.embedding_service.embed_texts.assert_not_awaited()  # type: ignore[attr-defined]
    services.qdrant_service.upsert_chunks.assert_not_awaited()  # type: ignore[attr-defined]
    batch_orchestrator.create_batch_job_for_threshold.assert_awaited_once()
    batch_orchestrator.submit_to_gemini.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_b_marks_records_failed_when_batch_submit_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(session_factory)
    batch_orchestrator = SimpleNamespace(
        create_batch_job_for_threshold=AsyncMock(return_value=SimpleNamespace()),
        submit_to_gemini=AsyncMock(side_effect=RuntimeError("batch submit failed")),
    )
    services = _services(chunk_count=51, batch_orchestrator=batch_orchestrator)

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        with pytest.raises(RuntimeError, match="batch submit failed"):
            await handle_path_b(session, task, source, b"markdown-bytes", services)

    async with session_factory() as session:
        document = await session.scalar(select(Document))
        version = await session.scalar(select(DocumentVersion))
        chunks = (await session.scalars(select(Chunk).order_by(Chunk.chunk_index.asc()))).all()

    assert document is not None
    assert document.status is DocumentStatus.FAILED
    assert version is not None
    assert version.status is DocumentVersionStatus.FAILED
    assert len(chunks) == 51
    assert all(chunk.status is ChunkStatus.FAILED for chunk in chunks)
    services.embedding_service.embed_texts.assert_not_awaited()  # type: ignore[attr-defined]
    services.qdrant_service.upsert_chunks.assert_not_awaited()  # type: ignore[attr-defined]
    batch_orchestrator.create_batch_job_for_threshold.assert_awaited_once()
    batch_orchestrator.submit_to_gemini.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_b_marks_records_failed_when_batch_job_creation_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(session_factory)
    batch_orchestrator = SimpleNamespace(
        create_batch_job_for_threshold=AsyncMock(side_effect=RuntimeError("batch create failed")),
        submit_to_gemini=AsyncMock(),
    )
    services = _services(chunk_count=51, batch_orchestrator=batch_orchestrator)

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        with pytest.raises(RuntimeError, match="batch create failed"):
            await handle_path_b(session, task, source, b"markdown-bytes", services)

    batch_orchestrator.submit_to_gemini.assert_not_awaited()
    services.qdrant_service.delete_chunks.assert_not_awaited()  # type: ignore[attr-defined]

    async with session_factory() as session:
        document = await session.scalar(select(Document))
        version = await session.scalar(select(DocumentVersion))
        chunks = (await session.scalars(select(Chunk))).all()

    assert document is not None
    assert document.status is DocumentStatus.FAILED
    assert version is not None
    assert version.status is DocumentVersionStatus.FAILED
    assert chunks
    assert all(chunk.status is ChunkStatus.FAILED for chunk in chunks)
