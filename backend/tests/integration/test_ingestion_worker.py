from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import (
    BackgroundTask,
    Chunk,
    Document,
    DocumentVersion,
    EmbeddingProfile,
    KnowledgeSnapshot,
    Source,
)
from app.db.models.enums import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    ChunkStatus,
    DocumentStatus,
    DocumentVersionStatus,
    ProcessingPath,
    SnapshotStatus,
    SourceStatus,
    SourceType,
)
from app.services.docling_parser import ChunkData, DoclingParser
from app.services.snapshot import SnapshotService
from app.workers.tasks import ingestion

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _fixture_bytes(name: str) -> bytes:
    return (FIXTURES_DIR / name).read_bytes()


async def _seed_task(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_status: BackgroundTaskStatus = BackgroundTaskStatus.PENDING,
    source_type: SourceType = SourceType.MARKDOWN,
    filename: str = "doc.md",
    file_size_bytes: int = 10,
    mime_type: str = "text/markdown",
    title: str = "Worker source",
) -> tuple[uuid.UUID, uuid.UUID]:
    source_id = uuid.uuid7()
    task_id = uuid.uuid7()
    async with session_factory() as session:
        source = Source(
            id=source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            source_type=source_type,
            title=title,
            file_path=f"{DEFAULT_AGENT_ID}/{source_id}/{filename}",
            file_size_bytes=file_size_bytes,
            mime_type=mime_type,
            status=SourceStatus.PENDING,
        )
        task = BackgroundTask(
            id=task_id,
            agent_id=DEFAULT_AGENT_ID,
            task_type=BackgroundTaskType.INGESTION,
            status=task_status,
            source_id=source_id,
        )
        session.add_all([source, task])
        await session.commit()
    return source_id, task_id


