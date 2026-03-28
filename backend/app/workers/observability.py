from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import structlog
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from redis.asyncio import Redis

from app.core.logging import bind_request_context, clear_request_context
from app.services.metrics import ARQ_QUEUE_DEPTH, BACKGROUND_JOB_COUNT, BACKGROUND_JOB_DURATION

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)
_ARQ_QUEUE_NAME = "arq:queue"


async def update_queue_depth(redis_client: Redis | None) -> None:
    if redis_client is None:
        return
    try:
        ARQ_QUEUE_DEPTH.set(await redis_client.zcard(_ARQ_QUEUE_NAME))
    except Exception as error:
        logger.warning(
            "worker.queue_depth_probe_failed",
            error=error.__class__.__name__,
        )


async def probe_queue_depth(ctx: dict[str, object]) -> None:
    await update_queue_depth(ctx.get("worker_redis_client"))


@asynccontextmanager
async def observe_background_job(
    *,
    task_name: str,
    correlation_id: str | None,
    redis_client: Redis | None,
) -> AsyncIterator[str]:
    resolved_request_id = correlation_id or str(uuid.uuid4())
    bind_request_context(
        request_id=resolved_request_id,
        worker_task=task_name,
    )
    await update_queue_depth(redis_client)
    started_at = time.perf_counter()
    with tracer.start_as_current_span(f"worker.{task_name}") as span:
        span.set_attribute("background.task.name", task_name)
        span.set_attribute("correlation_id", resolved_request_id)
        span.set_attribute("request_id", resolved_request_id)
        try:
            yield resolved_request_id
        except Exception as error:
            duration_seconds = time.perf_counter() - started_at
            BACKGROUND_JOB_COUNT.labels(task_name=task_name, status="failed").inc()
            BACKGROUND_JOB_DURATION.labels(task_name=task_name, status="failed").observe(
                duration_seconds
            )
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, str(error)))
            raise
        else:
            duration_seconds = time.perf_counter() - started_at
            BACKGROUND_JOB_COUNT.labels(task_name=task_name, status="complete").inc()
            BACKGROUND_JOB_DURATION.labels(task_name=task_name, status="complete").observe(
                duration_seconds
            )
        finally:
            await update_queue_depth(redis_client)
            clear_request_context()
