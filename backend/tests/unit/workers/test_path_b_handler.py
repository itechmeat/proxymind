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
from app.services.document_processing import ChunkData
from app.services.enrichment import EnrichmentResult, build_enriched_text
from app.services.path_router import FileMetadata
from app.services.snapshot import SnapshotService
from app.workers.tasks.handlers.path_b import (
    PathBResult,
    _is_suspected_scan,
    _resolve_parent_id,
    handle_path_b,
)
from app.workers.tasks.pipeline import BatchSubmittedResult, PipelineServices


async def _seed_source_and_task(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_type: SourceType = SourceType.MARKDOWN,
    filename: str = "doc.md",
    mime_type: str = "text/markdown",
) -> tuple[uuid.UUID, uuid.UUID]:
    source_id = uuid.uuid7()
    task_id = uuid.uuid7()
    async with session_factory() as session:
        source = Source(
            id=source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            source_type=source_type,
            title="Path B source",
            file_path=f"{DEFAULT_AGENT_ID}/{source_id}/{filename}",
            file_size_bytes=256,
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
    document_ai_enabled: bool = False,
    batch_orchestrator: object | None = None,
    enrichment_service: object | None = None,
) -> PipelineServices:
    return PipelineServices(
        storage_service=SimpleNamespace(download=AsyncMock()),
        document_processor=SimpleNamespace(
            parse_and_chunk=AsyncMock(return_value=_chunk_data(chunk_count))
        ),
        document_ai_parser=(
            None if not document_ai_enabled else SimpleNamespace(parse_and_chunk=AsyncMock())
        ),
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
        path_c_min_chars_per_page=50,
        document_ai_enabled=document_ai_enabled,
        batch_orchestrator=batch_orchestrator,
        enrichment_service=enrichment_service,
    )


