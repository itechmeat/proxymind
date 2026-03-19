from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SourceUploadMetadata
from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import BackgroundTask, Source
from app.db.models.enums import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    SourceStatus,
    SourceType,
)


class TaskEnqueuer(Protocol):
    async def enqueue_ingestion(self, task_id: uuid.UUID) -> str: ...


class SourcePersistenceError(RuntimeError):
    pass


class TaskEnqueueError(RuntimeError):
    pass


@dataclass(slots=True)
class SourceTaskBundle:
    source: Source
    task: BackgroundTask


class SourceService:
    def __init__(self, session: AsyncSession, task_enqueuer: TaskEnqueuer) -> None:
        self._session = session
        self._task_enqueuer = task_enqueuer

    async def create_source_and_task(
        self,
        *,
        source_id: uuid.UUID,
        metadata: SourceUploadMetadata,
        source_type: SourceType,
        file_path: str,
        file_size_bytes: int,
        mime_type: str | None,
    ) -> SourceTaskBundle:
        source = Source(
            id=source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            source_type=source_type,
            title=metadata.title,
            description=metadata.description,
            public_url=str(metadata.public_url) if metadata.public_url else None,
            file_path=file_path,
            file_size_bytes=file_size_bytes,
            mime_type=mime_type,
            language=metadata.language,
            catalog_item_id=metadata.catalog_item_id,
            status=SourceStatus.PENDING,
        )
        task = BackgroundTask(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            task_type=BackgroundTaskType.INGESTION,
            status=BackgroundTaskStatus.PENDING,
            source_id=source_id,
        )
        self._session.add_all([source, task])

        try:
            await self._session.commit()
        except Exception as error:
            await self._session.rollback()
            raise SourcePersistenceError("Failed to persist source and task") from error

        try:
            task.arq_job_id = await self._task_enqueuer.enqueue_ingestion(task.id)
            await self._session.commit()
        except Exception as error:
            await self._session.rollback()
            persisted_source = await self._session.get(Source, source_id)
            persisted_task = await self._session.get(BackgroundTask, task.id)
            if persisted_source is None or persisted_task is None:
                raise TaskEnqueueError(
                    "Failed to recover source/task after enqueue error"
                ) from error

            persisted_source.status = SourceStatus.FAILED
            persisted_task.status = BackgroundTaskStatus.FAILED
            persisted_task.error_message = f"Failed to enqueue ingestion task: {error}"
            persisted_task.completed_at = datetime.now(UTC)
            await self._session.commit()
            raise TaskEnqueueError("Failed to enqueue ingestion task") from error

        return SourceTaskBundle(source=source, task=task)

    async def get_task(self, task_id: uuid.UUID) -> BackgroundTask | None:
        return await self._session.get(BackgroundTask, task_id)
