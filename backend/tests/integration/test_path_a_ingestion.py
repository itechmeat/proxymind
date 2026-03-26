from __future__ import annotations

import base64
import io
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pypdf import PdfWriter
from qdrant_client import AsyncQdrantClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import BackgroundTask, Chunk, DocumentVersion, EmbeddingProfile, Source
from app.db.models.enums import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    ChunkStatus,
    ProcessingPath,
    SourceStatus,
    SourceType,
)
from app.services.document_processing import ChunkData
from app.services.path_router import FileMetadata
from app.services.qdrant import QdrantService
from app.services.snapshot import SnapshotService
from app.workers.tasks import ingestion

MINIMAL_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+yF9kAAAAASUVORK5CYII="
)


async def _seed_task(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_type: SourceType,
    filename: str,
    mime_type: str,
    file_bytes: bytes,
) -> tuple[uuid.UUID, uuid.UUID]:
    source_id = uuid.uuid7()
    task_id = uuid.uuid7()
    async with session_factory() as session:
        source = Source(
            id=source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            source_type=source_type,
            title="Path A integration source",
            file_path=f"{DEFAULT_AGENT_ID}/{source_id}/{filename}",
            file_size_bytes=len(file_bytes),
            mime_type=mime_type,
            status=SourceStatus.PENDING,
        )
        task = BackgroundTask(
            id=task_id,
            agent_id=DEFAULT_AGENT_ID,
            task_type=BackgroundTaskType.INGESTION,
            status=BackgroundTaskStatus.PENDING,
            source_id=source_id,
        )
        session.add_all([source, task])
        await session.commit()
    return source_id, task_id


async def _qdrant_service(qdrant_url: str) -> QdrantService:
    service = QdrantService(
        client=AsyncQdrantClient(url=qdrant_url),
        collection_name=f"test_path_a_{uuid.uuid4().hex}",
        embedding_dimensions=3,
        bm25_language="english",
    )
    await service.ensure_collection()
    return service