def _worker_context(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    chunk_data: list[ChunkData] | None = None,
    embedding_side_effect: object | None = None,
) -> dict[str, object]:
    if chunk_data is None:
        chunk_data = [
            ChunkData(
                text_content="ProxyMind is searchable.",
                token_count=4,
                chunk_index=0,
                anchor_page=None,
                anchor_chapter="Intro",
                anchor_section="Overview",
            ),
            ChunkData(
                text_content="Chunks should be indexed in Qdrant.",
                token_count=6,
                chunk_index=1,
                anchor_page=None,
                anchor_chapter="Intro",
                anchor_section="Indexing",
            ),
        ]

    embedding_service = SimpleNamespace(
        model="gemini-embedding-2-preview",
        dimensions=3,
        embed_texts=(
            AsyncMock(side_effect=embedding_side_effect)
            if embedding_side_effect is not None
            else AsyncMock(return_value=[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        ),
        embed_file=AsyncMock(return_value=[0.1, 0.2, 0.3]),
    )
    return {
        "session_factory": session_factory,
        "settings": SimpleNamespace(bm25_language="english"),
        "path_a_text_threshold_pdf": 2000,
        "path_a_text_threshold_media": 500,
        "path_a_max_pdf_pages": 6,
        "path_a_max_audio_duration_sec": 80,
        "path_a_max_video_duration_sec": 120,
        "storage_service": SimpleNamespace(download=AsyncMock(return_value=b"# ProxyMind")),
        "docling_parser": SimpleNamespace(parse_and_chunk=AsyncMock(return_value=chunk_data)),
        "embedding_service": embedding_service,
        "gemini_content_service": SimpleNamespace(extract_text_content=AsyncMock()),
        "tokenizer": SimpleNamespace(count_tokens=lambda text: len(str(text).split())),
        "qdrant_service": SimpleNamespace(
            upsert_chunks=AsyncMock(),
            delete_chunks=AsyncMock(),
        ),
        "snapshot_service": SnapshotService(),
    }


def _real_parser_worker_context(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    file_bytes: bytes,
) -> dict[str, object]:
    embedding_service = SimpleNamespace(
        model="gemini-embedding-2-preview",
        dimensions=3,
        embed_texts=AsyncMock(
            side_effect=lambda texts, **kwargs: [[0.1, 0.2, 0.3] for _ in texts]
        ),
        embed_file=AsyncMock(return_value=[0.1, 0.2, 0.3]),
    )
    return {
        "session_factory": session_factory,
        "settings": SimpleNamespace(bm25_language="english"),
        "path_a_text_threshold_pdf": 2000,
        "path_a_text_threshold_media": 500,
        "path_a_max_pdf_pages": 6,
        "path_a_max_audio_duration_sec": 80,
        "path_a_max_video_duration_sec": 120,
        "storage_service": SimpleNamespace(download=AsyncMock(return_value=file_bytes)),
        "docling_parser": DoclingParser(chunk_max_tokens=1024),
        "embedding_service": embedding_service,
        "gemini_content_service": SimpleNamespace(extract_text_content=AsyncMock()),
        "tokenizer": SimpleNamespace(count_tokens=lambda text: len(str(text).split())),
        "qdrant_service": SimpleNamespace(
            upsert_chunks=AsyncMock(),
            delete_chunks=AsyncMock(),
        ),
        "snapshot_service": SnapshotService(),
    }


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_processes_task_full_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_task(session_factory)
    worker_ctx = _worker_context(session_factory)

    await ingestion.process_ingestion(worker_ctx, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)
        documents = (await session.scalars(select(Document))).all()
        versions = (await session.scalars(select(DocumentVersion))).all()
        chunks = (await session.scalars(select(Chunk).order_by(Chunk.chunk_index.asc()))).all()
        snapshots = (await session.scalars(select(KnowledgeSnapshot))).all()
        embedding_profiles = (await session.scalars(select(EmbeddingProfile))).all()

    assert task is not None
    assert source is not None
    assert task.status is BackgroundTaskStatus.COMPLETE
    assert task.progress == 100
    assert task.started_at is not None
    assert task.completed_at is not None
    assert task.result_metadata is not None
    assert task.result_metadata["chunk_count"] == 2
    assert task.result_metadata["processing_path"] == "path_b"
    assert source.status is SourceStatus.READY
    assert len(documents) == 1
    assert documents[0].status is DocumentStatus.READY
    assert len(versions) == 1
    assert versions[0].status is DocumentVersionStatus.READY
    assert versions[0].processing_path is ProcessingPath.PATH_B
    assert [chunk.status for chunk in chunks] == [ChunkStatus.INDEXED, ChunkStatus.INDEXED]
    assert len(snapshots) == 1
    assert snapshots[0].status is SnapshotStatus.DRAFT
    assert snapshots[0].chunk_count == 2
    assert len(embedding_profiles) == 1
    worker_ctx["qdrant_service"].upsert_chunks.assert_awaited_once()  # type: ignore[attr-defined]
    qdrant_points = worker_ctx["qdrant_service"].upsert_chunks.await_args.args[0]  # type: ignore[attr-defined]
    assert all(point.language == "english" for point in qdrant_points)


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_processes_html_with_real_docling_parser(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_task(
        session_factory,
        source_type=SourceType.HTML,
        filename="sample.html",
        file_size_bytes=len(_fixture_bytes("sample.html")),
        mime_type="text/html",
        title="HTML source",
    )
    worker_ctx = _real_parser_worker_context(
        session_factory,
        file_bytes=_fixture_bytes("sample.html"),
    )

    await ingestion.process_ingestion(worker_ctx, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)
        chunks = (await session.scalars(select(Chunk).order_by(Chunk.chunk_index.asc()))).all()
        document = await session.scalar(select(Document))
        document_version = await session.scalar(select(DocumentVersion))

    assert task is not None
    assert source is not None
    assert document is not None
    assert document_version is not None
    assert task.status is BackgroundTaskStatus.COMPLETE
    assert task.result_metadata is not None
    assert task.result_metadata["chunk_count"] > 0
    assert source.status is SourceStatus.READY
    assert document.status is DocumentStatus.READY
    assert document_version.status is DocumentVersionStatus.READY
    assert chunks
    assert all(chunk.status is ChunkStatus.INDEXED for chunk in chunks)
    worker_ctx["embedding_service"].embed_texts.assert_awaited_once()  # type: ignore[attr-defined]
    worker_ctx["qdrant_service"].upsert_chunks.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_marks_corrupt_pdf_failed_with_real_docling_parser(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_task(
        session_factory,
        source_type=SourceType.PDF,
        filename="corrupt.pdf",
        file_size_bytes=len(b"not-a-real-pdf"),
        mime_type="application/pdf",
        title="Corrupt PDF source",
    )
    worker_ctx = _real_parser_worker_context(
        session_factory,
        file_bytes=b"not-a-real-pdf",
    )

    await ingestion.process_ingestion(worker_ctx, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)
        document = await session.scalar(select(Document))
        document_version = await session.scalar(select(DocumentVersion))
        chunks = (await session.scalars(select(Chunk))).all()

    assert task is not None
    assert source is not None
    assert task.status is BackgroundTaskStatus.FAILED
    assert task.error_message
    assert source.status is SourceStatus.FAILED
    assert document is None
    assert document_version is None
    assert chunks == []
    worker_ctx["embedding_service"].embed_texts.assert_not_awaited()  # type: ignore[attr-defined]
    worker_ctx["qdrant_service"].upsert_chunks.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_reuses_draft_and_accumulates_chunk_count(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, first_task_id = await _seed_task(session_factory)
    _, second_task_id = await _seed_task(session_factory)
    worker_ctx = _worker_context(session_factory)

    await ingestion.process_ingestion(worker_ctx, str(first_task_id))
    await ingestion.process_ingestion(worker_ctx, str(second_task_id))

    async with session_factory() as session:
        snapshots = (await session.scalars(select(KnowledgeSnapshot))).all()

    assert len(snapshots) == 1
    assert snapshots[0].status is SnapshotStatus.DRAFT
    assert snapshots[0].chunk_count == 4
    assert worker_ctx["qdrant_service"].upsert_chunks.await_count == 2  # type: ignore[attr-defined]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_rebinds_to_new_draft_when_snapshot_was_published(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, task_id = await _seed_task(session_factory)

    async with session_factory() as session:
        seeded_snapshot = KnowledgeSnapshot(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            name="Original draft",
            status=SnapshotStatus.DRAFT,
        )
        session.add(seeded_snapshot)
        await session.commit()

    class PublishingSnapshotService(SnapshotService):
        def __init__(self) -> None:
            super().__init__()
            self._published = False

        async def get_or_create_draft(self, session, *, agent_id, knowledge_base_id):
            snapshot = await session.get(KnowledgeSnapshot, seeded_snapshot.id)
            assert snapshot is not None
            if snapshot.status is SnapshotStatus.DRAFT:
                return snapshot
            return await super().get_or_create_draft(
                session,
                agent_id=agent_id,
                knowledge_base_id=knowledge_base_id,
            )

        async def ensure_draft_or_rebind(
            self, session, *, snapshot_id, agent_id, knowledge_base_id
        ):
            if not self._published:
                self._published = True
                async with session_factory() as publish_session:
                    published_snapshot = await publish_session.get(
                        KnowledgeSnapshot, seeded_snapshot.id
                    )
                    assert published_snapshot is not None
                    published_snapshot.status = SnapshotStatus.PUBLISHED
                    await publish_session.commit()

            return await super().ensure_draft_or_rebind(
                session,
                snapshot_id=snapshot_id,
                agent_id=agent_id,
                knowledge_base_id=knowledge_base_id,
            )

    worker_ctx = _worker_context(session_factory)
    worker_ctx["snapshot_service"] = PublishingSnapshotService()

    await ingestion.process_ingestion(worker_ctx, str(task_id))

    async with session_factory() as session:
        snapshots = (
            await session.scalars(
                select(KnowledgeSnapshot).order_by(KnowledgeSnapshot.created_at.asc())
            )
        ).all()
        chunks = (
            await session.scalars(select(Chunk).order_by(Chunk.created_at.asc()))
        ).all()

    assert len(snapshots) == 2
    assert snapshots[0].id == seeded_snapshot.id
    assert snapshots[0].status is SnapshotStatus.PUBLISHED
    assert snapshots[0].chunk_count == 0
    assert snapshots[1].status is SnapshotStatus.DRAFT
    assert snapshots[1].chunk_count == 2
    assert chunks
    assert all(chunk.snapshot_id == snapshots[1].id for chunk in chunks)


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_skips_non_pending_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_task(
        session_factory,
        task_status=BackgroundTaskStatus.COMPLETE,
    )

    await ingestion.process_ingestion({"session_factory": session_factory}, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)

    assert task is not None
    assert source is not None
    assert task.status is BackgroundTaskStatus.COMPLETE
    assert task.started_at is None
    assert source.status is SourceStatus.PENDING


@pytest.mark.asyncio
async def test_worker_handles_missing_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await ingestion.process_ingestion({"session_factory": session_factory}, str(uuid.uuid7()))


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_marks_failed_on_unhandled_exception(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_task(session_factory)

    async def explode(*args, **kwargs) -> None:
        raise RuntimeError("boom")

    worker_ctx = _worker_context(session_factory, embedding_side_effect=explode)

    await ingestion.process_ingestion(worker_ctx, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)
        document = await session.scalar(select(Document))
        document_version = await session.scalar(select(DocumentVersion))
        chunks = (await session.scalars(select(Chunk))).all()

    assert task is not None
    assert source is not None
    assert task.status is BackgroundTaskStatus.FAILED
    assert task.error_message == "boom"
    assert source.status is SourceStatus.FAILED
    assert document is not None
    assert document.status is DocumentStatus.FAILED
    assert document_version is not None
    assert document_version.status is DocumentVersionStatus.FAILED
    assert chunks
    assert all(chunk.status is ChunkStatus.FAILED for chunk in chunks)
    worker_ctx["qdrant_service"].upsert_chunks.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_attempts_qdrant_cleanup_when_upsert_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_task(session_factory)
    worker_ctx = _worker_context(session_factory)
    worker_ctx["qdrant_service"].upsert_chunks = AsyncMock(
        side_effect=RuntimeError("qdrant timeout")
    )  # type: ignore[index]

    await ingestion.process_ingestion(worker_ctx, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)
        chunks = (await session.scalars(select(Chunk))).all()

    assert task is not None
    assert source is not None
    assert task.status is BackgroundTaskStatus.FAILED
    assert task.error_message == "qdrant timeout"
    assert source.status is SourceStatus.FAILED
    assert chunks
    assert all(chunk.status is ChunkStatus.FAILED for chunk in chunks)
    worker_ctx["qdrant_service"].delete_chunks.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_deletes_qdrant_points_when_finalization_fails(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_task(session_factory)
    worker_ctx = _worker_context(session_factory)

    async def explode(**kwargs) -> None:
        raise RuntimeError("finalize failed")

    monkeypatch.setattr(ingestion, "_finalize_pipeline_success", explode)

    await ingestion.process_ingestion(worker_ctx, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)
        chunks = (await session.scalars(select(Chunk))).all()

    assert task is not None
    assert source is not None
    assert task.status is BackgroundTaskStatus.FAILED
    assert task.error_message == "finalize failed"
    assert source.status is SourceStatus.FAILED
    assert chunks
    assert all(chunk.status is ChunkStatus.FAILED for chunk in chunks)
    worker_ctx["qdrant_service"].upsert_chunks.assert_awaited_once()  # type: ignore[attr-defined]
    worker_ctx["qdrant_service"].delete_chunks.assert_awaited_once()  # type: ignore[attr-defined]
