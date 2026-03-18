from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI
from redis.asyncio import Redis

from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import create_database_engine, create_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger = structlog.get_logger(__name__)
    configure_logging(settings.log_level)
    db_engine = create_database_engine(settings)
    app.state.settings = settings
    app.state.db_engine = db_engine
    app.state.session_factory = create_session_factory(db_engine)
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
        await app.state.db_engine.dispose()
    except Exception as error:
        logger.error("app.shutdown.db_engine_dispose_failed", error=str(error))

    logger.info("app.shutdown")


app = FastAPI(title="ProxyMind API", version="0.1.0", lifespan=lifespan)
app.include_router(health_router)
