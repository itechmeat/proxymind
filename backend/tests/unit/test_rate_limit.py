from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI
from structlog.testing import capture_logs

from app.middleware import rate_limit as rate_limit_module
from app.middleware.rate_limit import RateLimitMiddleware


class FakeRedis:
    def __init__(self) -> None:
        self._store: dict[str, int] = {}

    def pipeline(self, transaction: bool = False) -> FakePipeline:
        return FakePipeline(self._store)

    async def ping(self) -> bool:
        return True


class FakePipeline:
    def __init__(self, store: dict[str, int]) -> None:
        self._store = store
        self._commands: list[tuple[str, str, int | None]] = []

    def get(self, key: str) -> FakePipeline:
        self._commands.append(("get", key, None))
        return self

    def incr(self, key: str) -> FakePipeline:
        self._commands.append(("incr", key, None))
        return self

    def expire(self, key: str, ttl: int) -> FakePipeline:
        self._commands.append(("expire", key, ttl))
        return self

    async def execute(self) -> list[int | bool | None]:
        results: list[int | bool | None] = []
        for command, key, ttl in self._commands:
            if command == "get":
                results.append(self._store.get(key))
                continue
            if command == "incr":
                self._store[key] = self._store.get(key, 0) + 1
                results.append(self._store[key])
                continue
            results.append(ttl is not None)
        return results


def _make_app(
    *,
    rate_limit: int = 5,
    window_seconds: int = 60,
    proxy_depth: int = 1,
) -> FastAPI:
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        chat_rate_limit=rate_limit,
        chat_rate_window_seconds=window_seconds,
        trusted_proxy_depth=proxy_depth,
    )
    app.state.redis_client = FakeRedis()

    chat_router = APIRouter(prefix="/api/chat")

    @chat_router.post("/messages")
    async def chat_messages() -> dict[str, str]:
        return {"reply": "hello"}

    admin_router = APIRouter(prefix="/api/admin")

    @admin_router.get("/sources")
    async def admin_sources() -> dict[str, list[object]]:
        return {"sources": []}

    app.include_router(chat_router)
    app.include_router(admin_router)
    app.add_middleware(RateLimitMiddleware)
    return app


@pytest_asyncio.fixture
async def rl_client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=_make_app(rate_limit=3))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_under_limit_returns_200(rl_client: httpx.AsyncClient) -> None:
    response = await rl_client.post("/api/chat/messages")

    assert response.status_code == 200
    assert "x-ratelimit-limit" in response.headers
    assert "x-ratelimit-remaining" in response.headers
    assert "x-ratelimit-reset" in response.headers


@pytest.mark.asyncio
async def test_over_limit_returns_429(rl_client: httpx.AsyncClient) -> None:
    for _ in range(3):
        response = await rl_client.post("/api/chat/messages")
        assert response.status_code == 200

    response = await rl_client.post("/api/chat/messages")

    assert response.status_code == 429
    assert "retry-after" in response.headers
    assert response.headers["x-ratelimit-remaining"] == "0"
    assert "Rate limit exceeded" in response.json()["detail"]


@pytest.mark.asyncio
async def test_rate_limit_exceeded_is_logged(rl_client: httpx.AsyncClient) -> None:
    for _ in range(3):
        response = await rl_client.post("/api/chat/messages")
        assert response.status_code == 200

    with capture_logs() as captured_logs:
        response = await rl_client.post("/api/chat/messages")

    assert response.status_code == 429
    assert any(entry.get("event") == "rate_limit.exceeded" for entry in captured_logs)


@pytest.mark.asyncio
async def test_rate_limit_still_rejects_when_metrics_counter_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rate_limit_module, "RATE_LIMIT_HITS_TOTAL", None)

    transport = httpx.ASGITransport(app=_make_app(rate_limit=1))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first_response = await client.post("/api/chat/messages")
        second_response = await client.post("/api/chat/messages")

    assert first_response.status_code == 200
    assert second_response.status_code == 429


@pytest.mark.asyncio
async def test_admin_routes_not_rate_limited(rl_client: httpx.AsyncClient) -> None:
    for _ in range(10):
        response = await rl_client.get("/api/admin/sources")
        assert response.status_code == 200

    assert "x-ratelimit-limit" not in response.headers


@pytest.mark.asyncio
async def test_redis_failure_allows_request() -> None:
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        chat_rate_limit=1,
        chat_rate_window_seconds=60,
        trusted_proxy_depth=1,
    )

    chat_router = APIRouter(prefix="/api/chat")

    @chat_router.post("/messages")
    async def chat_messages() -> dict[str, str]:
        return {"reply": "hello"}

    app.include_router(chat_router)
    app.add_middleware(RateLimitMiddleware)
    app.state.redis_client = SimpleNamespace(
        pipeline=lambda **_kwargs: (_ for _ in ()).throw(Exception("Redis connection refused"))
    )

    transport = httpx.ASGITransport(app=app)
    with capture_logs() as captured_logs:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post("/api/chat/messages")

    assert response.status_code == 200
    assert any(entry.get("event") == "rate_limit.redis_unavailable" for entry in captured_logs)


@pytest.mark.asyncio
async def test_sliding_window_uses_previous_window_weight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _make_app(rate_limit=2, window_seconds=60, proxy_depth=1)
    app.state.redis_client._store["ratelimit:1.2.3.4:60"] = 4
    monkeypatch.setattr(rate_limit_module.time, "time", lambda: 150.0)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/chat/messages",
            headers={"X-Forwarded-For": "1.2.3.4"},
        )

    assert response.status_code == 429


@pytest.mark.asyncio
async def test_xff_depth_mismatch_is_logged() -> None:
    transport = httpx.ASGITransport(app=_make_app(rate_limit=5, proxy_depth=3))
    with capture_logs() as captured_logs:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/chat/messages",
                headers={"X-Forwarded-For": "1.2.3.4"},
            )

    assert response.status_code == 200
    assert any(entry.get("event") == "rate_limit.xff_depth_mismatch" for entry in captured_logs)


@pytest.mark.asyncio
async def test_x_forwarded_for_single_proxy() -> None:
    transport = httpx.ASGITransport(app=_make_app(rate_limit=1, proxy_depth=1))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first_response = await client.post(
            "/api/chat/messages",
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        second_response = await client.post(
            "/api/chat/messages",
            headers={"X-Forwarded-For": "5.6.7.8"},
        )
        third_response = await client.post(
            "/api/chat/messages",
            headers={"X-Forwarded-For": "1.2.3.4"},
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert third_response.status_code == 429


@pytest.mark.asyncio
async def test_no_xff_uses_direct_connection_ip() -> None:
    transport = httpx.ASGITransport(app=_make_app(rate_limit=1, proxy_depth=1))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first_response = await client.post("/api/chat/messages")
        second_response = await client.post("/api/chat/messages")

    assert first_response.status_code == 200
    assert second_response.status_code == 429
