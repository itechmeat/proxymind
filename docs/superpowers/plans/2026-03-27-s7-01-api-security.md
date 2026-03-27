# S7-01: API Security — Auth + Rate Limiting — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Protect admin API with Bearer token auth and chat API with Redis-based rate limiting.

**Architecture:** Two independent security components — a FastAPI dependency for admin auth (timing-safe API key check) and an ASGI middleware for chat rate limiting (sliding window counter in Redis). No external libraries — ~100 lines total.

**Tech Stack:** FastAPI Security (HTTPBearer), Redis (sliding window), secrets.compare_digest, structlog

**Spec:** `docs/superpowers/specs/2026-03-27-s7-01-api-security-design.md`

> **Commit policy:** Each task includes a commit step for logical grouping, but per project policy (`CLAUDE.md`), agents MUST NOT commit without explicit user permission. Treat commit steps as "stage and propose" — stage the files and present the commit message for approval.

---

### Task 1: Add security settings to config

**Files:**

- Modify: `backend/app/core/config.py`
- Test: `backend/tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_config.py`:

```python
def test_security_settings_defaults(monkeypatch):
    """Security settings have correct defaults."""
    from app.core.config import Settings, get_settings

    get_settings.cache_clear()
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    monkeypatch.delenv("CHAT_RATE_LIMIT", raising=False)
    monkeypatch.delenv("CHAT_RATE_WINDOW_SECONDS", raising=False)
    monkeypatch.delenv("TRUSTED_PROXY_DEPTH", raising=False)
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.admin_api_key is None
    assert settings.chat_rate_limit == 60
    assert settings.chat_rate_window_seconds == 60
    assert settings.trusted_proxy_depth == 1


def test_security_settings_from_env(monkeypatch):
    """Security settings can be configured via environment variables."""
    from app.core.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ADMIN_API_KEY", "test-secret-key-123")
    monkeypatch.setenv("CHAT_RATE_LIMIT", "120")
    monkeypatch.setenv("CHAT_RATE_WINDOW_SECONDS", "30")
    monkeypatch.setenv("TRUSTED_PROXY_DEPTH", "2")
    get_settings.cache_clear()

    settings = get_settings()
    assert settings.admin_api_key == "test-secret-key-123"
    assert settings.chat_rate_limit == 120
    assert settings.chat_rate_window_seconds == 30
    assert settings.trusted_proxy_depth == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec api python -m pytest tests/unit/test_config.py::test_security_settings_defaults tests/unit/test_config.py::test_security_settings_from_env -v`
Expected: FAIL with `AttributeError: 'Settings' object has no attribute 'admin_api_key'`

- [ ] **Step 3: Add settings to config.py**

Add these fields to the `Settings` class in `backend/app/core/config.py`, after the `log_level` field (around line 85):

```python
    admin_api_key: str | None = Field(default=None)
    chat_rate_limit: int = Field(default=60, ge=1)
    chat_rate_window_seconds: int = Field(default=60, ge=1)
    trusted_proxy_depth: int = Field(default=1, ge=1)
```

Add `"admin_api_key"` to the `normalize_empty_optional_strings` tuple so empty string becomes None.

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec api python -m pytest tests/unit/test_config.py::test_security_settings_defaults tests/unit/test_config.py::test_security_settings_from_env -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/unit/test_config.py
git commit -m "feat(security): add auth and rate limit settings to config"
```

---

### Task 2: Implement admin auth dependency

**Files:**

- Create: `backend/app/api/auth.py`
- Test: `backend/tests/unit/test_auth.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_auth.py`:

```python
from __future__ import annotations

import secrets
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI

TEST_API_KEY = "test-admin-key-abc123"


def _make_app(admin_api_key: str | None) -> FastAPI:
    from app.api.auth import verify_admin_key

    router = APIRouter(prefix="/api/admin", dependencies=[Depends(verify_admin_key)])

    @router.get("/test")
    async def admin_test():
        return {"ok": True}

    app = FastAPI()
    app.include_router(router)
    app.state.settings = SimpleNamespace(admin_api_key=admin_api_key)
    return app


