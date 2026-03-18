from contextlib import asynccontextmanager

import asyncpg
import httpx
import structlog
from fastapi import FastAPI
from redis.asyncio import Redis

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger = structlog.get_logger(__name__)
    configure_logging(settings.log_level)
    app.state.settings = settings
    app.state.postgres_pool = await asyncpg.create_pool(
        user=settings.postgres_user,
        password=settings.postgres_password,
        database=settings.postgres_db,
        host=settings.postgres_host,
        port=settings.postgres_port,
        min_size=0,
    )
    app.state.redis_client = Redis.from_url(settings.redis_url)
    app.state.http_client = httpx.AsyncClient(timeout=5.0)
    logger.info("app.startup", log_level=settings.log_level)
    yield
    try:
        await app.state.http_client.aclose()
    except Exception as error:
        logger.error("app.shutdown.http_client_close_failed", error=str(error))

    try:
        await app.state.redis_client.aclose()
    except Exception as error:
        logger.error("app.shutdown.redis_client_close_failed", error=str(error))

    try:
        await app.state.postgres_pool.close()
    except Exception as error:
        logger.error("app.shutdown.postgres_pool_close_failed", error=str(error))

    logger.info("app.shutdown")


app = FastAPI(title="ProxyMind API", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