def _pdf_bytes(page_count: int) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=72, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_processes_image_via_path_a_and_indexes_in_qdrant(
    session_factory: async_sessionmaker[AsyncSession],
    qdrant_url: str,
) -> None:
    source_id, task_id = await _seed_task(
        session_factory,
        source_type=SourceType.IMAGE,
        filename="photo.png",
        mime_type="image/png",
        file_bytes=MINIMAL_PNG_BYTES,
    )
    qdrant_service = await _qdrant_service(qdrant_url)
    worker_ctx = {
        "session_factory": session_factory,
        "settings": SimpleNamespace(bm25_language="english"),
        "path_a_text_threshold_pdf": 2000,
        "path_a_text_threshold_media": 500,
        "path_a_max_pdf_pages": 6,
        "path_a_max_audio_duration_sec": 80,
        "path_a_max_video_duration_sec": 120,
        "storage_service": SimpleNamespace(download=AsyncMock(return_value=MINIMAL_PNG_BYTES)),
        "document_processor": SimpleNamespace(parse_and_chunk=AsyncMock()),
        "embedding_service": SimpleNamespace(
            model="gemini-embedding-2-preview",
            dimensions=3,
            embed_texts=AsyncMock(),
            embed_file=AsyncMock(return_value=[0.1, 0.2, 0.3]),
        ),
        "gemini_content_service": SimpleNamespace(
            extract_text_content=AsyncMock(return_value="a red square logo")
        ),
        "tokenizer": SimpleNamespace(count_tokens=lambda _text: 4),
        "qdrant_service": qdrant_service,
        "snapshot_service": SnapshotService(),
    }

    try:
        await ingestion.process_ingestion(worker_ctx, str(task_id))

        async with session_factory() as session:
            task = await session.get(BackgroundTask, task_id)
            source = await session.get(Source, source_id)
            version = await session.scalar(select(DocumentVersion))
            chunks = (await session.scalars(select(Chunk))).all()
            embedding_profile = await session.scalar(select(EmbeddingProfile))

        assert task is not None
        assert source is not None
        assert version is not None
        assert embedding_profile is not None
        assert task.status is BackgroundTaskStatus.COMPLETE
        assert task.result_metadata is not None
        assert task.result_metadata["processing_path"] == "path_a"
        assert source.status is SourceStatus.READY
        assert version.processing_path is ProcessingPath.PATH_A
        assert embedding_profile.pipeline_version == "s3-04-path-a"
        assert len(chunks) == 1
        assert chunks[0].status is ChunkStatus.INDEXED

        results = await qdrant_service.hybrid_search(
            text="red square",
            vector=[0.1, 0.2, 0.3],
            snapshot_id=chunks[0].snapshot_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            limit=5,
        )

        assert results
        assert results[0].chunk_id == chunks[0].id
    finally:
        await qdrant_service.close()


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_falls_back_to_path_b_when_pdf_text_is_too_long(
    session_factory: async_sessionmaker[AsyncSession],
    qdrant_url: str,
) -> None:
    pdf_bytes = _pdf_bytes(3)
    source_id, task_id = await _seed_task(
        session_factory,
        source_type=SourceType.PDF,
        filename="report.pdf",
        mime_type="application/pdf",
        file_bytes=pdf_bytes,
    )
    qdrant_service = await _qdrant_service(qdrant_url)
    worker_ctx = {
        "session_factory": session_factory,
        "settings": SimpleNamespace(bm25_language="english"),
        "path_a_text_threshold_pdf": 2000,
        "path_a_text_threshold_media": 500,
        "path_a_max_pdf_pages": 6,
        "path_a_max_audio_duration_sec": 80,
        "path_a_max_video_duration_sec": 120,
        "storage_service": SimpleNamespace(download=AsyncMock(return_value=pdf_bytes)),
        "document_processor": SimpleNamespace(
            parse_and_chunk=AsyncMock(
                return_value=[
                    ChunkData(
                        text_content="first fallback chunk",
                        token_count=3,
                        chunk_index=0,
                        anchor_page=1,
                        anchor_chapter="Intro",
                        anchor_section=None,
                    ),
                    ChunkData(
                        text_content="second fallback chunk",
                        token_count=3,
                        chunk_index=1,
                        anchor_page=2,
                        anchor_chapter="Body",
                        anchor_section=None,
                    ),
                ]
            )
        ),
        "embedding_service": SimpleNamespace(
            model="gemini-embedding-2-preview",
            dimensions=3,
            embed_texts=AsyncMock(return_value=[[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]),
            embed_file=AsyncMock(return_value=[0.1, 0.2, 0.3]),
        ),
        "gemini_content_service": SimpleNamespace(
            extract_text_content=AsyncMock(return_value="word " * 2001)
        ),
        "tokenizer": SimpleNamespace(count_tokens=lambda _text: 2001),
        "qdrant_service": qdrant_service,
        "snapshot_service": SnapshotService(),
    }

    try:
        await ingestion.process_ingestion(worker_ctx, str(task_id))

        async with session_factory() as session:
            task = await session.get(BackgroundTask, task_id)
            source = await session.get(Source, source_id)
            version = await session.scalar(select(DocumentVersion))
            chunks = (await session.scalars(select(Chunk).order_by(Chunk.chunk_index.asc()))).all()
            embedding_profile = await session.scalar(select(EmbeddingProfile))

        assert task is not None
        assert source is not None
        assert version is not None
        assert embedding_profile is not None
        assert task.status is BackgroundTaskStatus.COMPLETE
        assert task.result_metadata is not None
        assert task.result_metadata["processing_path"] == "path_b"
        assert source.status is SourceStatus.READY
        assert version.processing_path is ProcessingPath.PATH_B
        assert embedding_profile.pipeline_version == "s2-02-path-b"
        assert len(chunks) == 2
        assert [chunk.status for chunk in chunks] == [ChunkStatus.INDEXED, ChunkStatus.INDEXED]
        worker_ctx["embedding_service"].embed_file.assert_not_awaited()  # type: ignore[attr-defined]
    finally:
        await qdrant_service.close()


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_preserves_skip_embedding_during_path_a_to_path_b_fallback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    pdf_bytes = _pdf_bytes(3)
    source_id, task_id = await _seed_task(
        session_factory,
        source_type=SourceType.PDF,
        filename="report.pdf",
        mime_type="application/pdf",
        file_bytes=pdf_bytes,
    )
    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        assert task is not None
        task.result_metadata = {"skip_embedding": True}
        await session.commit()

    qdrant_service = SimpleNamespace(
        upsert_chunks=AsyncMock(),
        delete_chunks=AsyncMock(),
    )
    worker_ctx = {
        "session_factory": session_factory,
        "settings": SimpleNamespace(
            bm25_language="english",
            batch_embed_chunk_threshold=50,
            embedding_task_type="RETRIEVAL_DOCUMENT",
        ),
        "path_a_text_threshold_pdf": 2000,
        "path_a_text_threshold_media": 500,
        "path_a_max_pdf_pages": 6,
        "path_a_max_audio_duration_sec": 80,
        "path_a_max_video_duration_sec": 120,
        "storage_service": SimpleNamespace(download=AsyncMock(return_value=pdf_bytes)),
        "document_processor": SimpleNamespace(
            parse_and_chunk=AsyncMock(
                return_value=[
                    ChunkData(
                        text_content="first fallback chunk",
                        token_count=3,
                        chunk_index=0,
                        anchor_page=1,
                        anchor_chapter="Intro",
                        anchor_section=None,
                    ),
                    ChunkData(
                        text_content="second fallback chunk",
                        token_count=3,
                        chunk_index=1,
                        anchor_page=2,
                        anchor_chapter="Body",
                        anchor_section=None,
                    ),
                ]
            )
        ),
        "embedding_service": SimpleNamespace(
            model="gemini-embedding-2-preview",
            dimensions=3,
            embed_texts=AsyncMock(),
            embed_file=AsyncMock(),
        ),
        "gemini_content_service": SimpleNamespace(
            extract_text_content=AsyncMock(return_value="word " * 2001)
        ),
        "tokenizer": SimpleNamespace(count_tokens=lambda _text: 2001),
        "qdrant_service": qdrant_service,
        "snapshot_service": SnapshotService(),
        "batch_orchestrator": None,
    }

    await ingestion.process_ingestion(worker_ctx, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)
        version = await session.scalar(select(DocumentVersion))
        chunks = (await session.scalars(select(Chunk).order_by(Chunk.chunk_index.asc()))).all()
        embedding_profile = await session.scalar(select(EmbeddingProfile))

    assert task is not None
    assert source is not None
    assert version is not None
    assert task.status is BackgroundTaskStatus.COMPLETE
    assert task.progress == 100
    assert task.result_metadata is not None
    assert task.result_metadata["skip_embedding"] is True
    assert task.result_metadata["processing_path"] == "path_b"
    assert source.status is SourceStatus.READY
    assert version.processing_path is ProcessingPath.PATH_B
    assert embedding_profile is None
    assert len(chunks) == 2
    assert [chunk.status for chunk in chunks] == [ChunkStatus.PENDING, ChunkStatus.PENDING]
    worker_ctx["embedding_service"].embed_file.assert_not_awaited()  # type: ignore[attr-defined]
    worker_ctx["embedding_service"].embed_texts.assert_not_awaited()  # type: ignore[attr-defined]
    qdrant_service.upsert_chunks.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
@pytest.mark.parametrize(
    ("source_type", "filename", "mime_type", "duration_seconds"),
    [
        (SourceType.AUDIO, "clip.mp3", "audio/mpeg", 81.0),
        (SourceType.VIDEO, "clip.mp4", "video/mp4", 121.0),
    ],
)
async def test_worker_rejects_over_limit_media_before_persist(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
    source_type: SourceType,
    filename: str,
    mime_type: str,
    duration_seconds: float,
) -> None:
    source_id, task_id = await _seed_task(
        session_factory,
        source_type=source_type,
        filename=filename,
        mime_type=mime_type,
        file_bytes=b"media-bytes",
    )
    worker_ctx = {
        "session_factory": session_factory,
        "settings": SimpleNamespace(bm25_language="english"),
        "path_a_text_threshold_pdf": 2000,
        "path_a_text_threshold_media": 500,
        "path_a_max_pdf_pages": 6,
        "path_a_max_audio_duration_sec": 80,
        "path_a_max_video_duration_sec": 120,
        "storage_service": SimpleNamespace(download=AsyncMock(return_value=b"media-bytes")),
        "document_processor": SimpleNamespace(parse_and_chunk=AsyncMock()),
        "embedding_service": SimpleNamespace(
            model="gemini-embedding-2-preview",
            dimensions=3,
            embed_texts=AsyncMock(),
            embed_file=AsyncMock(return_value=[0.1, 0.2, 0.3]),
        ),
        "gemini_content_service": SimpleNamespace(extract_text_content=AsyncMock()),
        "tokenizer": SimpleNamespace(count_tokens=lambda _text: 0),
        "qdrant_service": SimpleNamespace(
            upsert_chunks=AsyncMock(),
            delete_chunks=AsyncMock(),
        ),
        "snapshot_service": SnapshotService(),
    }

    monkeypatch.setattr(
        ingestion,
        "inspect_file",
        lambda _bytes, _source_type: FileMetadata(
            page_count=None,
            duration_seconds=duration_seconds,
            file_size_bytes=11,
        ),
    )

    await ingestion.process_ingestion(worker_ctx, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)

    assert task is not None
    assert source is not None
    assert task.status is BackgroundTaskStatus.FAILED
    assert task.error_message is not None
    assert "duration limit" in task.error_message
    assert source.status is SourceStatus.FAILED

    async with session_factory() as session:
        assert await session.scalar(select(DocumentVersion)) is None
        assert (await session.scalars(select(Chunk))).all() == []
