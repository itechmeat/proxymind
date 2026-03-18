from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import BackgroundTask, Source
from app.db.models.enums import BackgroundTaskStatus, BackgroundTaskType, SourceStatus, SourceType
from app.workers.tasks import ingestion


async def _seed_task(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_status: BackgroundTaskStatus = BackgroundTaskStatus.PENDING,
) -> tuple[uuid.UUID, uuid.UUID]:
    source_id = uuid.uuid7()
    task_id = uuid.uuid7()
    async with session_factory() as session:
        source = Source(
            id=source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            source_type=SourceType.MARKDOWN,
            title="Worker source",
            file_path=f"{DEFAULT_AGENT_ID}/{source_id}/doc.md",
            file_size_bytes=10,
            mime_type="text/markdown",
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


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_worker_processes_task_full_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, task_id = await _seed_task(session_factory)

    await ingestion.process_ingestion({"session_factory": session_factory}, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)

    assert task is not None
    assert source is not None
    assert task.status is BackgroundTaskStatus.COMPLETE
    assert task.progress == 100
    assert task.started_at is not None
    assert task.completed_at is not None
    assert source.status is SourceStatus.READY


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

    monkeypatch.setattr(ingestion, "_run_noop_ingestion", explode)

    await ingestion.process_ingestion({"session_factory": session_factory}, str(task_id))

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        source = await session.get(Source, source_id)

    assert task is not None
    assert source is not None
    assert task.status is BackgroundTaskStatus.FAILED
    assert task.error_message == "boom"
    assert source.status is SourceStatus.FAILED