from fastapi import Depends


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
async def test_valid_key_returns_200(client_with_key):
    response = await client_with_key.get(
        "/api/admin/test",
        headers={"Authorization": f"Bearer {TEST_API_KEY}"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_missing_key_returns_401(client_with_key):
    response = await client_with_key.get("/api/admin/test")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert "Invalid or missing" in response.json()["detail"]


@pytest.mark.asyncio
async def test_wrong_key_returns_401(client_with_key):
    response = await client_with_key.get(
        "/api/admin/test",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_key_not_configured_returns_503(client_no_key):
    response = await client_no_key.get(
        "/api/admin/test",
        headers={"Authorization": "Bearer some-key"},
    )
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_timing_safe_comparison(client_with_key):
    """Verify secrets.compare_digest is used, not == operator."""
    with patch.object(secrets, "compare_digest", wraps=secrets.compare_digest) as mock_compare:
        await client_with_key.get(
            "/api/admin/test",
            headers={"Authorization": f"Bearer {TEST_API_KEY}"},
        )
        mock_compare.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api python -m pytest tests/unit/test_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.auth'`

- [ ] **Step 3: Implement auth dependency**

Create `backend/app/api/auth.py`:

```python
from __future__ import annotations

import secrets

import structlog
from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = structlog.get_logger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_admin_key(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    """FastAPI dependency that verifies the admin API key.

    Apply to admin routers via ``dependencies=[Depends(verify_admin_key)]``.

    Uses ``Security(HTTPBearer(...))`` in the signature so FastAPI registers
    the Bearer scheme in the OpenAPI spec (lock icon + Authorize button).

    Behaviour:
    - Key not configured (None/empty) → 503 Service Unavailable
    - Missing or invalid key → 401 Unauthorized
    - Valid key → pass through
    """
    configured_key: str | None = request.app.state.settings.admin_api_key

    if not configured_key:
        logger.warning(
            "admin.auth.key_not_configured",
            path=request.url.path,
            client_ip=request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API key not configured",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode(), configured_key.encode()
    ):
        logger.warning(
            "admin.auth.failed",
            path=request.url.path,
            client_ip=request.client.host if request.client else "unknown",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose exec api python -m pytest tests/unit/test_auth.py -v`
Expected: PASS (all 5 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/auth.py backend/tests/unit/test_auth.py
git commit -m "feat(security): implement admin API key auth dependency"
```

---

### Task 3: Wire auth dependency to admin routers

**Files:**

- Modify: `backend/app/api/admin.py` (line 106 — router declaration, lines 162/513/634 — remove TODOs)
- Modify: `backend/app/api/profile.py` (line 25 — admin_router declaration)
- Test: `backend/tests/unit/test_admin_auth_wiring.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_admin_auth_wiring.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_API_KEY = "wiring-test-key-xyz"


@pytest.fixture
def authed_admin_app(
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
    mock_arq_pool: SimpleNamespace,
) -> FastAPI:
    from app.api.admin import router as admin_router
    from app.api.profile import admin_router as profile_admin_router

    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(profile_admin_router)
    app.state.settings = SimpleNamespace(
        admin_api_key=TEST_API_KEY,
        upload_max_file_size_mb=100,
        seaweedfs_sources_path="/sources",
        bm25_language="english",
        batch_max_items_per_request=1000,
    )
    app.state.session_factory = session_factory
    app.state.storage_service = mock_storage_service
    app.state.arq_pool = mock_arq_pool
    app.state.embedding_service = SimpleNamespace(
        model="gemini-embedding-2-preview",
        dimensions=3,
    )
    app.state.qdrant_service = SimpleNamespace(bm25_language="english")
    return app


@pytest_asyncio.fixture
async def authed_client(authed_admin_app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=authed_admin_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_admin_sources_without_key_returns_401(authed_client):
    response = await authed_client.get("/api/admin/sources")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_sources_with_key_passes_auth(authed_client):
    response = await authed_client.get(
        "/api/admin/sources",
        headers={"Authorization": f"Bearer {TEST_API_KEY}"},
    )
    # May be 200 or another status depending on DB state,
    # but NOT 401 — auth passed.
    assert response.status_code != 401


@pytest.mark.asyncio
async def test_admin_profile_without_key_returns_401(authed_client):
    # Real profile admin routes live under /api/admin/agent/*
    response = await authed_client.put(
        "/api/admin/agent/profile",
        json={"name": "Test"},
    )
    assert response.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec api python -m pytest tests/unit/test_admin_auth_wiring.py -v`
Expected: FAIL — admin routes return 200/other without auth check

- [ ] **Step 3: Wire auth to admin router in admin.py**

In `backend/app/api/admin.py`:

1. Add import at the top:

```python
from app.api.auth import verify_admin_key
```

2. Change the router declaration (line 106) from:

```python
router = APIRouter(prefix="/api/admin", tags=["admin"])
```

to:

```python
router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(verify_admin_key)],
)
```

3. Remove all three `# TODO(S7-01)` comments (lines 162, 513, 634).

- [ ] **Step 4: Wire auth to admin profile router in profile.py**

In `backend/app/api/profile.py`:

1. Add import at the top:

```python
from app.api.auth import verify_admin_key
```

2. Change the admin_router declaration (line 25) from:

```python
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])
```

to:

```python
admin_router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(verify_admin_key)],
)
```

- [ ] **Step 5: Update existing test fixtures**

The `admin_app` fixture in `backend/tests/conftest.py` mounts the real `admin_router`. After wiring auth, all existing admin tests will get 401. Fix by setting a test key and adding the auth header to `api_client`.

In `backend/tests/conftest.py`:

1. Add a module-level constant at the top:

```python
TEST_ADMIN_API_KEY = "conftest-test-key-for-admin"
```

2. In the `admin_app` fixture, add to `app.state.settings` SimpleNamespace:

```python
admin_api_key=TEST_ADMIN_API_KEY,
```

3. Update the `api_client` fixture to always send the auth header:

```python
@pytest_asyncio.fixture
async def api_client(admin_app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=admin_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {TEST_ADMIN_API_KEY}"},
    ) as client:
        yield client
```

4. Update `profile_app` fixture similarly:

```python
app.state.settings = SimpleNamespace(admin_api_key=TEST_ADMIN_API_KEY)
```

5. Update `profile_client` fixture to include the auth header:

```python
@pytest_asyncio.fixture
async def profile_client(profile_app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=profile_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {TEST_ADMIN_API_KEY}"},
    ) as client:
        yield client
```

- [ ] **Step 6: Run all tests to verify nothing breaks**

Run: `docker compose exec api python -m pytest tests/ -v --tb=short`
Expected: All tests PASS including new wiring tests. If any test fails with 401, it means it uses admin endpoints without the auth header — fix by adding the header to that test's client.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/admin.py backend/app/api/profile.py backend/tests/unit/test_admin_auth_wiring.py backend/tests/conftest.py
git commit -m "feat(security): wire admin auth dependency to admin and profile routers"
```

---

### Task 4: Implement rate limit middleware

**Files:**

- Create: `backend/app/middleware/__init__.py`
- Create: `backend/app/middleware/rate_limit.py`
- Test: `backend/tests/unit/test_rate_limit.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_rate_limit.py`:

```python
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI


def _make_app(
    rate_limit: int = 5,
    window_seconds: int = 60,
    proxy_depth: int = 1,
) -> FastAPI:
    from app.middleware.rate_limit import RateLimitMiddleware

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        chat_rate_limit=rate_limit,
        chat_rate_window_seconds=window_seconds,
        trusted_proxy_depth=proxy_depth,
    )

    router = APIRouter(prefix="/api/chat")

    @router.post("/messages")
    async def chat_messages():
        return {"reply": "hello"}

    other = APIRouter(prefix="/api/admin")

    @other.get("/sources")
    async def admin_sources():
        return {"sources": []}

    app.include_router(router)
    app.include_router(other)
    app.add_middleware(RateLimitMiddleware)
    return app


@pytest_asyncio.fixture
async def rl_client() -> httpx.AsyncClient:
    app = _make_app(rate_limit=3)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_under_limit_returns_200(rl_client):
    response = await rl_client.post("/api/chat/messages")
    assert response.status_code == 200
    assert "x-ratelimit-limit" in response.headers
    assert "x-ratelimit-remaining" in response.headers
    assert "x-ratelimit-reset" in response.headers


@pytest.mark.asyncio
async def test_over_limit_returns_429(rl_client):
    for _ in range(3):
        response = await rl_client.post("/api/chat/messages")
        assert response.status_code == 200

    response = await rl_client.post("/api/chat/messages")
    assert response.status_code == 429
    assert "retry-after" in response.headers
    assert "Rate limit exceeded" in response.json()["detail"]


@pytest.mark.asyncio
async def test_admin_routes_not_rate_limited(rl_client):
    for _ in range(10):
        response = await rl_client.get("/api/admin/sources")
        assert response.status_code == 200
    assert "x-ratelimit-limit" not in response.headers


@pytest.mark.asyncio
async def test_redis_failure_allows_request():
    """When Redis is unreachable, requests pass through (fail-open)."""
    from app.middleware.rate_limit import RateLimitMiddleware

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        chat_rate_limit=1,
        chat_rate_window_seconds=60,
        trusted_proxy_depth=1,
    )

    router = APIRouter(prefix="/api/chat")

    @router.post("/messages")
    async def chat_messages():
        return {"reply": "hello"}

    app.include_router(router)
    app.add_middleware(RateLimitMiddleware)

    # Mock Redis to raise on every call
    mock_redis = AsyncMock()
    mock_redis.pipeline.side_effect = Exception("Redis connection refused")
    app.state.redis_client = mock_redis

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/chat/messages")
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_x_forwarded_for_single_proxy():
    """With depth=1, single-entry XFF returns the client IP."""
    app = _make_app(rate_limit=1, proxy_depth=1)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # First request from IP-A (via X-Forwarded-For, single entry = Caddy added it)
        r1 = await client.post(
            "/api/chat/messages",
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        assert r1.status_code == 200

        # Second request from IP-B — separate bucket
        r2 = await client.post(
            "/api/chat/messages",
            headers={"X-Forwarded-For": "5.6.7.8"},
        )
        assert r2.status_code == 200

        # Third request from IP-A again — should be blocked (limit=1)
        r3 = await client.post(
            "/api/chat/messages",
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        assert r3.status_code == 429


@pytest.mark.asyncio
async def test_no_xff_uses_direct_connection_ip():
    """Without X-Forwarded-For, the direct connection IP is used."""
    app = _make_app(rate_limit=1, proxy_depth=1)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # No XFF header — uses ASGI scope client IP
        r1 = await client.post("/api/chat/messages")
        assert r1.status_code == 200

        r2 = await client.post("/api/chat/messages")
        assert r2.status_code == 429
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose exec api python -m pytest tests/unit/test_rate_limit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.middleware'`

- [ ] **Step 3: Create middleware package**

Create `backend/app/middleware/__init__.py`:

```python

```

(Empty `__init__.py` — just makes it a package.)

- [ ] **Step 4: Implement rate limit middleware**

Create `backend/app/middleware/rate_limit.py`:

```python
from __future__ import annotations

import time
from typing import Any

import structlog
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger(__name__)

_CHAT_PREFIX = "/api/chat"


class RateLimitMiddleware:
    """Pure ASGI middleware for sliding-window rate limiting on Chat API.

    Uses raw ASGI protocol instead of BaseHTTPMiddleware to avoid
    response-body wrapping issues with SSE streaming endpoints.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(_CHAT_PREFIX):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        settings = request.app.state.settings
        limit: int = settings.chat_rate_limit
        window: int = settings.chat_rate_window_seconds
        proxy_depth: int = settings.trusted_proxy_depth

        client_ip = _extract_client_ip(scope, proxy_depth)
        now = time.time()

        try:
            current_count, previous_count, window_start = await _get_counters(
                request, client_ip, now, window
            )
        except Exception:
            logger.warning("rate_limit.redis_unavailable", client_ip=client_ip)
            await self.app(scope, receive, send)
            return

        elapsed_fraction = (now - window_start) / window
        weighted_count = previous_count * (1.0 - elapsed_fraction) + current_count
        remaining = max(0, int(limit - weighted_count))
        reset_at = int(window_start + window)

        if weighted_count > limit:
            retry_after = max(1, reset_at - int(now))
            logger.warning(
                "rate_limit.exceeded",
                client_ip=client_ip,
                path=scope["path"],
                weighted_count=round(weighted_count, 1),
                limit=limit,
            )
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_at),
                },
            )
            await response(scope, receive, send)
            return

        # Inject rate limit headers into the response
        rl_headers = {
            b"x-ratelimit-limit": str(limit).encode(),
            b"x-ratelimit-remaining": str(remaining).encode(),
            b"x-ratelimit-reset": str(reset_at).encode(),
        }

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                for name, value in rl_headers.items():
                    headers.append((name, value))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


def _extract_client_ip(scope: Scope, proxy_depth: int) -> str:
    # Extract X-Forwarded-For from raw ASGI headers
    xff_value: str | None = None
    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-for":
            xff_value = value.decode("latin-1")
            break

    if xff_value:
        parts = [p.strip() for p in xff_value.split(",")]
        # Each trusted proxy appends one entry at the end of XFF.
        # Skip proxy_depth entries from the right; the next one is the client.
        index = len(parts) - proxy_depth - 1
        if index >= 0:
            return parts[index]
        return parts[0]

    client = scope.get("client")
    if client:
        return client[0]
    return "unknown"


async def _get_counters(
    request: Request,
    client_ip: str,
    now: float,
    window: int,
) -> tuple[int, int, float]:
    """Return (current_count, previous_count, current_window_start)."""
    redis = request.app.state.redis_client
    window_start = (int(now) // window) * window
    previous_window_start = window_start - window

    current_key = f"ratelimit:{client_ip}:{window_start}"
    previous_key = f"ratelimit:{client_ip}:{previous_window_start}"

    pipe = redis.pipeline(transaction=False)
    pipe.get(previous_key)
    pipe.incr(current_key)
    pipe.expire(current_key, window * 2)
    results = await pipe.execute()

    previous_count = int(results[0] or 0)
    current_count = int(results[1])
    return current_count, previous_count, float(window_start)
```

- [ ] **Step 5: Add in-memory Redis mock for unit tests**

The tests above use `app.state.redis_client` which doesn't exist in the test fixture. We need to add a simple in-memory Redis mock to the test `_make_app` function.

Add to the top of `backend/tests/unit/test_rate_limit.py`:

```python
class FakeRedis:
    """Minimal in-memory Redis mock for rate limit tests."""

    def __init__(self):
        self._store: dict[str, int] = {}

    def pipeline(self, transaction=False):
        return FakePipeline(self._store)


class FakePipeline:
    def __init__(self, store):
        self._store = store
        self._commands = []

    def get(self, key):
        self._commands.append(("get", key))
        return self

    def incr(self, key):
        self._commands.append(("incr", key))
        return self

    def expire(self, key, ttl):
        self._commands.append(("expire", key, ttl))
        return self

    async def execute(self):
        results = []
        for cmd in self._commands:
            if cmd[0] == "get":
                results.append(self._store.get(cmd[1]))
            elif cmd[0] == "incr":
                self._store[cmd[1]] = self._store.get(cmd[1], 0) + 1
                results.append(self._store[cmd[1]])
            elif cmd[0] == "expire":
                results.append(True)
        return results
```

Then in `_make_app`, add after `app.state.settings = ...`:

```python
    app.state.redis_client = FakeRedis()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `docker compose exec api python -m pytest tests/unit/test_rate_limit.py -v`
Expected: All 7 tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/middleware/__init__.py backend/app/middleware/rate_limit.py backend/tests/unit/test_rate_limit.py
git commit -m "feat(security): implement Redis-based rate limit middleware for Chat API"
```

---

### Task 5: Mount middleware in main.py

**Files:**

- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/test_app_main.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_app_main.py`:

```python
def test_rate_limit_middleware_is_mounted():
    """RateLimitMiddleware is present in the app middleware stack."""
    from app.main import app
    from app.middleware.rate_limit import RateLimitMiddleware

    middleware_classes = [m.cls for m in app.user_middleware]
    assert RateLimitMiddleware in middleware_classes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec api python -m pytest tests/unit/test_app_main.py::test_rate_limit_middleware_is_mounted -v`
Expected: FAIL — middleware not in stack

- [ ] **Step 3: Mount middleware in main.py**

In `backend/app/main.py`, add the import after existing imports:

```python
from app.middleware.rate_limit import RateLimitMiddleware
```

Then after the `app = FastAPI(...)` line (line 195) and before the `app.include_router(...)` calls, add:

```python
app.add_middleware(RateLimitMiddleware)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec api python -m pytest tests/unit/test_app_main.py::test_rate_limit_middleware_is_mounted -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/unit/test_app_main.py
git commit -m "feat(security): mount rate limit middleware in main app"
```

---

### Task 6: Update .env.example and documentation

**Files:**

- Modify: `backend/.env.example` (or `.env` template)

- [ ] **Step 1: Add security variables to .env.example**

Add to `backend/.env.example` (or the main `.env` if no `.env.example` exists) at the end, under a new section comment:

```bash
# --- Security (S7-01) ---
# API key for admin endpoints. Admin API blocked (503) when not set.
# ADMIN_API_KEY=your-secret-key-here

# Rate limiting for Chat API
# CHAT_RATE_LIMIT=60
# CHAT_RATE_WINDOW_SECONDS=60

# X-Forwarded-For depth (1 = one trusted proxy like Caddy)
# TRUSTED_PROXY_DEPTH=1
```

- [ ] **Step 2: Commit**

```bash
git add backend/.env.example  # or .env if no .env.example
git commit -m "docs(security): add auth and rate limit env variables to .env.example"
```

---

### Task 7: Full integration test

**Files:**

- Create: `backend/tests/integration/test_api_security.py`

- [ ] **Step 1: Write integration tests**

Create `backend/tests/integration/test_api_security.py`:

```python
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

TEST_KEY = "integration-test-key-456"


@pytest.fixture
def secure_app(
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
    mock_arq_pool: SimpleNamespace,
) -> FastAPI:
    from app.api.admin import router as admin_router
    from app.api.chat import router as chat_router
    from app.api.health import router as health_router
    from app.middleware.rate_limit import RateLimitMiddleware

    app = FastAPI()
    app.state.settings = SimpleNamespace(
        admin_api_key=TEST_KEY,
        chat_rate_limit=3,
        chat_rate_window_seconds=60,
        trusted_proxy_depth=1,
        upload_max_file_size_mb=100,
        seaweedfs_sources_path="/sources",
        bm25_language="english",
        batch_max_items_per_request=1000,
        min_retrieved_chunks=1,
        max_citations_per_response=5,
        retrieval_context_budget=4096,
        max_promotions_per_response=1,
        sse_heartbeat_interval_seconds=15,
        sse_inter_token_timeout_seconds=30,
        conversation_memory_budget=4096,
        conversation_summary_ratio=0.3,
    )
    app.state.session_factory = session_factory
    app.state.storage_service = mock_storage_service
    app.state.arq_pool = mock_arq_pool
    app.state.embedding_service = SimpleNamespace(
        model="gemini-embedding-2-preview", dimensions=3
    )
    app.state.qdrant_service = SimpleNamespace(
        bm25_language="english",
        hybrid_search=AsyncMock(return_value=[]),
        dense_search=AsyncMock(return_value=[]),
    )

    # In-memory Redis for rate limiting
    from tests.unit.test_rate_limit import FakeRedis

    app.state.redis_client = FakeRedis()

    app.add_middleware(RateLimitMiddleware)
    app.include_router(admin_router)
    app.include_router(chat_router)
    app.include_router(health_router)
    return app


@pytest_asyncio.fixture
async def secure_client(secure_app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=secure_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.mark.asyncio
async def test_admin_auth_full_flow(secure_client):
    """Admin auth: 401 without key, 200 with key."""
    r_no_key = await secure_client.get("/api/admin/sources")
    assert r_no_key.status_code == 401

    r_wrong = await secure_client.get(
        "/api/admin/sources",
        headers={"Authorization": "Bearer wrong"},
    )
    assert r_wrong.status_code == 401

    r_ok = await secure_client.get(
        "/api/admin/sources",
        headers={"Authorization": f"Bearer {TEST_KEY}"},
    )
    assert r_ok.status_code == 200


@pytest.mark.asyncio
async def test_chat_rate_limit_full_flow(secure_client):
    """Chat rate limit: N requests pass through the full stack, N+1 gets 429."""
    for i in range(3):
        r = await secure_client.post(
            "/api/chat/sessions",
            json={"agent_id": "00000000-0000-0000-0000-000000000001"},
        )
        # Assert the request actually reached the handler (201 for created session).
        # If this fails with 500, the secure_app fixture is missing dependencies.
        assert r.status_code == 201, (
            f"Request {i+1} expected 201 but got {r.status_code}: {r.text}"
        )

    r_limited = await secure_client.post(
        "/api/chat/sessions",
        json={"agent_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert r_limited.status_code == 429
    assert "retry-after" in r_limited.headers


@pytest.mark.asyncio
async def test_health_not_affected(secure_client):
    """Health endpoints are not affected by auth or rate limiting."""
    r = await secure_client.get("/health")
    assert r.status_code in (200, 503)  # depends on DB availability
    assert "x-ratelimit-limit" not in r.headers
```

- [ ] **Step 2: Run integration tests**

Run: `docker compose exec api python -m pytest tests/integration/test_api_security.py -v`
Expected: All 3 tests PASS

- [ ] **Step 3: Run full test suite**

Run: `docker compose exec api python -m pytest tests/ -v --tb=short`
Expected: All tests PASS — no regressions

- [ ] **Step 4: Commit**

```bash
git add backend/tests/integration/test_api_security.py
git commit -m "test(security): add integration tests for admin auth and chat rate limiting"
```
