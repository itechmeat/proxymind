import asyncio

import asyncpg
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

router = APIRouter(tags=["health"])
HEALTH_CHECK_TIMEOUT_SECONDS = 3.0
HEALTH_CHECK_DEADLINE_SECONDS = 10.0


@router.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


async def _check_postgres(pool: asyncpg.Pool) -> None:
    async with asyncio.timeout(HEALTH_CHECK_TIMEOUT_SECONDS):
        async with pool.acquire() as connection:
            await connection.execute("SELECT 1")


async def _check_redis(client: Redis) -> None:
    async with asyncio.timeout(HEALTH_CHECK_TIMEOUT_SECONDS):
        await client.ping()


async def _check_http(client: httpx.AsyncClient, url: str) -> None:
    async with asyncio.timeout(HEALTH_CHECK_TIMEOUT_SECONDS):
        response = await client.get(url)
        response.raise_for_status()


@router.get("/ready", response_model=None)
async def readiness(request: Request) -> JSONResponse | dict[str, str]:
    settings = request.app.state.settings
    checks = {
        "postgres": _check_postgres(request.app.state.postgres_pool),
        "redis": _check_redis(request.app.state.redis_client),
        "qdrant": _check_http(request.app.state.http_client, f"{settings.qdrant_url}/readyz"),
        "minio": _check_http(
            request.app.state.http_client,
            f"{settings.minio_url}/minio/health/live",
        ),
    }
    try:
        async with asyncio.timeout(HEALTH_CHECK_DEADLINE_SECONDS):
            results = await asyncio.gather(
                *checks.values(),
                return_exceptions=True,
            )
    except TimeoutError:
        failed = list(checks)
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "failed": failed,
                "failures": {
                    name: {
                        "error_type": "TimeoutError",
                        "message": "Readiness check exceeded overall deadline",
                    }
                    for name in failed
                },
            },
        )

    failures = {
        name: {
            "error_type": type(result).__name__,
            "message": str(result) or "Health check failed",
        }
        for name, result in zip(checks, results, strict=True)
        if isinstance(result, Exception)
    }

    if failures:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "failed": list(failures),
                "failures": failures,
            },
        )

    return {"status": "ready"}