def test_resolve_parent_id_raises_clear_error_for_orphan_chunk() -> None:
    with pytest.raises(ValueError, match="child-to-parent mapping"):
        _resolve_parent_id(
            chunk_index=7,
            document_version_id=uuid.uuid7(),
            child_parent_index_by_chunk_index={},
            parent_id_by_parent_index={},
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

        result = await handle_path_b(
            session,
            task,
            source,
            b"markdown-bytes",
            FileMetadata(page_count=None, duration_seconds=None, file_size_bytes=14),
            services,
        )

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

        result = await handle_path_b(
            session,
            task,
            source,
            b"markdown-bytes",
            FileMetadata(page_count=None, duration_seconds=None, file_size_bytes=14),
            services,
        )

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
async def test_handle_path_b_uses_enriched_text_for_embedding_and_payload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(session_factory)
    enrichment_result = EnrichmentResult(
        summary="Summary for chunk 0.",
        keywords=["retrieval", "search"],
        questions=["What is chunk 0 about?"],
    )
    enrichment_service = SimpleNamespace(
        model="gemini-2.5-flash",
        enrich=AsyncMock(return_value=[enrichment_result, None]),
    )
    services = _services(chunk_count=2, enrichment_service=enrichment_service)

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        result = await handle_path_b(
            session,
            task,
            source,
            b"markdown-bytes",
            FileMetadata(page_count=None, duration_seconds=None, file_size_bytes=14),
            services,
        )

        chunks = (await session.scalars(select(Chunk).order_by(Chunk.chunk_index.asc()))).all()

    assert isinstance(result, PathBResult)
    expected_text = build_enriched_text(
        text_content="chunk-0",
        summary=enrichment_result.summary,
        keywords=enrichment_result.keywords,
        questions=enrichment_result.questions,
    )
    services.embedding_service.embed_texts.assert_awaited_once_with(  # type: ignore[attr-defined]
        [expected_text, "chunk-1"],
        task_type="RETRIEVAL_DOCUMENT",
        title="Path B source",
    )
    qdrant_points = services.qdrant_service.upsert_chunks.await_args.args[0]  # type: ignore[attr-defined]
    assert qdrant_points[0].enriched_text == expected_text
    assert qdrant_points[0].enriched_summary == enrichment_result.summary
    assert qdrant_points[1].enriched_text is None
    assert chunks[0].enriched_text == expected_text
    assert chunks[0].enriched_keywords == ["retrieval", "search"]
    assert chunks[1].enriched_text is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_b_without_enrichment_service_uses_original_text(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(session_factory)
    services = _services(chunk_count=2, enrichment_service=None)

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        result = await handle_path_b(
            session,
            task,
            source,
            b"markdown-bytes",
            FileMetadata(page_count=None, duration_seconds=None, file_size_bytes=14),
            services,
        )

        chunks = (await session.scalars(select(Chunk).order_by(Chunk.chunk_index.asc()))).all()

    assert isinstance(result, PathBResult)
    services.embedding_service.embed_texts.assert_awaited_once_with(  # type: ignore[attr-defined]
        ["chunk-0", "chunk-1"],
        task_type="RETRIEVAL_DOCUMENT",
        title="Path B source",
    )
    qdrant_points = services.qdrant_service.upsert_chunks.await_args.args[0]  # type: ignore[attr-defined]
    assert qdrant_points[0].bm25_text == "chunk-0"
    assert qdrant_points[0].enriched_text is None
    assert qdrant_points[1].bm25_text == "chunk-1"
    assert chunks[0].enriched_text is None
    assert chunks[1].enriched_text is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_b_falls_back_to_original_text_when_enrichment_batch_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(session_factory)
    enrichment_service = SimpleNamespace(
        model="gemini-2.5-flash",
        enrich=AsyncMock(side_effect=RuntimeError("enrichment offline")),
    )
    services = _services(chunk_count=2, enrichment_service=enrichment_service)

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        result = await handle_path_b(
            session,
            task,
            source,
            b"markdown-bytes",
            FileMetadata(page_count=None, duration_seconds=None, file_size_bytes=14),
            services,
        )

        chunks = (await session.scalars(select(Chunk).order_by(Chunk.chunk_index.asc()))).all()

    assert isinstance(result, PathBResult)
    services.embedding_service.embed_texts.assert_awaited_once_with(  # type: ignore[attr-defined]
        ["chunk-0", "chunk-1"],
        task_type="RETRIEVAL_DOCUMENT",
        title="Path B source",
    )
    qdrant_points = services.qdrant_service.upsert_chunks.await_args.args[0]  # type: ignore[attr-defined]
    assert qdrant_points[0].enriched_text is None
    assert qdrant_points[1].enriched_text is None
    assert chunks[0].enriched_text is None
    assert chunks[1].enriched_text is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_b_uses_enriched_text_for_batch_submission(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(session_factory)
    batch_orchestrator = SimpleNamespace(
        create_batch_job_for_threshold=AsyncMock(return_value=SimpleNamespace()),
        submit_to_gemini=AsyncMock(return_value=SimpleNamespace()),
    )
    enrichment_result = EnrichmentResult(
        summary="Summary for chunk 0.",
        keywords=["retrieval", "search"],
        questions=["What is chunk 0 about?"],
    )
    enrichment_service = SimpleNamespace(
        model="gemini-2.5-flash",
        enrich=AsyncMock(return_value=[enrichment_result] + [None] * 50),
    )
    services = _services(
        chunk_count=51,
        batch_orchestrator=batch_orchestrator,
        enrichment_service=enrichment_service,
    )

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        result = await handle_path_b(
            session,
            task,
            source,
            b"markdown-bytes",
            FileMetadata(page_count=None, duration_seconds=None, file_size_bytes=14),
            services,
        )

        chunks = (await session.scalars(select(Chunk).order_by(Chunk.chunk_index.asc()))).all()

    assert isinstance(result, BatchSubmittedResult)
    expected_text = build_enriched_text(
        text_content="chunk-0",
        summary=enrichment_result.summary,
        keywords=enrichment_result.keywords,
        questions=enrichment_result.questions,
    )
    submit_kwargs = batch_orchestrator.submit_to_gemini.await_args.kwargs
    assert submit_kwargs["texts"][0] == expected_text
    assert submit_kwargs["texts"][1] == "chunk-1"
    assert chunks[0].enriched_text == expected_text
    assert chunks[0].enrichment_model == "gemini-2.5-flash"


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
            await handle_path_b(
                session,
                task,
                source,
                b"markdown-bytes",
                FileMetadata(page_count=None, duration_seconds=None, file_size_bytes=14),
                services,
            )

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
            await handle_path_b(
                session,
                task,
                source,
                b"markdown-bytes",
                FileMetadata(page_count=None, duration_seconds=None, file_size_bytes=14),
                services,
            )

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


@pytest.mark.asyncio
async def test_handle_path_b_reroutes_empty_scan_results_to_path_c(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(
        session_factory,
        source_type=SourceType.PDF,
        filename="scan.pdf",
        mime_type="application/pdf",
    )
    services = _services(chunk_count=0, document_ai_enabled=True)
    sentinel_result = object()
    handle_path_c = AsyncMock(return_value=sentinel_result)
    monkeypatch.setattr("app.workers.tasks.handlers.path_c.handle_path_c", handle_path_c)

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        result = await handle_path_b(
            session,
            task,
            source,
            b"pdf-bytes",
            FileMetadata(page_count=2, duration_seconds=None, file_size_bytes=14),
            services,
        )

    assert result is sentinel_result
    handle_path_c.assert_awaited_once()


def test_is_suspected_scan_returns_false_without_page_count() -> None:
    assert _is_suspected_scan(_chunk_data(1), page_count=None, min_chars_per_page=50) is False
    assert _is_suspected_scan(_chunk_data(1), page_count=0, min_chars_per_page=50) is False


def test_is_suspected_scan_respects_threshold_boundary() -> None:
    chunk_data = [
        ChunkData(
            text_content="a" * 50,
            token_count=10,
            chunk_index=0,
            anchor_page=1,
            anchor_chapter=None,
            anchor_section=None,
        )
    ]

    assert _is_suspected_scan(chunk_data, page_count=1, min_chars_per_page=50) is False
    assert _is_suspected_scan(chunk_data, page_count=2, min_chars_per_page=50) is True
