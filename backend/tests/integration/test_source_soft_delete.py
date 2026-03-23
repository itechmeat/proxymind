from __future__ import annotations

import uuid
from datetime import UTC, datetime
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
from app.services.source_delete import SourceDeleteService, SourceNotFoundError
from app.workers.tasks import ingestion


async def _create_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: SnapshotStatus,
    chunk_count: int = 0,
    knowledge_base_id: uuid.UUID = DEFAULT_KNOWLEDGE_BASE_ID,
    activated_at: datetime | None = None,
) -> uuid.UUID:
    snapshot_id = uuid.uuid7()
    async with session_factory() as session:
        snapshot = KnowledgeSnapshot(
            id=snapshot_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=knowledge_base_id,
            name=f"Snapshot {status.value}",
            status=status,
            chunk_count=chunk_count,
            published_at=datetime.now(UTC)
            if status in {SnapshotStatus.PUBLISHED, SnapshotStatus.ACTIVE}
            else None,
            activated_at=activated_at
            if status in {SnapshotStatus.PUBLISHED, SnapshotStatus.ACTIVE}
            else None,
        )
        session.add(snapshot)
        await session.commit()
    return snapshot_id


async def _create_source(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: SourceStatus = SourceStatus.READY,
    knowledge_base_id: uuid.UUID = DEFAULT_KNOWLEDGE_BASE_ID,
    deleted_at: datetime | None = None,
) -> uuid.UUID:
    source_id = uuid.uuid7()
    async with session_factory() as session:
        session.add(
            Source(
                id=source_id,
                agent_id=DEFAULT_AGENT_ID,
                knowledge_base_id=knowledge_base_id,
                source_type=SourceType.MARKDOWN,
                title="Soft delete source",
                file_path=f"{source_id}/source.md",
                status=status,
                deleted_at=deleted_at,
            )
        )
        await session.commit()
    return source_id


async def _create_doc_version(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_id: uuid.UUID,
) -> uuid.UUID:
    document_version_id = uuid.uuid7()
    async with session_factory() as session:
        document = Document(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            source_id=source_id,
            title="Source document",
            status=DocumentStatus.READY,
        )
        document_version = DocumentVersion(
            id=document_version_id,
            document_id=document.id,
            version_number=1,
            file_path=f"{source_id}/document-v1.md",
            processing_path=ProcessingPath.PATH_B,
            status=DocumentVersionStatus.READY,
        )
        session.add_all([document, document_version])
        await session.commit()
    return document_version_id


async def _create_chunk_in_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_id: uuid.UUID,
    document_version_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    chunk_index: int,
    knowledge_base_id: uuid.UUID = DEFAULT_KNOWLEDGE_BASE_ID,
    status: ChunkStatus = ChunkStatus.INDEXED,
) -> uuid.UUID:
    chunk_id = uuid.uuid7()
    async with session_factory() as session:
        session.add(
            Chunk(
                id=chunk_id,
                agent_id=DEFAULT_AGENT_ID,
                knowledge_base_id=knowledge_base_id,
                document_version_id=document_version_id,
                snapshot_id=snapshot_id,
                source_id=source_id,
                chunk_index=chunk_index,
                text_content=f"chunk {chunk_index}",
                status=status,
            )
        )
        await session.commit()
    return chunk_id


