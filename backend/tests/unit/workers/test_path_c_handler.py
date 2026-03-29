from __future__ import annotations

# pyright: reportArgumentType=false

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import BackgroundTask, Source
from app.db.models.enums import BackgroundTaskStatus, BackgroundTaskType, SourceStatus, SourceType
from app.services.document_processing import ChunkData
from app.services.enrichment import EnrichmentResult, build_enriched_text
from app.services.path_router import FileMetadata
from app.services.snapshot import SnapshotService
from app.workers.tasks.handlers.path_c import PathCResult, handle_path_c
from app.workers.tasks.pipeline import PipelineServices


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
            source_type=SourceType.PDF,
            title="Path C source",
            file_path=f"{DEFAULT_AGENT_ID}/{source_id}/scan.pdf",
            file_size_bytes=256,
            mime_type="application/pdf",
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
    enrichment_service: object | None = None,
    batch_orchestrator: object | None = None,
) -> PipelineServices:
    chunk_data = [
        ChunkData(
            text_content="path-c-chunk",
            token_count=8,
            chunk_index=0,
            anchor_page=1,
            anchor_chapter="Chapter",
            anchor_section="Section",
        )
    ]
    return PipelineServices(  # type: ignore[arg-type]
        storage_service=SimpleNamespace(download=AsyncMock()),
        document_processor=SimpleNamespace(parse_and_chunk=AsyncMock()),
        document_ai_parser=SimpleNamespace(parse_and_chunk=AsyncMock(return_value=chunk_data)),
        embedding_service=SimpleNamespace(
            model="gemini-embedding-2-preview",
            dimensions=3,
            embed_texts=AsyncMock(return_value=[[0.1, 0.2, 0.3]]),
        ),
        qdrant_service=SimpleNamespace(upsert_chunks=AsyncMock(), delete_chunks=AsyncMock()),
        snapshot_service=SnapshotService(),
        gemini_content_service=SimpleNamespace(extract_text_content=AsyncMock()),
        tokenizer=SimpleNamespace(count_tokens=lambda _text: 1),
        settings=SimpleNamespace(batch_embed_chunk_threshold=50, embedding_task_type="RETRIEVAL_DOCUMENT"),
        default_language="english",
        path_a_text_threshold_pdf=2000,
        path_a_text_threshold_media=500,
        path_a_max_pdf_pages=6,
        path_a_max_audio_duration_sec=80,
        path_a_max_video_duration_sec=120,
        path_c_min_chars_per_page=50,
        document_ai_enabled=True,
        batch_orchestrator=batch_orchestrator,
        enrichment_service=enrichment_service,
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_handle_path_c_uses_enriched_text_for_embedding(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_source_and_task(session_factory)
    enrichment_result = EnrichmentResult(
        summary="Summary for path c.",
        keywords=["ocr", "scan"],
        questions=["What is in the scanned document?"],
    )
    enrichment_service = SimpleNamespace(
        model="gemini-2.5-flash",
        enrich=AsyncMock(return_value=[enrichment_result]),
    )
    services = _services(enrichment_service=enrichment_service)

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        task = await session.get(BackgroundTask, task_id)
        assert source is not None
        assert task is not None

        result = await handle_path_c(
            session,
            task,
            source,
            b"pdf-bytes",
            FileMetadata(page_count=1, duration_seconds=None, file_size_bytes=100),
            services,
        )

    assert isinstance(result, PathCResult)
    expected_text = build_enriched_text(
        text_content="path-c-chunk",
        summary=enrichment_result.summary,
        keywords=enrichment_result.keywords,
        questions=enrichment_result.questions,
    )
    services.embedding_service.embed_texts.assert_awaited_once_with(  # type: ignore[attr-defined]
        [expected_text],
        task_type="RETRIEVAL_DOCUMENT",
        title="Path C source",
    )
    qdrant_points = services.qdrant_service.upsert_chunks.await_args.args[0]  # type: ignore[attr-defined]
    assert qdrant_points[0].enriched_text == expected_text
    assert qdrant_points[0].enriched_keywords == ["ocr", "scan"]
