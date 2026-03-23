from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.models.enums import BatchStatus
from app.workers.tasks import batch_poll
from app.workers.tasks.batch_poll import poll_active_batches


class _SessionContextManager:
    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _make_session_factory(session):
    return _SessionContextManager(session)


@pytest.mark.asyncio
async def test_poll_active_batches_continues_after_single_batch_failure() -> None:
    batch_job_ids = [
        uuid.uuid7(),
        uuid.uuid7(),
    ]
    batch_jobs = {
        batch_job_ids[0]: SimpleNamespace(id=batch_job_ids[0], status=BatchStatus.PROCESSING),
        batch_job_ids[1]: SimpleNamespace(id=batch_job_ids[1], status=BatchStatus.PROCESSING),
    }
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: batch_job_ids)),
        get=AsyncMock(side_effect=lambda _model, batch_job_id: batch_jobs.get(batch_job_id)),
        rollback=AsyncMock(),
    )

    def session_factory():
        return _make_session_factory(session)

    batch_orchestrator = SimpleNamespace(
        poll_and_complete=AsyncMock(side_effect=[RuntimeError("boom"), None])
    )

    original_async_sessionmaker = batch_poll.async_sessionmaker
    batch_poll.async_sessionmaker = object
    try:
        await poll_active_batches(
            {
                "session_factory": session_factory,
                "batch_orchestrator": batch_orchestrator,
            }
        )
    finally:
        batch_poll.async_sessionmaker = original_async_sessionmaker

    assert batch_orchestrator.poll_and_complete.await_count == 2
    assert session.get.await_count == 2
    session.rollback.assert_awaited_once()
