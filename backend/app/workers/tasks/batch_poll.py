from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import BatchJob
from app.db.models.enums import BatchStatus
from app.workers.observability import observe_background_job

logger = structlog.get_logger(__name__)


async def poll_active_batches(
    ctx: dict[str, object],
    *,
    correlation_id: str | None = None,
) -> None:
    session_factory = ctx["session_factory"]
    batch_orchestrator = ctx["batch_orchestrator"]
    worker_redis_client = ctx.get("worker_redis_client")
    if not isinstance(session_factory, async_sessionmaker):
        raise RuntimeError("Worker context is missing a valid session factory")

    async with observe_background_job(
        task_name="poll_active_batches",
        correlation_id=correlation_id,
        redis_client=worker_redis_client,
    ):
        async with session_factory() as session:
            batch_job_ids = (
                await session.scalars(
                    select(BatchJob.id).where(BatchJob.status == BatchStatus.PROCESSING)
                )
            ).all()
            for batch_job_id in batch_job_ids:
                try:
                    batch_job = await session.get(BatchJob, batch_job_id)
                    if batch_job is None or batch_job.status is not BatchStatus.PROCESSING:
                        continue
                    await batch_orchestrator.poll_and_complete(session, batch_job=batch_job)
                except Exception:
                    await session.rollback()
                    logger.exception(
                        "worker.batch_poll.failed",
                        batch_job_id=str(batch_job_id),
                    )
