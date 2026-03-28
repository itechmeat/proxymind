from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.models.enums import BackgroundTaskStatus, BatchStatus, ChunkStatus
from app.workers.tasks import batch_embed
from app.workers.tasks.batch_embed import process_batch_embed


class _SessionContextManager:
    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_process_batch_embed_uses_stored_chunk_order() -> None:
    task_id = uuid.uuid7()
    first_chunk_id = uuid.uuid7()
    second_chunk_id = uuid.uuid7()
    task = SimpleNamespace(
        id=task_id,
        status=BackgroundTaskStatus.PENDING,
        result_metadata={"source_ids": []},
    )
    batch_job = SimpleNamespace(
        id=uuid.uuid7(),
        result_metadata={"chunk_ids": [str(second_chunk_id), str(first_chunk_id)]},
        status=BatchStatus.PENDING,
        error_message=None,
    )
    first_chunk = SimpleNamespace(
        id=first_chunk_id,
        text_content="first",
        status=ChunkStatus.PENDING,
    )
    second_chunk = SimpleNamespace(
        id=second_chunk_id,
        text_content="second",
        status=ChunkStatus.PENDING,
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=task),
        scalar=AsyncMock(return_value=batch_job),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [first_chunk, second_chunk])),
        commit=AsyncMock(),
    )
    batch_orchestrator = SimpleNamespace(submit_to_gemini=AsyncMock())

    original_async_sessionmaker = batch_embed.async_sessionmaker
    batch_embed.async_sessionmaker = object
    try:
        await process_batch_embed(
            {
                "session_factory": lambda: _SessionContextManager(session),
                "batch_orchestrator": batch_orchestrator,
            },
            str(task_id),
        )
    finally:
        batch_embed.async_sessionmaker = original_async_sessionmaker

    submit_call = batch_orchestrator.submit_to_gemini.await_args
    assert submit_call.kwargs["chunk_ids"] == [second_chunk_id, first_chunk_id]
    assert submit_call.kwargs["texts"] == ["second", "first"]


@pytest.mark.asyncio
async def test_process_batch_embed_fails_on_malformed_chunk_ids() -> None:
    task_id = uuid.uuid7()
    task = SimpleNamespace(
        id=task_id,
        status=BackgroundTaskStatus.PENDING,
        error_message=None,
        completed_at=None,
        result_metadata={"source_ids": []},
    )
    batch_job = SimpleNamespace(
        id=uuid.uuid7(),
        result_metadata={"chunk_ids": ["not-a-uuid"]},
        status=BatchStatus.PENDING,
        error_message=None,
        completed_at=None,
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=task),
        scalar=AsyncMock(return_value=batch_job),
        commit=AsyncMock(),
    )
    batch_orchestrator = SimpleNamespace(submit_to_gemini=AsyncMock())

    original_async_sessionmaker = batch_embed.async_sessionmaker
    batch_embed.async_sessionmaker = object
    try:
        await process_batch_embed(
            {
                "session_factory": lambda: _SessionContextManager(session),
                "batch_orchestrator": batch_orchestrator,
            },
            str(task_id),
        )
    finally:
        batch_embed.async_sessionmaker = original_async_sessionmaker

    assert task.status is BackgroundTaskStatus.FAILED
    assert task.error_message == "Batch job contains malformed chunk_ids"
    assert batch_job.status is BatchStatus.FAILED
    assert batch_job.error_message == "Batch job contains malformed chunk_ids"
    session.commit.assert_awaited_once()
    batch_orchestrator.submit_to_gemini.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_batch_embed_skips_non_pending_task() -> None:
    task_id = uuid.uuid7()
    task = SimpleNamespace(
        id=task_id,
        status=BackgroundTaskStatus.COMPLETE,
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=task),
    )
    batch_orchestrator = SimpleNamespace(submit_to_gemini=AsyncMock())

    original_async_sessionmaker = batch_embed.async_sessionmaker
    batch_embed.async_sessionmaker = object
    try:
        await process_batch_embed(
            {
                "session_factory": lambda: _SessionContextManager(session),
                "batch_orchestrator": batch_orchestrator,
            },
            str(task_id),
        )
    finally:
        batch_embed.async_sessionmaker = original_async_sessionmaker

    batch_orchestrator.submit_to_gemini.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_batch_embed_marks_task_failed_when_submit_raises() -> None:
    task_id = uuid.uuid7()
    chunk_id = uuid.uuid7()
    task = SimpleNamespace(
        id=task_id,
        status=BackgroundTaskStatus.PENDING,
        error_message=None,
        completed_at=None,
        result_metadata={"source_ids": []},
    )
    batch_job = SimpleNamespace(
        id=uuid.uuid7(),
        result_metadata={"chunk_ids": [str(chunk_id)]},
        status=BatchStatus.PENDING,
        error_message=None,
        completed_at=None,
    )
    chunk = SimpleNamespace(
        id=chunk_id,
        text_content="chunk",
        status=ChunkStatus.PENDING,
    )
    session = SimpleNamespace(
        get=AsyncMock(side_effect=[task, task, batch_job]),
        scalar=AsyncMock(return_value=batch_job),
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [chunk])),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    batch_orchestrator = SimpleNamespace(
        submit_to_gemini=AsyncMock(side_effect=RuntimeError("submit failed"))
    )

    original_async_sessionmaker = batch_embed.async_sessionmaker
    batch_embed.async_sessionmaker = object
    try:
        with pytest.raises(RuntimeError, match="submit failed"):
            await process_batch_embed(
                {
                    "session_factory": lambda: _SessionContextManager(session),
                    "batch_orchestrator": batch_orchestrator,
                },
                str(task_id),
            )
    finally:
        batch_embed.async_sessionmaker = original_async_sessionmaker

    assert task.status is BackgroundTaskStatus.FAILED
    assert task.error_message == "submit failed"
    assert batch_job.status is BatchStatus.FAILED
    assert batch_job.error_message == "submit failed"
    session.rollback.assert_awaited_once()
    assert session.commit.await_count == 2
