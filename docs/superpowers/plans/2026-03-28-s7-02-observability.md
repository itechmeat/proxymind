# S7-02: Observability — Audit Logging + Monitoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every twin response reproducible via audit logging and the system observable via Prometheus metrics, Grafana dashboards, and OpenTelemetry tracing with correlation IDs.

**Architecture:** Layered approach — ObservabilityMiddleware for request-level concerns (correlation IDs, OTel spans, Prometheus metrics), separate AuditService for domain-level audit records. Config hashes already exist in PersonaContext (via PersonaLoader). New Docker Compose services: Prometheus, Grafana, Tempo.

**Tech Stack:** prometheus-client, opentelemetry-api/sdk/exporters/instrumentors, structlog contextvars, Grafana Tempo, Prometheus, Grafana

---

## File Map

| Action | Path                                                  | Responsibility                                                           |
| ------ | ----------------------------------------------------- | ------------------------------------------------------------------------ |
| Create | `backend/app/services/audit.py`                       | AuditService — writes audit_logs records                                 |
| Create | `backend/app/services/metrics.py`                     | Prometheus metric registry definitions                                   |
| Create | `backend/app/api/metrics.py`                          | GET /metrics endpoint                                                    |
| Create | `backend/app/middleware/observability.py`             | Correlation IDs, OTel spans, Prometheus request metrics                  |
| Create | `backend/app/services/telemetry.py`                   | OTel TracerProvider initialization                                       |
| Create | `backend/tests/unit/test_audit_service.py`            | AuditService unit tests                                                  |
| Create | `backend/tests/unit/test_observability_middleware.py` | Middleware unit tests                                                    |
| Create | `backend/tests/unit/test_metrics_endpoint.py`         | Metrics endpoint unit tests                                              |
| Create | `backend/tests/unit/test_telemetry.py`                | Telemetry initialization tests                                           |
| Create | `backend/tests/integration/test_audit_integration.py` | Full chat flow → audit record test                                       |
| Create | `config/prometheus/prometheus.yml`                    | Prometheus scrape config                                                 |
| Create | `config/tempo/tempo.yaml`                             | Tempo monolithic mode config                                             |
| Create | `config/grafana/provisioning/datasources.yaml`        | Prometheus + Tempo data sources                                          |
| Create | `config/grafana/provisioning/dashboards.yaml`         | Dashboard provider config                                                |
| Create | `config/grafana/dashboards/proxymind-overview.json`   | Main dashboard                                                           |
| Modify | `backend/app/core/config.py`                          | Add OTEL\_\* settings                                                    |
| Modify | `backend/app/core/logging.py`                         | Add request_id + trace_id + span_id structlog processors                 |
| Modify | `backend/app/main.py`                                 | Add ObservabilityMiddleware, telemetry init, metrics router              |
| Modify | `backend/app/services/chat.py`                        | Call AuditService after message finalization (complete, partial, failed) |
| Modify | `backend/app/api/dependencies.py`                     | Wire AuditService into ChatService; pass correlation_id on arq enqueue   |
| Modify | `backend/app/middleware/rate_limit.py`                | Increment rate_limit_hits_total counter                                  |
| Modify | `backend/app/workers/main.py`                         | Init/shutdown telemetry; bind correlation_id per task                    |
| Modify | `backend/pyproject.toml`                              | Add observability dependencies                                           |
| Modify | `docker-compose.yml`                                  | Add prometheus, grafana, tempo services                                  |

---

### Task 1: Add observability dependencies to pyproject.toml

**Files:**

- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add dependencies**

Add to the `[project.dependencies]` list in `backend/pyproject.toml`:

```toml
    "prometheus-client>=0.22.0",
    "opentelemetry-api>=1.40.0",
    "opentelemetry-sdk>=1.40.0",
    "opentelemetry-exporter-otlp>=1.40.0",
    "opentelemetry-instrumentation-fastapi>=0.51b0",
    "opentelemetry-instrumentation-httpx>=0.51b0",
    "opentelemetry-instrumentation-sqlalchemy>=0.51b0",
    "opentelemetry-instrumentation-redis>=0.51b0",
```

- [ ] **Step 2: Rebuild the backend container to verify deps resolve**

Run inside docker:

```bash
docker compose build api
```

Expected: build succeeds, no dependency conflicts.

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml
git commit -m "chore(deps): add observability dependencies (prometheus, opentelemetry)"
```

---

### Task 2: Add OTel settings to config

**Files:**

- Modify: `backend/app/core/config.py`
- Create: `backend/tests/unit/test_config_otel.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_config_otel.py`:

```python
"""Tests for OTel settings in Settings."""
import os

import pytest


def test_otel_defaults():
    """OTel settings have correct defaults."""
    os.environ.setdefault("POSTGRES_HOST", "localhost")
    os.environ.setdefault("POSTGRES_USER", "test")
    os.environ.setdefault("POSTGRES_PASSWORD", "test")
    os.environ.setdefault("POSTGRES_DB", "test")
    os.environ.setdefault("REDIS_HOST", "localhost")
    os.environ.setdefault("QDRANT_HOST", "localhost")
    os.environ.setdefault("SEAWEEDFS_HOST", "localhost")

    from app.core.config import Settings

    settings = Settings()
    assert settings.otel_enabled is False
    assert settings.otel_exporter_otlp_endpoint == "http://tempo:4317"
    assert settings.otel_service_name == "proxymind-api"


