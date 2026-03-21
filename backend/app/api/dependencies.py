from __future__ import annotations

import uuid
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services import SnapshotService, SourceService, StorageService
from app.services.source import TaskEnqueuer


def get_storage_service(request: Request) -> StorageService:
    return request.app.state.storage_service


class ArqTaskEnqueuer(TaskEnqueuer):
    def __init__(self, arq_pool: ArqRedis) -> None:
        self._arq_pool = arq_pool

    async def enqueue_ingestion(self, task_id: uuid.UUID) -> str:
        job = await self._arq_pool.enqueue_job("process_ingestion", str(task_id))
        if job is None:
            raise RuntimeError("arq returned no job handle")
        return job.job_id


def get_task_enqueuer(request: Request) -> TaskEnqueuer:
    return ArqTaskEnqueuer(request.app.state.arq_pool)


def get_source_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    task_enqueuer: Annotated[TaskEnqueuer, Depends(get_task_enqueuer)],
) -> SourceService:
    return SourceService(session=session, task_enqueuer=task_enqueuer)


def get_snapshot_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SnapshotService:
    return SnapshotService(session=session)
