from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BackgroundTask, Source
from app.db.models.enums import BackgroundTaskStatus, SourceStatus

logger = structlog.get_logger(__name__)


async def _run_noop_ingestion(task: BackgroundTask, source: Source | None) -> None:
    # TODO(S2-02): Replace this noop with the real Docling pipeline:
    # download the source from MinIO, choose the processing path, parse and chunk
    # content, create embeddings, and upsert the final payload into Qdrant.
    task.result_metadata = {"message": "Noop ingestion completed"}
    if source is not None:
        source.status = SourceStatus.READY


async def process_ingestion(ctx: dict[str, Any], task_id: str) -> None:
    session_factory = ctx["session_factory"]
    if not isinstance(session_factory, async_sessionmaker):
        raise RuntimeError("Worker context is missing a valid session factory")

    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        logger.warning("worker.ingestion.invalid_task_id", task_id=task_id)
        return

    async with session_factory() as session:
        await _process_task(session, task_uuid)


async def _process_task(session: AsyncSession, task_id: uuid.UUID) -> None:
    task = await session.get(BackgroundTask, task_id)
    if task is None:
        logger.warning("worker.ingestion.task_missing", task_id=str(task_id))
        return

    if task.status is not BackgroundTaskStatus.PENDING:
        logger.warning(
            "worker.ingestion.task_skipped",
            task_id=str(task_id),
            status=task.status.value,
        )
        return

    source = await session.get(Source, task.source_id) if task.source_id else None

    try:
        task.status = BackgroundTaskStatus.PROCESSING
        task.progress = 0
        task.started_at = datetime.now(UTC)
        if source is not None:
            source.status = SourceStatus.PROCESSING
        await session.commit()

        await _run_noop_ingestion(task, source)

        task.status = BackgroundTaskStatus.COMPLETE
        task.progress = 100
        task.completed_at = datetime.now(UTC)
        await session.commit()
    except Exception as error:
        await session.rollback()
        failed_task = await session.get(BackgroundTask, task_id)
        if failed_task is None:
            logger.error("worker.ingestion.fail_fast_task_missing", task_id=str(task_id))
            return

        failed_task.status = BackgroundTaskStatus.FAILED
        failed_task.error_message = str(error) or type(error).__name__
        failed_task.completed_at = datetime.now(UTC)
        if failed_task.source_id is not None:
            failed_source = await session.get(Source, failed_task.source_id)
            if failed_source is not None:
                failed_source.status = SourceStatus.FAILED

        # TODO(S7-04): Add stale PROCESSING task detection and recovery for worker crashes.
        await session.commit()
        logger.exception("worker.ingestion.failed", task_id=str(task_id))