async def _create_ingestion_task(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_id: uuid.UUID,
) -> uuid.UUID:
    task_id = uuid.uuid7()
    async with session_factory() as session:
        session.add(
            BackgroundTask(
                id=task_id,
                agent_id=DEFAULT_AGENT_ID,
                task_type=BackgroundTaskType.INGESTION,
                status=BackgroundTaskStatus.PENDING,
                source_id=source_id,
            )
        )
        await session.commit()
    return task_id


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_soft_delete_removes_draft_chunks_and_decrements_snapshot_count(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_source(session_factory)
    document_version_id = await _create_doc_version(session_factory, source_id=source_id)
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        chunk_count=2,
    )
    chunk_ids = {
        await _create_chunk_in_snapshot(
            session_factory,
            source_id=source_id,
            document_version_id=document_version_id,
            snapshot_id=snapshot_id,
            chunk_index=0,
        ),
        await _create_chunk_in_snapshot(
            session_factory,
            source_id=source_id,
            document_version_id=document_version_id,
            snapshot_id=snapshot_id,
            chunk_index=1,
        ),
    }
    qdrant_service = SimpleNamespace(delete_chunks=AsyncMock())

    async with session_factory() as session:
        result = await SourceDeleteService(session, qdrant_service=qdrant_service).soft_delete(
            source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )

    assert result.source.status is SourceStatus.DELETED
    assert result.source.deleted_at is not None
    assert result.warnings == []
    deleted_chunk_ids = set(qdrant_service.delete_chunks.await_args.args[0])
    assert deleted_chunk_ids == chunk_ids

    async with session_factory() as session:
        remaining_chunks = (
            await session.scalars(select(Chunk).where(Chunk.source_id == source_id))
        ).all()
        snapshot = await session.get(KnowledgeSnapshot, snapshot_id)
        source = await session.get(Source, source_id)

    assert source is not None
    assert source.deleted_at is not None
    assert remaining_chunks == []
    assert snapshot is not None
    assert snapshot.chunk_count == 0


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_soft_delete_rolls_back_pg_mutations_when_qdrant_cleanup_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_source(session_factory)
    document_version_id = await _create_doc_version(session_factory, source_id=source_id)
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        chunk_count=1,
    )
    chunk_id = await _create_chunk_in_snapshot(
        session_factory,
        source_id=source_id,
        document_version_id=document_version_id,
        snapshot_id=snapshot_id,
        chunk_index=0,
    )
    qdrant_service = SimpleNamespace(
        delete_chunks=AsyncMock(side_effect=RuntimeError("qdrant down"))
    )

    async with session_factory() as session:
        service = SourceDeleteService(session, qdrant_service=qdrant_service)
        with pytest.raises(RuntimeError, match="qdrant down"):
            await service.soft_delete(
                source_id,
                agent_id=DEFAULT_AGENT_ID,
                knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            )
        await session.rollback()

    async with session_factory() as session:
        source = await session.get(Source, source_id)
        snapshot = await session.get(KnowledgeSnapshot, snapshot_id)
        remaining_chunks = (
            await session.scalars(select(Chunk).where(Chunk.source_id == source_id))
        ).all()

    assert source is not None
    assert source.status is SourceStatus.READY
    assert source.deleted_at is None
    assert snapshot is not None
    assert snapshot.chunk_count == 1
    assert {chunk.id for chunk in remaining_chunks} == {chunk_id}


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_soft_delete_preserves_published_chunks_and_returns_warning(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_source(session_factory)
    document_version_id = await _create_doc_version(session_factory, source_id=source_id)
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_count=1,
        activated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    await _create_chunk_in_snapshot(
        session_factory,
        source_id=source_id,
        document_version_id=document_version_id,
        snapshot_id=snapshot_id,
        chunk_index=0,
    )
    qdrant_service = SimpleNamespace(delete_chunks=AsyncMock())

    async with session_factory() as session:
        result = await SourceDeleteService(session, qdrant_service=qdrant_service).soft_delete(
            source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )

    assert result.warnings == [
        "Source is referenced in 1 published/active snapshot(s). "
        "Chunks will remain visible until a new snapshot replaces them."
    ]
    qdrant_service.delete_chunks.assert_not_awaited()

    async with session_factory() as session:
        remaining_chunks = (
            await session.scalars(select(Chunk).where(Chunk.source_id == source_id))
        ).all()
        snapshot = await session.get(KnowledgeSnapshot, snapshot_id)

    assert len(remaining_chunks) == 1
    assert snapshot is not None
    assert snapshot.chunk_count == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_soft_delete_cleans_draft_chunks_and_preserves_published_chunks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_source(session_factory)
    document_version_id = await _create_doc_version(session_factory, source_id=source_id)
    draft_snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        chunk_count=2,
    )
    published_snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_count=1,
        activated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    draft_chunk_ids = {
        await _create_chunk_in_snapshot(
            session_factory,
            source_id=source_id,
            document_version_id=document_version_id,
            snapshot_id=draft_snapshot_id,
            chunk_index=0,
        ),
        await _create_chunk_in_snapshot(
            session_factory,
            source_id=source_id,
            document_version_id=document_version_id,
            snapshot_id=draft_snapshot_id,
            chunk_index=1,
        ),
    }
    published_chunk_id = await _create_chunk_in_snapshot(
        session_factory,
        source_id=source_id,
        document_version_id=document_version_id,
        snapshot_id=published_snapshot_id,
        chunk_index=2,
    )
    qdrant_service = SimpleNamespace(delete_chunks=AsyncMock())

    async with session_factory() as session:
        result = await SourceDeleteService(session, qdrant_service=qdrant_service).soft_delete(
            source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )

    assert result.warnings == [
        "Source is referenced in 1 published/active snapshot(s). "
        "Chunks will remain visible until a new snapshot replaces them."
    ]
    deleted_chunk_ids = set(qdrant_service.delete_chunks.await_args.args[0])
    assert deleted_chunk_ids == draft_chunk_ids

    async with session_factory() as session:
        remaining_chunks = (
            await session.scalars(select(Chunk).where(Chunk.source_id == source_id))
        ).all()
        draft_snapshot = await session.get(KnowledgeSnapshot, draft_snapshot_id)
        published_snapshot = await session.get(KnowledgeSnapshot, published_snapshot_id)

    assert {chunk.id for chunk in remaining_chunks} == {published_chunk_id}
    assert draft_snapshot is not None
    assert draft_snapshot.chunk_count == 0
    assert published_snapshot is not None
    assert published_snapshot.chunk_count == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_soft_delete_is_idempotent_for_already_deleted_source(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    deleted_at = datetime(2026, 1, 1, tzinfo=UTC)
    source_id = await _create_source(
        session_factory,
        status=SourceStatus.DELETED,
        deleted_at=deleted_at,
    )
    qdrant_service = SimpleNamespace(delete_chunks=AsyncMock())

    async with session_factory() as session:
        result = await SourceDeleteService(session, qdrant_service=qdrant_service).soft_delete(
            source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )

    assert result.warnings == []
    assert result.source.deleted_at == deleted_at
    qdrant_service.delete_chunks.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_soft_delete_sets_status_and_deleted_at_together(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_source(session_factory)
    qdrant_service = SimpleNamespace(delete_chunks=AsyncMock())

    async with session_factory() as session:
        result = await SourceDeleteService(session, qdrant_service=qdrant_service).soft_delete(
            source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )

    assert result.source.status is SourceStatus.DELETED
    assert result.source.deleted_at is not None


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_soft_delete_not_found_raises_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = SourceDeleteService(session, qdrant_service=None)
        with pytest.raises(SourceNotFoundError, match="Source not found"):
            await service.soft_delete(
                uuid.uuid4(),
                agent_id=DEFAULT_AGENT_ID,
                knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            )


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_soft_delete_uses_scoped_lookup(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_source(session_factory, knowledge_base_id=uuid.uuid7())

    async with session_factory() as session:
        service = SourceDeleteService(session, qdrant_service=None)
        with pytest.raises(SourceNotFoundError, match="Source not found"):
            await service.soft_delete(
                source_id,
                agent_id=DEFAULT_AGENT_ID,
                knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            )


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_delete_source_endpoint_returns_200(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_source(session_factory)

    response = await api_client.delete(f"/api/admin/sources/{source_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(source_id)
    assert body["title"] == "Soft delete source"
    assert body["source_type"] == "markdown"
    assert body["status"] == "deleted"
    assert body["deleted_at"] is not None
    assert body["warnings"] == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_delete_source_endpoint_returns_404(api_client) -> None:
    response = await api_client.delete(f"/api/admin/sources/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Source not found"


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_delete_source_endpoint_is_idempotent_for_deleted_source(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_source(
        session_factory,
        status=SourceStatus.DELETED,
        deleted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    response = await api_client.delete(f"/api/admin/sources/{source_id}")

    assert response.status_code == 200
    assert response.json()["warnings"] == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_ingestion_rejects_deleted_source_without_loading_services(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = await _create_source(
        session_factory,
        status=SourceStatus.DELETED,
        deleted_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    task_id = await _create_ingestion_task(session_factory, source_id=source_id)

    def _fail_if_called(_ctx):
        raise AssertionError("_load_pipeline_services should not be called for deleted sources")

    monkeypatch.setattr(ingestion, "_load_pipeline_services", _fail_if_called)

    await ingestion.process_ingestion({"session_factory": session_factory}, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)

    assert task is not None
    assert task.status is BackgroundTaskStatus.FAILED
    assert task.error_message == "Source was deleted before processing completed"
    assert task.completed_at is not None
    assert source is not None
    assert source.status is SourceStatus.DELETED


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_ingestion_non_deleted_source_passes_guard_and_loads_services(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_id = await _create_source(session_factory, status=SourceStatus.PENDING)
    task_id = await _create_ingestion_task(session_factory, source_id=source_id)
    load_called = False
    run_pipeline = AsyncMock(return_value=None)

    def _load_services(_ctx):
        nonlocal load_called
        load_called = True
        return SimpleNamespace()

    monkeypatch.setattr(ingestion, "_load_pipeline_services", _load_services)
    monkeypatch.setattr(ingestion, "_run_ingestion_pipeline", run_pipeline)

    await ingestion.process_ingestion({"session_factory": session_factory}, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)

    assert load_called is True
    run_pipeline.assert_awaited_once()
    assert task is not None
    assert task.status is BackgroundTaskStatus.PROCESSING
    assert source is not None
    assert source.status is SourceStatus.PROCESSING
