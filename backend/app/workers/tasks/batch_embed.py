from __future__ import annotations

import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import BackgroundTask, BatchJob, Chunk
from app.db.models.enums import BackgroundTaskStatus, BatchStatus, ChunkStatus

logger = structlog.get_logger(__name__)


async def process_batch_embed(ctx: dict[str, object], task_id: str) -> None:
    session_factory = ctx["session_factory"]
    batch_orchestrator = ctx["batch_orchestrator"]
    if not isinstance(session_factory, async_sessionmaker):
        raise RuntimeError("Worker context is missing a valid session factory")

    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        logger.warning("worker.batch_embed.invalid_task_id", task_id=task_id)
        return

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_uuid)
        if task is None:
            logger.warning("worker.batch_embed.task_missing", task_id=task_id)
            return
        if task.status is not BackgroundTaskStatus.PENDING:
            logger.info(
                "worker.batch_embed.skip_non_pending_task",
                task_id=task_id,
                status=task.status.value,
            )
            return

        batch_job = await session.scalar(
            select(BatchJob).where(BatchJob.background_task_id == task.id).limit(1)
        )
        if batch_job is None:
            task.status = BackgroundTaskStatus.FAILED
            task.error_message = "Batch job not found"
            task.completed_at = datetime.now(UTC)
            await session.commit()
            return

        metadata = dict(batch_job.result_metadata or {})
        raw_chunk_ids = metadata.get("chunk_ids") or []
        if not raw_chunk_ids:
            task.status = BackgroundTaskStatus.FAILED
            task.error_message = "Batch job is missing stored chunk_ids"
            task.completed_at = datetime.now(UTC)
            batch_job.status = BatchStatus.FAILED
            batch_job.error_message = "Batch job is missing stored chunk_ids"
            batch_job.completed_at = datetime.now(UTC)
            await session.commit()
            return

        try:
            stored_chunk_ids = [uuid.UUID(raw_chunk_id) for raw_chunk_id in raw_chunk_ids]
        except ValueError:
            logger.warning(
                "worker.batch_embed.invalid_chunk_ids",
                task_id=task_id,
                raw_chunk_ids=raw_chunk_ids,
            )
            task.status = BackgroundTaskStatus.FAILED
            task.error_message = "Batch job contains malformed chunk_ids"
            task.completed_at = datetime.now(UTC)
            batch_job.status = BatchStatus.FAILED
            batch_job.error_message = "Batch job contains malformed chunk_ids"
            batch_job.completed_at = datetime.now(UTC)
            await session.commit()
            return

        chunks = (
            await session.scalars(
                select(Chunk)
                .where(Chunk.id.in_(stored_chunk_ids))
            )
        ).all()
        chunk_by_id = {chunk.id: chunk for chunk in chunks}
        ordered_chunks = [chunk_by_id.get(chunk_id) for chunk_id in stored_chunk_ids]
        if any(
            chunk is None or chunk.status is not ChunkStatus.PENDING
            for chunk in ordered_chunks
        ):
            task.status = BackgroundTaskStatus.FAILED
            task.error_message = "Stored batch chunk_ids are missing or no longer pending"
            task.completed_at = datetime.now(UTC)
            batch_job.status = BatchStatus.FAILED
            batch_job.error_message = "Stored batch chunk_ids are missing or no longer pending"
            batch_job.completed_at = datetime.now(UTC)
            await session.commit()
            return

        pending_chunks = [chunk for chunk in ordered_chunks if chunk is not None]
        task.status = BackgroundTaskStatus.PROCESSING
        await session.commit()
        try:
            await batch_orchestrator.submit_to_gemini(
                session,
                background_task_id=task.id,
                texts=[chunk.text_content for chunk in pending_chunks],
                chunk_ids=[chunk.id for chunk in pending_chunks],
                display_name=f"batch-embed-{task.id}",
            )
        except Exception as error:
            await session.rollback()
            task = await session.get(BackgroundTask, task.id)
            if task is not None:
                task.status = BackgroundTaskStatus.FAILED
                task.error_message = str(error) or type(error).__name__
                task.completed_at = datetime.now(UTC)
            await session.commit()
            raise
