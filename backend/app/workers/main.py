from __future__ import annotations

from typing import Any

import structlog
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.db import create_database_engine, create_session_factory
from app.workers.tasks import process_ingestion

settings = get_settings()
logger = structlog.get_logger(__name__)


async def on_startup(ctx: dict[str, Any]) -> None:
    logger.info("worker.startup.begin")
    engine = create_database_engine(settings)
    ctx["db_engine"] = engine
    ctx["session_factory"] = create_session_factory(engine)
    logger.info("worker.startup.complete")


async def on_shutdown(ctx: dict[str, Any]) -> None:
    engine = ctx.get("db_engine")
    logger.info("worker.shutdown.begin", has_engine=engine is not None)
    if engine is None:
        logger.info("worker.shutdown.complete", disposed=False)
        return

    try:
        await engine.dispose()
    except Exception:
        logger.exception("worker.shutdown.failed")
        raise

    logger.info("worker.shutdown.complete", disposed=True)


class WorkerSettings:
    functions = [process_ingestion]
    redis_settings = RedisSettings(host=settings.redis_host, port=settings.redis_port)
    max_jobs = 10
    job_timeout = 600
    retry_jobs = False
    on_startup = on_startup
    on_shutdown = on_shutdown
