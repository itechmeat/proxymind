from __future__ import annotations

import secrets
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, Depends, FastAPI
from structlog.testing import capture_logs

from app.api.auth import verify_admin_key

TEST_API_KEY = "test-admin-key-abc123"


def _make_app(admin_api_key: str | None) -> FastAPI:
    router = APIRouter(prefix="/api/admin", dependencies=[Depends(verify_admin_key)])

    @router.get("/test")
    async def admin_test() -> dict[str, bool]:
        return {"ok": True}

    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(admin_api_key=admin_api_key)
    return app


@pytest_asyncio.fixture
async def client_with_key() -> httpx.AsyncClient:
    app = _make_app(TEST_API_KEY)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture
async def client_no_key() -> httpx.AsyncClient:
    app = _make_app(None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_valid_key_returns_200(client_with_key: httpx.AsyncClient) -> None:
    response = await client_with_key.get(
        "/api/admin/test",
        headers={"Authorization": f"Bearer {TEST_API_KEY}"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_missing_key_returns_401(client_with_key: httpx.AsyncClient) -> None:
    response = await client_with_key.get("/api/admin/test")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert "Invalid or missing" in response.json()["detail"]


@pytest.mark.asyncio
async def test_wrong_key_returns_401(client_with_key: httpx.AsyncClient) -> None:
    response = await client_with_key.get(
        "/api/admin/test",
        headers={"Authorization": "Bearer wrong-key"},
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_auth_failure_is_logged(client_with_key: httpx.AsyncClient) -> None:
    with capture_logs() as captured_logs:
        response = await client_with_key.get(
            "/api/admin/test",
            headers={"Authorization": "Bearer wrong-key"},
        )

    assert response.status_code == 401
    assert any(
        entry.get("event") == "admin.auth.failed" and entry.get("path") == "/api/admin/test"
        for entry in captured_logs
    )


@pytest.mark.asyncio
async def test_key_not_configured_returns_503(client_no_key: httpx.AsyncClient) -> None:
    response = await client_no_key.get(
        "/api/admin/test",
        headers={"Authorization": "Bearer some-key"},
    )

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_timing_safe_comparison(client_with_key: httpx.AsyncClient) -> None:
    with patch("app.api.auth.secrets.compare_digest", wraps=secrets.compare_digest) as mock_compare:
        await client_with_key.get(
            "/api/admin/test",
            headers={"Authorization": f"Bearer {TEST_API_KEY}"},
        )

    mock_compare.assert_called_once()
