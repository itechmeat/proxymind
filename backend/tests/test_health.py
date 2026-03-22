from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.api import health


def _session_factory(*, fail: Exception | None = None):
    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> bool:
            return False

        async def execute(self, statement: object) -> None:
            if fail is not None:
                raise fail

    return FakeSession


def _build_health_app(session_factory) -> FastAPI:
    app = FastAPI()
    app.include_router(health.router)
    app.state.settings = SimpleNamespace(
        qdrant_url="http://qdrant.invalid",
        seaweedfs_filer_url="http://seaweedfs.invalid",
    )
    app.state.session_factory = session_factory
    app.state.redis_client = object()
    app.state.http_client = object()
    return app


@pytest.mark.asyncio
async def test_health_returns_success_without_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("database check should not run for /health")

    monkeypatch.setattr(health, "_check_postgres", fail_if_called)

    transport = httpx.ASGITransport(app=_build_health_app(_session_factory()))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_returns_success_when_database_is_accessible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def noop(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(health, "_check_redis", noop)
    monkeypatch.setattr(health, "_check_http", noop)

    transport = httpx.ASGITransport(app=_build_health_app(_session_factory()))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_ready_returns_failure_when_database_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def noop(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(health, "_check_redis", noop)
    monkeypatch.setattr(health, "_check_http", noop)

    transport = httpx.ASGITransport(
        app=_build_health_app(_session_factory(fail=RuntimeError("database unavailable")))
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/ready")

    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "degraded"
    assert body["failed"] == ["postgres"]
    assert body["failures"]["postgres"]["error_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_ready_times_out_when_checks_hang(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health, "HEALTH_CHECK_DEADLINE_SECONDS", 0.05)

    async def slow(*args: object, **kwargs: object) -> None:
        await asyncio.sleep(health.HEALTH_CHECK_DEADLINE_SECONDS + 0.05)

    monkeypatch.setattr(health, "_check_redis", slow)
    monkeypatch.setattr(health, "_check_http", slow)

    transport = httpx.ASGITransport(app=_build_health_app(_session_factory()))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/ready")

    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "degraded"
    assert body["failed"] == ["postgres", "redis", "qdrant", "seaweedfs"]
    assert body["failures"]["redis"]["error_type"] == "TimeoutError"
