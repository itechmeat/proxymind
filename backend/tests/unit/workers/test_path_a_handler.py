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
    ProcessingPath,
    SourceStatus,
    SourceType,
)
from app.services.path_router import FileMetadata
from app.services.snapshot import SnapshotService
from app.workers.tasks.handlers.path_a import PathAFallback, PathAResult, handle_path_a
from app.workers.tasks.pipeline import PipelineServices, SkipEmbeddingResult


async def _seed_source_and_task(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_type: SourceType,
    filename: str,
    mime_type: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    source_id = uuid.uuid7()
    task_id = uuid.uuid7()
    async with session_factory() as session:
        source = Source(
            id=source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            source_type=source_type,
            title="Path A source",
            file_path=f"{DEFAULT_AGENT_ID}/{source_id}/{filename}",
            file_size_bytes=128,
            mime_type=mime_type,
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


def _services(
    *,
    extracted_text: str = "image description",
    token_count: int = 10,
    upsert_side_effect: Exception | None = None,
    extract_side_effect: Exception | None = None,
) -> PipelineServices:
    qdrant_service = SimpleNamespace(
        upsert_chunks=(
            AsyncMock(side_effect=upsert_side_effect)
            if upsert_side_effect is not None
            else AsyncMock()
        ),
        delete_chunks=AsyncMock(),
    )
    gemini_content_service = SimpleNamespace(
        extract_text_content=(
            AsyncMock(side_effect=extract_side_effect)
            if extract_side_effect is not None
            else AsyncMock(return_value=extracted_text)
        )
    )
    return PipelineServices(
        storage_service=SimpleNamespace(download=AsyncMock()),
        docling_parser=SimpleNamespace(parse_and_chunk=AsyncMock()),
        embedding_service=SimpleNamespace(
            model="gemini-embedding-2-preview",
            dimensions=3,
            embed_texts=AsyncMock(),
            embed_file=AsyncMock(return_value=[0.1, 0.2, 0.3]),
        ),
        qdrant_service=qdrant_service,
        snapshot_service=SnapshotService(),
        gemini_content_service=gemini_content_service,
        tokenizer=SimpleNamespace(count_tokens=lambda _text: token_count),
        settings=SimpleNamespace(),
        default_language="english",
        path_a_text_threshold_pdf=2000,
        path_a_text_threshold_media=500,
        path_a_max_pdf_pages=6,
        path_a_max_audio_duration_sec=80,
        path_a_max_video_duration_sec=120,
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_a_creates_single_image_chunk(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(
        session_factory,
        source_type=SourceType.IMAGE,
        filename="photo.png",
        mime_type="image/png",
    )
    services = _services()

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        result = await handle_path_a(
            session,
            task,
            source,
            b"image-bytes",
            FileMetadata(page_count=None, duration_seconds=None, file_size_bytes=11),
            services,
        )

    assert isinstance(result, PathAResult)
    assert result.chunk_count == 1
    qdrant_points = services.qdrant_service.upsert_chunks.await_args.args[0]
    assert len(qdrant_points) == 1
    assert qdrant_points[0].anchor_page is None
    assert qdrant_points[0].anchor_timecode is None
    assert qdrant_points[0].page_count is None
    assert qdrant_points[0].duration_seconds is None

    async with session_factory() as session:
        document = await session.scalar(select(Document))
        version = await session.scalar(select(DocumentVersion))
        chunk = await session.scalar(select(Chunk))

    assert document is not None
    assert document.status is DocumentStatus.PROCESSING
    assert version is not None
    assert version.status is DocumentVersionStatus.PROCESSING
    assert version.processing_path is ProcessingPath.PATH_A
    assert chunk is not None
    assert chunk.status is ChunkStatus.PENDING


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_a_skips_threshold_for_images(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(
        session_factory,
        source_type=SourceType.IMAGE,
        filename="photo.png",
        mime_type="image/png",
    )
    services = _services(token_count=50_000)

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        result = await handle_path_a(
            session,
            task,
            source,
            b"image-bytes",
            FileMetadata(page_count=None, duration_seconds=None, file_size_bytes=11),
            services,
        )

    assert isinstance(result, PathAResult)
    services.embedding_service.embed_file.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_a_returns_skip_embedding_result_without_upsert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(
        session_factory,
        source_type=SourceType.IMAGE,
        filename="photo.png",
        mime_type="image/png",
    )
    services = _services()

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None
        task.result_metadata = {"skip_embedding": True}

        result = await handle_path_a(
            session,
            task,
            source,
            b"image-bytes",
            FileMetadata(page_count=None, duration_seconds=None, file_size_bytes=11),
            services,
        )

    assert isinstance(result, SkipEmbeddingResult)
    services.embedding_service.embed_file.assert_not_awaited()  # type: ignore[attr-defined]
    services.qdrant_service.upsert_chunks.assert_not_awaited()  # type: ignore[attr-defined]

    async with session_factory() as session:
        document = await session.scalar(select(Document))
        version = await session.scalar(select(DocumentVersion))
        chunk = await session.scalar(select(Chunk))

    assert document is not None
    assert document.status is DocumentStatus.PROCESSING
    assert version is not None
    assert version.status is DocumentVersionStatus.PROCESSING
    assert chunk is not None
    assert chunk.status is ChunkStatus.PENDING


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_a_returns_pdf_fallback_before_persist(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(
        session_factory,
        source_type=SourceType.PDF,
        filename="report.pdf",
        mime_type="application/pdf",
    )
    services = _services(token_count=2001)

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        result = await handle_path_a(
            session,
            task,
            source,
            b"pdf-bytes",
            FileMetadata(page_count=3, duration_seconds=None, file_size_bytes=9),
            services,
        )

    assert result == PathAFallback(
        reason="PDF text content exceeds the Path A threshold; falling back to Path B"
    )
    services.embedding_service.embed_file.assert_not_awaited()  # type: ignore[attr-defined]
    services.qdrant_service.upsert_chunks.assert_not_awaited()  # type: ignore[attr-defined]

    async with session_factory() as session:
        assert await session.scalar(select(Document)) is None
        assert (await session.scalars(select(Chunk))).all() == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_a_raises_for_dense_audio_content(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(
        session_factory,
        source_type=SourceType.AUDIO,
        filename="clip.mp3",
        mime_type="audio/mpeg",
    )
    services = _services(token_count=501)

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        with pytest.raises(ValueError, match="Audio content is too dense"):
            await handle_path_a(
                session,
                task,
                source,
                b"audio-bytes",
                FileMetadata(page_count=None, duration_seconds=75.0, file_size_bytes=11),
                services,
            )

    async with session_factory() as session:
        assert await session.scalar(select(Document)) is None
        assert (await session.scalars(select(Chunk))).all() == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_a_propagates_gemini_extraction_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(
        session_factory,
        source_type=SourceType.IMAGE,
        filename="photo.png",
        mime_type="image/png",
    )
    services = _services(extract_side_effect=RuntimeError("gemini failed"))

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        with pytest.raises(RuntimeError, match="gemini failed"):
            await handle_path_a(
                session,
                task,
                source,
                b"image-bytes",
                FileMetadata(page_count=None, duration_seconds=None, file_size_bytes=11),
                services,
            )

    async with session_factory() as session:
        assert await session.scalar(select(Document)) is None
        assert (await session.scalars(select(Chunk))).all() == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_a_marks_records_failed_when_qdrant_upsert_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(
        session_factory,
        source_type=SourceType.IMAGE,
        filename="photo.png",
        mime_type="image/png",
    )
    services = _services(upsert_side_effect=RuntimeError("qdrant down"))

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        with pytest.raises(RuntimeError, match="qdrant down"):
            await handle_path_a(
                session,
                task,
                source,
                b"image-bytes",
                FileMetadata(page_count=None, duration_seconds=None, file_size_bytes=11),
                services,
            )

    services.qdrant_service.delete_chunks.assert_awaited_once()  # type: ignore[attr-defined]

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


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_a_formats_audio_anchor_timecode(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(
        session_factory,
        source_type=SourceType.AUDIO,
        filename="clip.mp3",
        mime_type="audio/mpeg",
    )
    services = _services(token_count=20)

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        await handle_path_a(
            session,
            task,
            source,
            b"audio-bytes",
            FileMetadata(page_count=None, duration_seconds=75.0, file_size_bytes=11),
            services,
        )

    qdrant_points = services.qdrant_service.upsert_chunks.await_args.args[0]
    assert qdrant_points[0].anchor_timecode == "0:00-1:15"
