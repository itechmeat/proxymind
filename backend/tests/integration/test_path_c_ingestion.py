from __future__ import annotations

import uuid
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import BackgroundTask, Chunk, DocumentVersion, Source
from app.db.models.enums import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    ChunkStatus,
    ProcessingPath,
    SourceStatus,
    SourceType,
)
from app.services.document_processing import ChunkData
from app.services.path_router import PathDecision
from app.services.snapshot import SnapshotService
from app.workers.tasks import ingestion

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


async def _seed_pdf_task(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    filename: str,
    result_metadata: dict[str, object] | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    source_id = uuid.uuid7()
    task_id = uuid.uuid7()
    async with session_factory() as session:
        source = Source(
            id=source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            source_type=SourceType.PDF,
            title="PDF source",
            file_path=f"{DEFAULT_AGENT_ID}/{source_id}/{filename}",
            file_size_bytes=1024,
            mime_type="application/pdf",
            status=SourceStatus.PENDING,
        )
        task = BackgroundTask(
            id=task_id,
            agent_id=DEFAULT_AGENT_ID,
            task_type=BackgroundTaskType.INGESTION,
            status=BackgroundTaskStatus.PENDING,
            source_id=source_id,
            result_metadata=result_metadata,
        )
        session.add_all([source, task])
        await session.commit()
    return source_id, task_id


def _ctx(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    file_bytes: bytes,
    path_b_chunks: list[ChunkData],
    path_c_chunks: list[ChunkData] | None,
    gemini_text: str = "",
    token_count: int = 0,
    path_a_max_pdf_pages: int = 1,
) -> dict[str, object]:
    qdrant_service = SimpleNamespace(upsert_chunks=AsyncMock(), delete_chunks=AsyncMock())
    return {
        "session_factory": session_factory,
        "settings": SimpleNamespace(
            bm25_language="english",
            batch_embed_chunk_threshold=50,
            embedding_task_type="RETRIEVAL_DOCUMENT",
            document_ai_enabled=path_c_chunks is not None,
            path_c_min_chars_per_page=50,
        ),
        "path_a_text_threshold_pdf": 2000,
        "path_a_text_threshold_media": 500,
        "path_a_max_pdf_pages": path_a_max_pdf_pages,
        "path_a_max_audio_duration_sec": 80,
        "path_a_max_video_duration_sec": 120,
        "path_c_min_chars_per_page": 50,
        "storage_service": SimpleNamespace(download=AsyncMock(return_value=file_bytes)),
        "document_processor": SimpleNamespace(parse_and_chunk=AsyncMock(return_value=path_b_chunks)),
        "document_ai_parser": (
            None
            if path_c_chunks is None
            else SimpleNamespace(parse_and_chunk=AsyncMock(return_value=path_c_chunks))
        ),
        "embedding_service": SimpleNamespace(
            model="gemini-embedding-2-preview",
            dimensions=3,
            embed_texts=AsyncMock(side_effect=lambda texts, **kwargs: [[0.1, 0.2, 0.3] for _ in texts]),
            embed_file=AsyncMock(return_value=[0.1, 0.2, 0.3]),
        ),
        "gemini_content_service": SimpleNamespace(
            extract_text_content=AsyncMock(return_value=gemini_text)
        ),
        "tokenizer": SimpleNamespace(count_tokens=lambda _text: token_count),
        "qdrant_service": qdrant_service,
        "snapshot_service": SnapshotService(),
        "batch_orchestrator": None,
    }


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_processing_hint_external_routes_to_path_c(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_pdf_task(
        session_factory,
        filename="external.pdf",
        result_metadata={"processing_hint": "external"},
    )
    ctx = _ctx(
        session_factory,
        file_bytes=(FIXTURES_DIR / "sample.pdf").read_bytes(),
        path_b_chunks=[ChunkData("local text", 2, 0, 1, None, None)],
        path_c_chunks=[ChunkData("external text", 2, 0, 1, None, None)],
    )

    await ingestion.process_ingestion(ctx, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)
        version = await session.scalar(select(DocumentVersion))
        chunks = (await session.scalars(select(Chunk))).all()

    assert task is not None
    assert source is not None
    assert version is not None
    assert task.status is BackgroundTaskStatus.COMPLETE
    assert task.result_metadata is not None
    assert task.result_metadata["processing_path"] == "path_c"
    assert source.status is SourceStatus.READY
    assert version.processing_path is ProcessingPath.PATH_C
    assert version.processing_hint == "external"
    assert chunks
    assert all(chunk.status is ChunkStatus.INDEXED for chunk in chunks)
    qdrant_points = ctx["qdrant_service"].upsert_chunks.await_args.args[0]  # type: ignore[index, attr-defined]
    expected_page_count = len(PdfReader(BytesIO((FIXTURES_DIR / "sample.pdf").read_bytes())).pages)
    assert qdrant_points
    assert all(point.page_count == expected_page_count for point in qdrant_points)
    ctx["document_processor"].parse_and_chunk.assert_not_awaited()  # type: ignore[attr-defined]
    ctx["document_ai_parser"].parse_and_chunk.assert_awaited_once()  # type: ignore[union-attr, attr-defined]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_scan_detection_reroutes_from_path_b_to_path_c(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, task_id = await _seed_pdf_task(session_factory, filename="scan.pdf")
    ctx = _ctx(
        session_factory,
        file_bytes=(FIXTURES_DIR / "sample.pdf").read_bytes(),
        path_b_chunks=[ChunkData("tiny", 1, 0, 1, None, None)],
        path_c_chunks=[ChunkData("document ai chunk", 3, 0, 1, None, None)],
    )

    await ingestion.process_ingestion(ctx, str(task_id))

    async with session_factory() as session:
        version = await session.scalar(select(DocumentVersion))

    assert version is not None
    assert version.processing_path is ProcessingPath.PATH_C
    assert version.processing_hint == "auto"
    ctx["document_processor"].parse_and_chunk.assert_awaited_once()  # type: ignore[attr-defined]
    ctx["document_ai_parser"].parse_and_chunk.assert_awaited_once()  # type: ignore[union-attr, attr-defined]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_scan_detection_falls_back_to_path_b_when_document_ai_disabled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, task_id = await _seed_pdf_task(session_factory, filename="scan-disabled.pdf")
    ctx = _ctx(
        session_factory,
        file_bytes=(FIXTURES_DIR / "sample.pdf").read_bytes(),
        path_b_chunks=[ChunkData("tiny", 1, 0, 1, None, None)],
        path_c_chunks=None,
    )

    await ingestion.process_ingestion(ctx, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        version = await session.scalar(select(DocumentVersion))

    assert task is not None
    assert version is not None
    assert task.status is BackgroundTaskStatus.COMPLETE
    assert version.processing_path is ProcessingPath.PATH_B
    assert version.processing_hint == "auto"


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_path_a_fallback_preserves_external_hint_and_dispatches_to_path_c(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.workers.tasks.handlers.path_a import PathAFallback

    _, task_id = await _seed_pdf_task(
        session_factory,
        filename="external-fallback.pdf",
        result_metadata={"processing_hint": "external"},
    )
    ctx = _ctx(
        session_factory,
        file_bytes=(FIXTURES_DIR / "sample.pdf").read_bytes(),
        path_b_chunks=[ChunkData("local text", 2, 0, 1, None, None)],
        path_c_chunks=[ChunkData("external text", 2, 0, 1, None, None)],
        gemini_text="word " * 2001,
        token_count=2001,
        path_a_max_pdf_pages=6,
    )

    async def _path_a_fallback(*_args, **_kwargs) -> PathAFallback:
        return PathAFallback(reason="fallback")

    monkeypatch.setattr(
        ingestion,
        "determine_path",
        lambda *_args, **_kwargs: PathDecision(
            path=ProcessingPath.PATH_A,
            reason="forced path a",
            rejected=False,
        ),
    )
    monkeypatch.setattr(
        "app.workers.tasks.handlers.path_a.handle_path_a",
        _path_a_fallback,
    )

    await ingestion.process_ingestion(ctx, str(task_id))

    async with session_factory() as session:
        version = await session.scalar(select(DocumentVersion))

    assert version is not None
    assert version.processing_path is ProcessingPath.PATH_C
    ctx["document_processor"].parse_and_chunk.assert_not_awaited()  # type: ignore[attr-defined]
    ctx["document_ai_parser"].parse_and_chunk.assert_awaited_once()  # type: ignore[union-attr, attr-defined]