def test_otel_disabled():
    """OTel can be disabled via env var."""
    os.environ["OTEL_ENABLED"] = "false"
    os.environ.setdefault("POSTGRES_HOST", "localhost")
    os.environ.setdefault("POSTGRES_USER", "test")
    os.environ.setdefault("POSTGRES_PASSWORD", "test")
    os.environ.setdefault("POSTGRES_DB", "test")
    os.environ.setdefault("REDIS_HOST", "localhost")
    os.environ.setdefault("QDRANT_HOST", "localhost")
    os.environ.setdefault("SEAWEEDFS_HOST", "localhost")

    from app.core.config import Settings

    settings = Settings()
    assert settings.otel_enabled is False
    os.environ.pop("OTEL_ENABLED", None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_config_otel.py -v"`
Expected: FAIL — `otel_enabled` attribute does not exist.

- [ ] **Step 3: Add OTel fields to Settings**

Add to `backend/app/core/config.py` in the `Settings` class, after line 89 (`trusted_proxy_depth`):

```python
    otel_enabled: bool = Field(default=False)
    otel_exporter_otlp_endpoint: str = Field(default="http://tempo:4317", min_length=1)
    otel_service_name: str = Field(default="proxymind-api", min_length=1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_config_otel.py -v"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/unit/test_config_otel.py
git commit -m "feat(config): add OTel settings (otel_enabled, endpoint, service_name)"
```

---

### Task 3: Correlation ID middleware + structlog integration

**Files:**

- Create: `backend/app/middleware/observability.py`
- Modify: `backend/app/core/logging.py`
- Create: `backend/tests/unit/test_observability_middleware.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_observability_middleware.py`:

```python
"""Tests for ObservabilityMiddleware."""
import uuid

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def _echo_request_id(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


@pytest.fixture
def app_with_middleware():
    from app.middleware.observability import ObservabilityMiddleware

    app = Starlette(routes=[Route("/test", _echo_request_id)])
    app.add_middleware(ObservabilityMiddleware)
    return app


def test_generates_request_id_when_absent(app_with_middleware):
    """Middleware generates X-Request-ID if client doesn't send one."""
    client = TestClient(app_with_middleware)
    response = client.get("/test")
    assert response.status_code == 200
    request_id = response.headers.get("x-request-id")
    assert request_id is not None
    uuid.UUID(request_id)  # must be valid UUID


def test_preserves_client_request_id(app_with_middleware):
    """Middleware preserves client-provided X-Request-ID."""
    client = TestClient(app_with_middleware)
    custom_id = str(uuid.uuid4())
    response = client.get("/test", headers={"X-Request-ID": custom_id})
    assert response.headers.get("x-request-id") == custom_id


def test_non_http_scope_passthrough(app_with_middleware):
    """Non-HTTP scopes are passed through without modification."""
    client = TestClient(app_with_middleware)
    # WebSocket scope should not crash
    with pytest.raises(Exception):
        # Starlette raises because no WS route exists, but middleware doesn't crash
        client.websocket_connect("/test")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_observability_middleware.py -v"`
Expected: FAIL — module `app.middleware.observability` does not exist.

- [ ] **Step 3: Add contextvars and structlog processor**

Modify `backend/app/core/logging.py` — add contextvars support:

```python
import contextvars
import logging
import sys
from collections.abc import Mapping, Sequence
from typing import Any

import structlog

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
}

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if normalized_key in SENSITIVE_KEYS:
                redacted[key] = REDACTED
            else:
                redacted[key] = _redact_value(item)
        return redacted

    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_redact_value(item) for item in value]

    return value


def redact_sensitive_fields(
    _: Any,
    __: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    return _redact_value(event_dict)


def add_request_context(
    _: Any,
    __: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Inject request_id from contextvars into every log entry."""
    rid = request_id_var.get()
    if rid is not None:
        event_dict["request_id"] = rid
    return event_dict


def add_trace_context(
    _: Any,
    __: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Inject OTel trace_id and span_id into every log entry for log-trace correlation."""
    try:
        from opentelemetry import trace as otel_trace

        span = otel_trace.get_current_span()
        ctx = span.get_span_context()
        if ctx and ctx.trace_id:
            event_dict["trace_id"] = format(ctx.trace_id, "032x")
            event_dict["span_id"] = format(ctx.span_id, "016x")
    except ImportError:
        pass
    return event_dict


def configure_logging(log_level: str) -> None:
    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            *shared_processors,
            add_request_context,
            add_trace_context,
            redact_sensitive_fields,
            structlog.processors.dict_tracebacks,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
```

- [ ] **Step 4: Implement ObservabilityMiddleware**

Create `backend/app/middleware/observability.py`:

```python
from __future__ import annotations

import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_var

_REQUEST_ID_HEADER = b"x-request-id"


class ObservabilityMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _extract_request_id(scope)
        token = request_id_var.set(request_id)
        start_time = time.perf_counter()

        status_code = 500

        async def send_with_request_id(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                headers = list(message.get("headers", []))
                headers.append((_REQUEST_ID_HEADER, request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration = time.perf_counter() - start_time
            _record_metrics(scope, status_code, duration)
            request_id_var.reset(token)


def _extract_request_id(scope: Scope) -> str:
    for name, value in scope.get("headers", []):
        if name == _REQUEST_ID_HEADER:
            return value.decode("latin-1")
    return str(uuid.uuid4())


def _record_metrics(scope: Scope, status_code: int, duration: float) -> None:
    """Record Prometheus metrics for the request. Imported lazily to avoid circular deps."""
    try:
        from app.services.metrics import record_request
        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")
        record_request(method=method, path=path, status_code=status_code, duration=duration)
    except ImportError:
        pass
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_observability_middleware.py -v"`
Expected: PASS (metrics import will be skipped gracefully since metrics.py doesn't exist yet)

- [ ] **Step 6: Commit**

```bash
git add backend/app/middleware/observability.py backend/app/core/logging.py backend/tests/unit/test_observability_middleware.py
git commit -m "feat(observability): add ObservabilityMiddleware with correlation IDs and structlog integration"
```

---

### Task 4: Prometheus metrics definitions and /metrics endpoint

**Files:**

- Create: `backend/app/services/metrics.py`
- Create: `backend/app/api/metrics.py`
- Create: `backend/tests/unit/test_metrics_endpoint.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_metrics_endpoint.py`:

```python
"""Tests for Prometheus metrics endpoint."""
import pytest
from starlette.testclient import TestClient


@pytest.fixture
def metrics_app():
    from fastapi import FastAPI
    from app.api.metrics import router

    app = FastAPI()
    app.include_router(router)
    return app


def test_metrics_endpoint_returns_prometheus_format(metrics_app):
    """GET /metrics returns Prometheus text exposition format."""
    client = TestClient(metrics_app)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"] or "text/plain" in response.headers.get("content-type", "")
    body = response.text
    # Must contain at least one metric from our registry
    assert "http_requests_total" in body or "# HELP" in body


def test_record_request_increments_counter():
    """record_request increments http_requests_total and observes histogram."""
    from app.services.metrics import record_request, HTTP_REQUESTS_TOTAL

    before = HTTP_REQUESTS_TOTAL._metrics.copy()
    record_request(method="GET", path="/test", status_code=200, duration=0.05)
    sample = HTTP_REQUESTS_TOTAL.labels(method="GET", path="/test", status_code="200")
    assert sample._value.get() >= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_metrics_endpoint.py -v"`
Expected: FAIL — modules don't exist.

- [ ] **Step 3: Create metrics definitions**

Create `backend/app/services/metrics.py`:

```python
"""Prometheus metric definitions for ProxyMind."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)

CHAT_RESPONSES_TOTAL = Counter(
    "chat_responses_total",
    "Total chat responses by final status",
    ["status"],
)

CHAT_RESPONSE_LATENCY_SECONDS = Histogram(
    "chat_response_latency_seconds",
    "Chat response latency in seconds",
    buckets=(0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0),
)

RATE_LIMIT_HITS_TOTAL = Counter(
    "rate_limit_hits_total",
    "Total rate limit rejections",
)

AUDIT_LOGS_TOTAL = Counter(
    "audit_logs_total",
    "Total audit log records written",
)

ARQ_QUEUE_DEPTH = Gauge(
    "arq_queue_depth",
    "Current depth of the arq task queue",
)


def record_request(
    *,
    method: str,
    path: str,
    status_code: int,
    duration: float,
) -> None:
    """Record a completed HTTP request in Prometheus metrics."""
    # Normalize paths to avoid high-cardinality labels
    normalized_path = _normalize_path(path)
    HTTP_REQUESTS_TOTAL.labels(method=method, path=normalized_path, status_code=str(status_code)).inc()
    HTTP_REQUEST_DURATION_SECONDS.labels(method=method, path=normalized_path).observe(duration)


def _normalize_path(path: str) -> str:
    """Collapse UUID/ID segments to reduce label cardinality."""
    parts = path.rstrip("/").split("/")
    normalized = []
    for part in parts:
        if len(part) >= 32 and all(c in "0123456789abcdef-" for c in part.lower()):
            normalized.append(":id")
        else:
            normalized.append(part)
    return "/".join(normalized) or "/"
```

- [ ] **Step 4: Create metrics endpoint**

Create `backend/app/api/metrics.py`:

```python
"""Prometheus metrics endpoint."""
from fastapi import APIRouter, Response
from prometheus_client import REGISTRY, generate_latest

router = APIRouter(tags=["observability"])


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Expose Prometheus metrics in text exposition format."""
    return Response(
        content=generate_latest(REGISTRY),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_metrics_endpoint.py -v"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/metrics.py backend/app/api/metrics.py backend/tests/unit/test_metrics_endpoint.py
git commit -m "feat(metrics): add Prometheus metric definitions and /metrics endpoint"
```

---

### Task 5: AuditService

**Files:**

- Create: `backend/app/services/audit.py`
- Create: `backend/tests/unit/test_audit_service.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_audit_service.py`:

```python
"""Tests for AuditService."""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.operations import AuditLog


@pytest.fixture
def mock_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_log_response_creates_audit_record(mock_session):
    """AuditService.log_response creates an AuditLog with all fields."""
    from app.services.audit import AuditService

    service = AuditService()
    agent_id = uuid.uuid4()
    session_id = uuid.uuid4()
    message_id = uuid.uuid4()
    snapshot_id = uuid.uuid4()
    source_ids = [uuid.uuid4(), uuid.uuid4()]

    result = await service.log_response(
        db=mock_session,
        agent_id=agent_id,
        session_id=session_id,
        message_id=message_id,
        snapshot_id=snapshot_id,
        source_ids=source_ids,
        model_name="openai/gpt-4o",
        token_count_prompt=100,
        token_count_completion=50,
        retrieval_chunks_count=3,
        latency_ms=1500,
        config_commit_hash="abc123",
        config_content_hash="def456",
    )

    mock_session.add.assert_called_once()
    added_record = mock_session.add.call_args[0][0]
    assert isinstance(added_record, AuditLog)
    assert added_record.agent_id == agent_id
    assert added_record.session_id == session_id
    assert added_record.message_id == message_id
    assert added_record.snapshot_id == snapshot_id
    assert added_record.source_ids == source_ids
    assert added_record.model_name == "openai/gpt-4o"
    assert added_record.token_count_prompt == 100
    assert added_record.token_count_completion == 50
    assert added_record.retrieval_chunks_count == 3
    assert added_record.latency_ms == 1500
    assert added_record.config_commit_hash == "abc123"
    assert added_record.config_content_hash == "def456"
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_log_response_increments_prometheus_counter(mock_session):
    """AuditService.log_response increments audit_logs_total counter."""
    from app.services.audit import AuditService
    from app.services.metrics import AUDIT_LOGS_TOTAL

    before = AUDIT_LOGS_TOTAL._value.get()
    service = AuditService()
    await service.log_response(
        db=mock_session,
        agent_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        message_id=uuid.uuid4(),
        snapshot_id=None,
        source_ids=[],
        model_name=None,
        token_count_prompt=0,
        token_count_completion=0,
        retrieval_chunks_count=0,
        latency_ms=0,
        config_commit_hash="",
        config_content_hash="",
    )
    after = AUDIT_LOGS_TOTAL._value.get()
    assert after == before + 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_audit_service.py -v"`
Expected: FAIL — `app.services.audit` does not exist.

- [ ] **Step 3: Implement AuditService**

Create `backend/app/services/audit.py`:

```python
"""Audit logging service for recording every twin response."""
from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.operations import AuditLog
from app.services.metrics import AUDIT_LOGS_TOTAL

logger = structlog.get_logger(__name__)


class AuditService:
    async def log_response(
        self,
        *,
        db: AsyncSession,
        agent_id: uuid.UUID,
        session_id: uuid.UUID,
        message_id: uuid.UUID,
        snapshot_id: uuid.UUID | None,
        source_ids: list[uuid.UUID],
        model_name: str | None,
        token_count_prompt: int,
        token_count_completion: int,
        retrieval_chunks_count: int,
        latency_ms: int,
        config_commit_hash: str,
        config_content_hash: str,
    ) -> AuditLog:
        record = AuditLog(
            id=uuid.uuid7(),
            agent_id=agent_id,
            session_id=session_id,
            message_id=message_id,
            snapshot_id=snapshot_id,
            source_ids=source_ids,
            config_commit_hash=config_commit_hash,
            config_content_hash=config_content_hash,
            model_name=model_name,
            token_count_prompt=token_count_prompt,
            token_count_completion=token_count_completion,
            retrieval_chunks_count=retrieval_chunks_count,
            latency_ms=latency_ms,
        )
        db.add(record)
        await db.commit()
        AUDIT_LOGS_TOTAL.inc()
        logger.info(
            "audit.response_logged",
            audit_id=str(record.id),
            session_id=str(session_id),
            message_id=str(message_id),
            snapshot_id=str(snapshot_id) if snapshot_id else None,
        )
        return record
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_audit_service.py -v"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/audit.py backend/tests/unit/test_audit_service.py
git commit -m "feat(audit): add AuditService for recording chat response audit logs"
```

---

### Task 6: Integrate AuditService into ChatService (complete, partial, failed)

**Files:**

- Modify: `backend/app/services/chat.py`
- Create: `backend/tests/unit/test_chat_audit_wiring.py`

- [ ] **Step 1: Write a test that verifies ChatService calls \_log_audit**

Create `backend/tests/unit/test_chat_audit_wiring.py`. This test constructs a real ChatService with a mock AuditService and verifies the audit call happens during `answer()`:

Note: The test fixture setup for ChatService is complex due to the number of dependencies and the internal flow (`_load_session` → `_ensure_snapshot_binding` → retrieval → LLM → persist → audit). Rather than writing a fragile unit test with deeply chained mocks that replicate the entire ChatService flow, the recommended approach is:

1. **Unit test `_log_audit` method directly** — verify that when `_log_audit` is called with the expected args, it delegates to `AuditService.log_response` with correct field mapping.
2. **Rely on the integration test (Task 14)** to verify the full flow: real ChatService → real DB → audit record exists.

The unit test for `_log_audit` in isolation:

```python
"""Tests that ChatService._log_audit delegates to AuditService correctly."""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_log_audit_delegates_to_audit_service():
    """_log_audit calls audit_service.log_response with correct fields."""
    from app.services.audit import AuditService
    from app.services.chat import ChatService

    mock_audit = AuditService()
    mock_audit.log_response = AsyncMock()
    mock_session = AsyncMock()

    service = ChatService.__new__(ChatService)
    service._audit_service = mock_audit
    service._session = mock_session
    service._logger = MagicMock()

    agent_id = uuid.uuid4()
    session_id = uuid.uuid4()
    message_id = uuid.uuid4()
    snapshot_id = uuid.uuid4()

    mock_chat_session = MagicMock()
    mock_chat_session.agent_id = agent_id
    mock_chat_session.id = session_id

    mock_message = MagicMock()
    mock_message.id = message_id
    mock_message.source_ids = [uuid.uuid4()]
    mock_message.model_name = "test-model"
    mock_message.token_count_prompt = 100
    mock_message.token_count_completion = 50
    mock_message.config_commit_hash = "abc"
    mock_message.config_content_hash = "def"

    await service._log_audit(
        chat_session=mock_chat_session,
        message=mock_message,
        snapshot_id=snapshot_id,
        retrieved_chunks_count=3,
        latency_ms=1500,
    )

    mock_audit.log_response.assert_awaited_once()
    call_kwargs = mock_audit.log_response.call_args.kwargs
    assert call_kwargs["agent_id"] == agent_id
    assert call_kwargs["session_id"] == session_id
    assert call_kwargs["message_id"] == message_id
    assert call_kwargs["snapshot_id"] == snapshot_id
    assert call_kwargs["config_commit_hash"] == "abc"
    assert call_kwargs["latency_ms"] == 1500


@pytest.mark.asyncio
async def test_log_audit_noop_when_no_audit_service():
    """_log_audit is a no-op when audit_service is None."""
    from app.services.chat import ChatService

    service = ChatService.__new__(ChatService)
    service._audit_service = None
    service._logger = MagicMock()

    # Should not raise
    await service._log_audit(
        chat_session=MagicMock(),
        message=MagicMock(),
        snapshot_id=None,
        retrieved_chunks_count=0,
        latency_ms=0,
    )
```

- [ ] **Step 2: Modify ChatService to accept and call AuditService**

In `backend/app/services/chat.py`:

Add imports at top:

```python
import time
from app.services.audit import AuditService
from app.services.metrics import CHAT_RESPONSES_TOTAL
```

Add `audit_service` parameter to `ChatService.__init__` (after `summary_enqueuer`):

```python
        audit_service: AuditService | None = None,
```

Store it:

```python
        self._audit_service = audit_service
```

Add a private method to ChatService:

```python
    async def _log_audit(
        self,
        *,
        chat_session: Session,
        message: Message,
        snapshot_id: uuid.UUID | None,
        retrieved_chunks_count: int,
        latency_ms: int,
    ) -> None:
        if self._audit_service is None:
            return
        try:
            await self._audit_service.log_response(
                db=self._session,
                agent_id=chat_session.agent_id,
                session_id=chat_session.id,
                message_id=message.id,
                snapshot_id=snapshot_id,
                source_ids=message.source_ids or [],
                model_name=message.model_name,
                token_count_prompt=message.token_count_prompt or 0,
                token_count_completion=message.token_count_completion or 0,
                retrieval_chunks_count=retrieved_chunks_count,
                latency_ms=latency_ms,
                config_commit_hash=message.config_commit_hash or "",
                config_content_hash=message.config_content_hash or "",
            )
        except Exception as error:
            self._logger.error(
                "audit.log_failed",
                session_id=str(chat_session.id),
                message_id=str(message.id),
                error=str(error),
            )
```

**Call sites — ALL terminal message states (complete, partial, failed):**

1. Add `start_time = time.perf_counter()` at the start of both `answer()` and `stream_answer()`.

2. **Complete (streaming path):** Call `_log_audit` right before `yield ChatStreamCitations(...)` after `await self._session.commit()` at line ~504:

```python
                latency_ms = int((time.perf_counter() - start_time) * 1000)
                await self._log_audit(
                    chat_session=chat_session,
                    message=assistant_message,
                    snapshot_id=snapshot_id,
                    retrieved_chunks_count=len(selected_chunks),
                    latency_ms=latency_ms,
                )
```

3. **Complete (sync `answer()`):** Call `_log_audit` before `return ChatAnswerResult(...)` for both the successful and refusal paths.

4. **Failed (streaming path):** In the `except` block of `stream_answer` (~line 524-536), after `await self._session.commit()`, add:

```python
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            await self._log_audit(
                chat_session=chat_session,
                message=assistant_message,
                snapshot_id=snapshot_id,
                retrieved_chunks_count=len(retrieved_chunks),
                latency_ms=latency_ms,
            )
```

5. **Partial (disconnect) and Failed (timeout):** `save_partial_on_disconnect` and `save_failed_on_timeout` currently accept only `(assistant_message_id, accumulated_content)`. The API route calls them with this signature at `backend/app/api/chat.py:148,160,174`.

**Decision:** Do NOT change the method signatures or the API route. Instead, load the required context from DB inside these methods:

```python
    async def save_partial_on_disconnect(
        self,
        assistant_message_id: uuid.UUID,
        accumulated_content: str,
    ) -> None:
        message = await self._session.get(Message, assistant_message_id)
        if message is None or message.status is not MessageStatus.STREAMING:
            return

        message.content = accumulated_content
        message.status = MessageStatus.PARTIAL
        await self._session.commit()

        # Audit: load session for agent_id context
        chat_session = await self._session.get(Session, message.session_id)
        if chat_session is not None:
            await self._log_audit(
                chat_session=chat_session,
                message=message,
                snapshot_id=message.snapshot_id,
                retrieved_chunks_count=len(message.source_ids or []),
                latency_ms=0,  # unknown at disconnect time
            )
```

Same pattern for `save_failed_on_timeout`. One extra `SELECT session` per disconnect/timeout — acceptable overhead for an uncommon code path.

7. **Metrics:** Add `CHAT_RESPONSES_TOTAL.labels(status=status.value).inc()` wherever an assistant message reaches a terminal state (complete, partial, failed).

- [ ] **Step 3: Run existing tests to verify nothing broke**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_chat_service.py tests/unit/test_chat_streaming.py -v"`
Expected: PASS (audit_service defaults to None so existing tests still work)

- [ ] **Step 4: Run the new test**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_chat_audit_wiring.py -v"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/chat.py backend/tests/unit/test_chat_audit_wiring.py
git commit -m "feat(audit): integrate AuditService into ChatService for all terminal states (complete/partial/failed)"
```

---

### Task 7: Rate limit metrics integration

**Files:**

- Modify: `backend/app/middleware/rate_limit.py`

- [ ] **Step 1: Add metric increment on rate limit rejection**

In `backend/app/middleware/rate_limit.py`, add a resilient import:

```python
try:
  from app.services.metrics import RATE_LIMIT_HITS_TOTAL
except ImportError:
  RATE_LIMIT_HITS_TOTAL = None
```

After the `logger.warning("rate_limit.exceeded", ...)` line (line ~68), add:

```python
      if RATE_LIMIT_HITS_TOTAL is not None:
        RATE_LIMIT_HITS_TOTAL.inc()
```

- [ ] **Step 2: Run existing rate limit tests**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_rate_limit.py -v"`
Expected: PASS (test needs to mock or import metrics — if it fails due to import, add a try/except around the import in rate_limit.py to handle the case where metrics aren't available yet in tests)

- [ ] **Step 3: Commit**

```bash
git add backend/app/middleware/rate_limit.py
git commit -m "feat(metrics): increment rate_limit_hits_total counter on rate limit rejection"
```

---

### Task 8: OpenTelemetry tracing initialization

**Files:**

- Create: `backend/app/services/telemetry.py`
- Create: `backend/tests/unit/test_telemetry.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/test_telemetry.py`:

```python
"""Tests for OTel telemetry initialization."""
import pytest
from unittest.mock import patch, MagicMock


def test_init_telemetry_when_enabled():
    """init_telemetry sets up TracerProvider when otel_enabled is True."""
    from app.services.telemetry import init_telemetry

        with patch("app.services.telemetry.TracerProvider") as mock_provider_cls, \
          patch("app.services.telemetry.trace") as mock_trace, \
          patch("app.services.telemetry.BatchSpanProcessor") as mock_bsp, \
          patch("app.services.telemetry.OTLPSpanExporter") as mock_exporter:
        init_telemetry(
            enabled=True,
            endpoint="http://localhost:4317",
            service_name="test-service",
        )
        mock_provider_cls.assert_called_once()
        mock_trace.set_tracer_provider.assert_called_once()


def test_init_telemetry_when_disabled():
    """init_telemetry is a no-op when otel_enabled is False."""
    from app.services.telemetry import init_telemetry

    with patch("app.services.telemetry.trace") as mock_trace:
        init_telemetry(
            enabled=False,
            endpoint="http://localhost:4317",
            service_name="test-service",
        )
        mock_trace.set_tracer_provider.assert_not_called()


def test_shutdown_telemetry():
    """shutdown_telemetry calls provider.shutdown()."""
    from app.services.telemetry import init_telemetry, shutdown_telemetry

        with patch("app.services.telemetry.TracerProvider") as mock_provider_cls, \
          patch("app.services.telemetry.trace"), \
          patch("app.services.telemetry.BatchSpanProcessor"), \
          patch("app.services.telemetry.OTLPSpanExporter"):
        mock_provider = MagicMock()
        mock_provider_cls.return_value = mock_provider
        init_telemetry(enabled=True, endpoint="http://localhost:4317", service_name="test")
        shutdown_telemetry()
        mock_provider.shutdown.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_telemetry.py -v"`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement telemetry module**

Create `backend/app/services/telemetry.py`:

```python
"""OpenTelemetry tracing initialization."""
from __future__ import annotations

import structlog
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = structlog.get_logger(__name__)

_provider: TracerProvider | None = None


def init_telemetry(
    *,
    enabled: bool,
    endpoint: str,
    service_name: str,
) -> None:
    """Initialize OTel TracerProvider with OTLP exporter."""
    global _provider

    if not enabled:
        logger.info("telemetry.disabled")
        return

    resource = Resource.create({"service.name": service_name})
    _provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    _provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(_provider)
    logger.info("telemetry.initialized", endpoint=endpoint, service_name=service_name)


def shutdown_telemetry() -> None:
    """Gracefully shut down the TracerProvider."""
    global _provider
    if _provider is not None:
        _provider.shutdown()
        _provider = None
        logger.info("telemetry.shutdown")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_telemetry.py -v"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/telemetry.py backend/tests/unit/test_telemetry.py
git commit -m "feat(telemetry): add OTel TracerProvider with OTLP/gRPC exporter for Tempo"
```

---

### Task 9: Wire everything into main.py

**Files:**

- Modify: `backend/app/main.py`

- [ ] **Step 1: Add imports and middleware**

In `backend/app/main.py`:

Add imports:

```python
from app.api.metrics import router as metrics_router
from app.services.telemetry import init_telemetry, shutdown_telemetry
from app.middleware.observability import ObservabilityMiddleware
```

In the `lifespan` function, after `configure_logging(settings.log_level)` and before the `try:` block, add:

```python
    init_telemetry(
        enabled=settings.otel_enabled,
        endpoint=settings.otel_exporter_otlp_endpoint,
        service_name=settings.otel_service_name,
    )
```

In the `finally` block of lifespan, before `_close_app_resources`:

```python
        shutdown_telemetry()
```

At the bottom of the file, change the middleware registration and add metrics router:

```python
app = FastAPI(title="ProxyMind API", version="0.1.0", lifespan=lifespan)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(ObservabilityMiddleware)
app.include_router(admin_router)
app.include_router(profile_admin_router)
app.include_router(chat_router)
app.include_router(profile_chat_router)
app.include_router(health_router)
app.include_router(metrics_router)
```

Note: In Starlette/FastAPI, `add_middleware` wraps in reverse order — the last added is the outermost. So `ObservabilityMiddleware` added second means it wraps `RateLimitMiddleware`, which is the desired order.

- [ ] **Step 2: Run existing app tests**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_app_main.py tests/test_health.py -v"`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(observability): wire ObservabilityMiddleware, telemetry, and /metrics into FastAPI app"
```

---

### Task 10: Docker Compose — Prometheus, Grafana, Tempo

**Files:**

- Modify: `docker-compose.yml`
- Create: `config/prometheus/prometheus.yml`
- Create: `config/tempo/tempo.yaml`
- Create: `config/grafana/provisioning/datasources.yaml`
- Create: `config/grafana/provisioning/dashboards.yaml`
- Create: `config/grafana/dashboards/proxymind-overview.json`

- [ ] **Step 1: Create Prometheus config**

Create `config/prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "proxymind-api"
    static_configs:
      - targets: ["api:8000"]
    metrics_path: /metrics
```

- [ ] **Step 2: Create Tempo config**

Create `config/tempo/tempo.yaml`:

```yaml
server:
  http_listen_port: 3200

distributor:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: "0.0.0.0:4317"

storage:
  trace:
    backend: local
    local:
      path: /var/tempo/traces
    wal:
      path: /var/tempo/wal

metrics_generator:
  storage:
    path: /var/tempo/generator/wal
```

- [ ] **Step 3: Create Grafana provisioning configs**

Create `config/grafana/provisioning/datasources.yaml`:

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false

  - name: Tempo
    type: tempo
    access: proxy
    url: http://tempo:3200
    editable: false
```

Create `config/grafana/provisioning/dashboards.yaml`:

```yaml
apiVersion: 1

providers:
  - name: ProxyMind
    orgId: 1
    folder: ProxyMind
    type: file
    disableDeletion: false
    editable: true
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: false
```

- [ ] **Step 4: Create Grafana dashboard JSON**

Create `config/grafana/dashboards/proxymind-overview.json`:

```json
{
  "annotations": { "list": [] },
  "editable": true,
  "fiscalYearStartMonth": 0,
  "graphTooltip": 1,
  "id": null,
  "links": [],
  "panels": [
    {
      "title": "Request Rate (req/s)",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 0 },
      "targets": [
        {
          "expr": "sum(rate(http_requests_total[5m])) by (status_code)",
          "legendFormat": "{{status_code}}",
          "refId": "A"
        }
      ],
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": {
        "defaults": { "unit": "reqps" },
        "overrides": []
      }
    },
    {
      "title": "Error Rate (4xx/5xx)",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 0 },
      "targets": [
        {
          "expr": "sum(rate(http_requests_total{status_code=~\"4..|5..\"}[5m])) by (status_code)",
          "legendFormat": "{{status_code}}",
          "refId": "A"
        }
      ],
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": {
        "defaults": { "unit": "reqps" },
        "overrides": []
      }
    },
    {
      "title": "Request Latency (p50/p95/p99)",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 8 },
      "targets": [
        {
          "expr": "histogram_quantile(0.50, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))",
          "legendFormat": "p50",
          "refId": "A"
        },
        {
          "expr": "histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))",
          "legendFormat": "p95",
          "refId": "B"
        },
        {
          "expr": "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket[5m])) by (le))",
          "legendFormat": "p99",
          "refId": "C"
        }
      ],
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": {
        "defaults": { "unit": "s" },
        "overrides": []
      }
    },
    {
      "title": "Chat Responses",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 12, "y": 8 },
      "targets": [
        {
          "expr": "sum(rate(chat_responses_total[5m])) by (status)",
          "legendFormat": "{{status}}",
          "refId": "A"
        }
      ],
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": {
        "defaults": { "unit": "reqps" },
        "overrides": []
      }
    },
    {
      "title": "Chat Latency (p50/p95/p99)",
      "type": "timeseries",
      "gridPos": { "h": 8, "w": 12, "x": 0, "y": 16 },
      "targets": [
        {
          "expr": "histogram_quantile(0.50, sum(rate(chat_response_latency_seconds_bucket[5m])) by (le))",
          "legendFormat": "p50",
          "refId": "A"
        },
        {
          "expr": "histogram_quantile(0.95, sum(rate(chat_response_latency_seconds_bucket[5m])) by (le))",
          "legendFormat": "p95",
          "refId": "B"
        },
        {
          "expr": "histogram_quantile(0.99, sum(rate(chat_response_latency_seconds_bucket[5m])) by (le))",
          "legendFormat": "p99",
          "refId": "C"
        }
      ],
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": {
        "defaults": { "unit": "s" },
        "overrides": []
      }
    },
    {
      "title": "Rate Limit Hits",
      "type": "stat",
      "gridPos": { "h": 4, "w": 4, "x": 12, "y": 16 },
      "targets": [
        {
          "expr": "sum(rate(rate_limit_hits_total[5m]))",
          "refId": "A"
        }
      ],
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": {
        "defaults": { "unit": "reqps" },
        "overrides": []
      }
    },
    {
      "title": "Queue Depth",
      "type": "stat",
      "gridPos": { "h": 4, "w": 4, "x": 16, "y": 16 },
      "targets": [
        {
          "expr": "arq_queue_depth",
          "refId": "A"
        }
      ],
      "datasource": { "type": "prometheus", "uid": "prometheus" }
    },
    {
      "title": "Audit Activity",
      "type": "stat",
      "gridPos": { "h": 4, "w": 4, "x": 20, "y": 16 },
      "targets": [
        {
          "expr": "sum(rate(audit_logs_total[5m]))",
          "refId": "A"
        }
      ],
      "datasource": { "type": "prometheus", "uid": "prometheus" },
      "fieldConfig": {
        "defaults": { "unit": "reqps" },
        "overrides": []
      }
    }
  ],
  "schemaVersion": 39,
  "tags": ["proxymind"],
  "templating": { "list": [] },
  "time": { "from": "now-1h", "to": "now" },
  "title": "ProxyMind Overview",
  "uid": "proxymind-overview"
}
```

- [ ] **Step 5: Add services to docker-compose.yml**

Add before the `volumes:` section at the bottom of `docker-compose.yml`:

```yaml
prometheus:
  image: prom/prometheus:v3.10.0
  ports:
    - "9090:9090"
  volumes:
    - ./config/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    - prometheus-data:/prometheus
  depends_on:
    api:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "wget", "-qO-", "http://127.0.0.1:9090/-/healthy"]
    interval: 15s
    timeout: 5s
    retries: 5
    start_period: 10s

tempo:
  image: grafana/tempo:2.10.3
  ports:
    - "4317:4317"
    - "3200:3200"
  volumes:
    - ./config/tempo/tempo.yaml:/etc/tempo/tempo.yaml:ro
    - tempo-data:/var/tempo
  command: ["-config.file=/etc/tempo/tempo.yaml"]
  healthcheck:
    test: ["CMD", "wget", "-qO-", "http://127.0.0.1:3200/ready"]
    interval: 15s
    timeout: 5s
    retries: 5
    start_period: 10s

grafana:
  image: grafana/grafana:12.4.1
  ports:
    - "3000:3000"
  environment:
    GF_SECURITY_ADMIN_PASSWORD: admin
    GF_AUTH_ANONYMOUS_ENABLED: "true"
    GF_AUTH_ANONYMOUS_ORG_ROLE: Viewer
  volumes:
    - ./config/grafana/provisioning:/etc/grafana/provisioning:ro
    - ./config/grafana/dashboards:/var/lib/grafana/dashboards:ro
    - grafana-data:/var/lib/grafana
  depends_on:
    prometheus:
      condition: service_healthy
    tempo:
      condition: service_healthy
  healthcheck:
    test: ["CMD", "wget", "-qO-", "http://127.0.0.1:3000/api/health"]
    interval: 15s
    timeout: 5s
    retries: 5
    start_period: 20s
```

Add to the `volumes:` section:

```yaml
prometheus-data:
tempo-data:
grafana-data:
```

- [ ] **Step 6: Verify docker-compose config is valid**

Run:

```bash
docker compose config --quiet
```

Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add docker-compose.yml config/prometheus/ config/tempo/ config/grafana/
git commit -m "feat(infra): add Prometheus, Grafana, and Tempo to Docker Compose with provisioned configs"
```

---

### Task 11: Wire AuditService into chat API dependencies

**Files:**

- Modify: `backend/app/api/dependencies.py:160-171`

ChatService is constructed in `backend/app/api/dependencies.py`, NOT in `chat.py`.

- [ ] **Step 1: Add AuditService to ChatService construction**

In `backend/app/api/dependencies.py`, add import:

```python
from app.services.audit import AuditService
```

At line ~160, where `ChatService(...)` is constructed, add the `audit_service` parameter:

```python
    return ChatService(
        session=session,
        snapshot_service=snapshot_service,
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        query_rewrite_service=query_rewrite_service,
        context_assembler=context_assembler,
        min_retrieved_chunks=request.app.state.settings.min_retrieved_chunks,
        max_citations_per_response=request.app.state.settings.max_citations_per_response,
        conversation_memory_service=conversation_memory_service,
        summary_enqueuer=summary_enqueuer,
        audit_service=AuditService(),
    )
```

- [ ] **Step 2: Run full test suite**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/ -v --timeout=60"`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/dependencies.py
git commit -m "feat(audit): wire AuditService into ChatService via dependencies.py"
```

---

### Task 12: OTel auto-instrumentation for FastAPI, httpx, SQLAlchemy, Redis

**Files:**

- Modify: `backend/app/core/telemetry.py`

**Instrumentation binding model:**

All four instrumentors use **global monkey-patching** — they intercept library calls at the module level, not at the instance level. This means:

- `init_telemetry()` is called **during FastAPI lifespan startup** (Task 9), which runs before the first request but after the app object is created.
- `FastAPIInstrumentor.instrument()` — patches ASGI internals globally. Works without an `app` reference because it hooks into Starlette's base classes. The TracerProvider is already set via `trace.set_tracer_provider()` before this call.
- `HTTPXClientInstrumentor().instrument()` — patches `httpx.AsyncClient` class globally. All httpx clients created after this point (including those in `app.state`) produce spans.
- `SQLAlchemyInstrumentor().instrument()` — in OTel SDK ≥0.45b0, calling without `engine=` patches `sqlalchemy.create_engine` and `create_async_engine` globally. Engines created in lifespan startup (after telemetry init) are automatically instrumented.
- `RedisInstrumentor().instrument()` — patches `redis.asyncio.Redis` globally.

**Ordering in lifespan:** `init_telemetry()` (which calls `_instrument_libraries()`) MUST be called before `create_database_engine()`, `Redis.from_url()`, and `httpx.AsyncClient()` construction. In the current `main.py` lifespan, telemetry init is placed before the `try:` block that creates these clients (Task 9), so this ordering is correct.

- [ ] **Step 1: Add auto-instrumentation to init_telemetry**

Extend `backend/app/core/telemetry.py` — add instrumentation after setting the tracer provider:

```python
def _instrument_libraries() -> None:
    """Enable auto-instrumentation for key libraries via global monkey-patching.

    Called after TracerProvider is set. All instrumentors patch at the module level,
    so any client/engine created after this point will produce spans automatically.
    """
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument()
    except ImportError:
        logger.debug("telemetry.fastapi_instrumentor_unavailable")

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
    except ImportError:
        logger.debug("telemetry.httpx_instrumentor_unavailable")

    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument()
    except ImportError:
        logger.debug("telemetry.sqlalchemy_instrumentor_unavailable")

    try:
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        RedisInstrumentor().instrument()
    except ImportError:
        logger.debug("telemetry.redis_instrumentor_unavailable")
```

Call `_instrument_libraries()` at the end of `init_telemetry` (only when enabled).

- [ ] **Step 2: Run tests**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_telemetry.py -v"`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/core/telemetry.py
git commit -m "feat(telemetry): add OTel auto-instrumentation for FastAPI, httpx, SQLAlchemy, Redis"
```

---

### Task 13: Worker telemetry + correlation ID propagation

**Files:**

- Modify: `backend/app/workers/main.py`
- Modify: `backend/app/workers/run.py`
- Modify: `backend/app/api/dependencies.py` (enqueue points)

- [ ] **Step 1: Add telemetry init/shutdown to worker lifecycle**

In `backend/app/workers/main.py`, in `on_startup`:

```python
from app.core.logging import configure_logging
from app.core.telemetry import init_telemetry

configure_logging(settings.log_level)
init_telemetry(
    enabled=settings.otel_enabled,
    endpoint=settings.otel_exporter_otlp_endpoint,
    service_name="proxymind-worker",
)
```

Add `on_shutdown` function (or extend existing if present):

```python
async def on_shutdown(ctx: dict[str, Any]) -> None:
    from app.core.telemetry import shutdown_telemetry
    shutdown_telemetry()
    # ... existing cleanup
```

Wire `on_shutdown` in `WorkerSettings`:

```python
class WorkerSettings:
    on_startup = on_startup
    on_shutdown = on_shutdown
    # ... rest of settings
```

- [ ] **Step 2: Pass correlation_id when enqueuing arq jobs**

In `backend/app/api/dependencies.py`, where arq jobs are enqueued, pass the current request_id:

```python
from app.core.logging import request_id_var
```

In the `summary_enqueuer` closure and any other `arq_pool.enqueue_job` calls, add `correlation_id` as a regular kwarg:

```python
    async def summary_enqueuer(session_id: str, window_start_message_id: str | None) -> None:
        await arq_pool.enqueue_job(
            "generate_session_summary",
            session_id,
            window_start_message_id,
            _job_id=f"summary:{session_id}",
            correlation_id=request_id_var.get(),
        )
```

**Important:** arq's `ctx` dict is worker-constructed and has no enqueue-to-ctx pipeline. Extra kwargs (like `correlation_id`) are serialized into the job payload and arrive as **regular keyword arguments** to the task function — not in `ctx`. The task function signature must accept `correlation_id=None`. Do NOT use underscore-prefixed names like `_correlation_id` unless they match arq's six reserved params (`_job_id`, `_queue_name`, `_defer_until`, `_defer_by`, `_expires`, `_job_try`); any other underscore-prefixed kwarg also flows through as a regular kwarg but looks misleadingly like a framework parameter.

- [ ] **Step 3: Bind correlation_id in worker tasks**

Each worker task function must accept `correlation_id=None` as a kwarg and bind it:

```python
from app.core.logging import request_id_var

async def process_ingestion(ctx, task_id: str, *, correlation_id: str | None = None):
    cid = correlation_id or str(uuid.uuid4())
    token = request_id_var.set(cid)
    try:
        # ... task body (unchanged)
    finally:
        request_id_var.reset(token)
```

Apply the same pattern to `generate_session_summary`, `process_batch_embed`, and any other task functions. This ensures all structlog entries within the worker task carry the `request_id` from the original API request.

**Note:** Logging is configured once in `on_startup` (Step 1). Do NOT also configure it in `run.py` — single point of ownership avoids double-initialization.

- [ ] **Step 4: Run existing worker tests**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/workers/ -v"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/workers/main.py backend/app/api/dependencies.py
git commit -m "feat(telemetry): add OTel tracing and correlation ID propagation to arq worker"
```

---

### Task 14: Integration test — full chat flow produces audit record

**Files:**

- Create: `backend/tests/integration/test_audit_integration.py`

- [ ] **Step 1: Write integration test**

Create `backend/tests/integration/test_audit_integration.py`:

```python
"""Integration test: chat flow writes an audit_logs record."""
import pytest
from sqlalchemy import select, text

from app.db.models.operations import AuditLog


@pytest.mark.integration
async def test_chat_stream_creates_audit_record(
    async_session,
    chat_service_with_audit,
    active_snapshot_with_chunks,
):
    """After a successful streaming chat response, an audit record exists in audit_logs."""
    session = await chat_service_with_audit.create_session()
    events = []
    async for event in chat_service_with_audit.stream_answer(
        session_id=session.id,
        text="Tell me about the uploaded document",
    ):
        events.append(event)

    # Verify audit log was created
    result = await async_session.execute(
        select(AuditLog).where(AuditLog.session_id == session.id)
    )
    audit_records = list(result.scalars().all())
    assert len(audit_records) == 1

    record = audit_records[0]
    assert record.agent_id == session.agent_id
    assert record.session_id == session.id
    assert record.snapshot_id is not None
    assert record.config_commit_hash is not None
    assert record.config_content_hash is not None
    assert record.latency_ms >= 0
```

Note: This test requires the same fixtures used by existing chat integration tests. The `chat_service_with_audit` fixture wraps the standard ChatService construction with `audit_service=AuditService()`. Adapt the fixture from `tests/integration/test_chat_api.py` or `test_chat_sse.py`.

- [ ] **Step 2: Run integration test**

Run: `make backend-exec-isolated BACKEND_CMD="python -m pytest tests/integration/test_audit_integration.py -v"`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/integration/test_audit_integration.py
git commit -m "test(audit): add integration test for chat flow audit record creation"
```

---

### Task 15: Smoke test — docker compose up with full observability stack

**Files:** No new files — manual verification.

- [ ] **Step 1: Start the full stack**

Run:

```bash
docker compose up -d
```

Wait for all services to be healthy:

```bash
docker compose ps
```

Expected: all services show "healthy" or "running".

- [ ] **Step 2: Verify /metrics endpoint**

Run:

```bash
curl -s http://localhost:8000/metrics | head -20
```

Expected: Prometheus text format output with `http_requests_total`, `http_request_duration_seconds`, etc.

- [ ] **Step 3: Verify Prometheus is scraping**

Run:

```bash
curl -s http://localhost:9090/api/v1/targets | python -m json.tool | grep proxymind
```

Expected: target with `"health": "up"`.

- [ ] **Step 4: Verify Grafana is running with dashboard**

Open `http://localhost:3000` in browser. Navigate to Dashboards → ProxyMind → ProxyMind Overview.
Expected: dashboard loads (may show "No data" if no traffic yet).

- [ ] **Step 5: Verify Tempo is accepting traces**

Run:

```bash
curl -s http://localhost:3200/ready
```

Expected: "ready" response.

- [ ] **Step 6: Send a test chat message and verify end-to-end**

Send a chat message, then verify:

- `/metrics` shows incremented counters
- Grafana dashboard shows data points
- Grafana Explore → Tempo shows traces for the request

- [ ] **Step 7: Commit any final fixes**

If any configuration adjustments were needed during smoke test, commit them.
