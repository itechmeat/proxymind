# S7-02: Observability — Audit Logging + Monitoring

## Summary

Every twin response becomes reproducible through audit logging. The system becomes observable through Prometheus metrics, Grafana dashboards, and OpenTelemetry tracing with correlation IDs across the full request lifecycle.

## Decisions Log

| # | Decision | Chosen | Why |
|---|----------|--------|-----|
| 1 | Dashboard scope | Minimal (set A) | Single-instance self-hosted; adding metrics later is trivial. Overloading the dashboard on day one is an anti-pattern. |
| 2 | Tracing backend | Grafana Tempo | Already adding Grafana for dashboards — Tempo gives unified observability (metrics + traces + dashboards) without an extra UI. Monolithic mode, one container, local disk storage. |
| 3 | OTel Collector | Direct exporter (no Collector) | YAGNI. One API + one worker — Collector adds a container with no benefit at this scale. Easy to add later. |
| 4 | Architecture approach | Layered middleware | ObservabilityMiddleware for request-level concerns (correlation ID, metrics, spans). Separate AuditService for domain-level audit records. Clean separation of concerns. |
| 5 | Audit write timing | After SSE stream finalization | All domain data (source_ids, token counts, latency) is available at message finalization. One INSERT — no need for background processing. |

## Architecture

### Layered approach

Two layers of observability, each with a single responsibility:

1. **ObservabilityMiddleware** — request-level: correlation IDs, OTel spans, Prometheus metrics, latency measurement. Wraps all requests including rate-limited ones.
2. **AuditService** — domain-level: writes audit records with full reproducibility data after each chat response finalization.

### Component diagram

```
Request → ObservabilityMiddleware (correlation ID, span, metrics)
        → RateLimitMiddleware
        → Router
        → ChatService → ... → finalize message → AuditService.log_response()
```

## Component Details

### 1. Audit Service

**File:** `backend/app/services/audit.py`

**Purpose:** Single point for writing audit records to `audit_logs` table.

**Interface:**

```python
class AuditService:
    async def log_response(
        self,
        db: AsyncSession,
        agent_id: UUID,
        session_id: UUID,
        message_id: UUID,
        snapshot_id: UUID | None,
        source_ids: list[UUID],
        model_name: str,
        token_count_prompt: int,
        token_count_completion: int,
        retrieval_chunks_count: int,
        latency_ms: int,
        config_commit_hash: str,
        config_content_hash: str,
    ) -> AuditLog: ...
```

**Call site:** In chat service, after assistant message transitions to `complete`, `partial`, or `failed`.

**No new migrations required** — `audit_logs` table already exists (migration 001).

### 2. Config Hashes (existing — no new code)

Config hashes are already computed by `PersonaLoader` and available via `PersonaContext`:

- `config_commit_hash`: resolved from `GIT_COMMIT_SHA` env var (set during Docker build).
- `config_content_hash`: SHA-256 of sorted, concatenated contents of `persona/*.md` + `config/*.md`.

Both values are already used in ChatService (`self._persona_context.config_commit_hash`, `self._persona_context.config_content_hash`) and stored on every assistant message. **No new ConfigHasher service is needed.**

### 3. Observability Middleware

**File:** `backend/app/middleware/observability.py`

**Responsibilities:**

- Generate `X-Request-ID` (UUID4) if not provided by the client.
- Bind `request_id` to structlog context via contextvars.
- Start an OTel span with attributes: `http.method`, `http.route`, `request_id`.
- Measure request latency via `time.perf_counter`.
- On response: increment Prometheus counters/histograms, set `X-Request-ID` response header.

**Middleware order in `main.py`:**

```
ObservabilityMiddleware  (outermost — wraps everything)
  → RateLimitMiddleware
    → Router handlers
```

### 4. Prometheus Metrics

**Metrics definition:** `backend/app/services/metrics.py`
**Endpoint:** `backend/app/api/metrics.py` → `GET /metrics`

**Metric set (minimal — set A):**

| Metric | Type | Labels | Source |
|--------|------|--------|--------|
| `http_requests_total` | Counter | method, path, status_code | ObservabilityMiddleware |
| `http_request_duration_seconds` | Histogram | method, path | ObservabilityMiddleware |
| `chat_responses_total` | Counter | status (complete/partial/failed) | ChatService |
| `chat_response_latency_seconds` | Histogram | — | ChatService |
| `rate_limit_hits_total` | Counter | — | RateLimitMiddleware |
| `arq_queue_depth` | Gauge | — | Periodic probe or enqueue hook |
| `audit_logs_total` | Counter | — | AuditService |

**Endpoint:** `GET /metrics` — Prometheus text exposition format. No authentication (same as `/health`). Caddy MAY restrict by IP.

### 5. OpenTelemetry Tracing

**File:** `backend/app/core/telemetry.py`

**Initialization:** Called during FastAPI lifespan startup.

**Components:**

- `TracerProvider` with `BatchSpanProcessor` → `OTLPSpanExporter` (gRPC to Tempo).
- Auto-instrumentation: `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-httpx`, `opentelemetry-instrumentation-sqlalchemy`, `opentelemetry-instrumentation-redis`.
- Resource attributes: `service.name`, `service.version`.
- Custom span attributes where available: `request_id`, `agent_id`, `session_id`.

**Configuration (env vars):**

| Variable | Default | Description |
|----------|---------|-------------|
| `OTEL_ENABLED` | `false` | Kill switch for tracing. Default off; set `OTEL_ENABLED=true` in docker-compose for api and worker. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://tempo:4317` | Tempo gRPC endpoint |
| `OTEL_SERVICE_NAME` | `proxymind-api` | Service identifier |

**Worker tracing:** Same TracerProvider initialized in `on_startup` of `backend/app/workers/main.py` with `service.name=proxymind-worker`. Shutdown in `on_shutdown`. One span per arq task execution, created in a wrapper or at the task handler level.

**Worker correlation:** When API enqueues an arq job, it passes `correlation_id=request_id_var.get()` as a regular keyword argument. arq serializes kwargs into the job payload; the worker task receives `correlation_id` as a function kwarg (not in `ctx` — arq's ctx dict is worker-constructed only). The task binds it to structlog context and `request_id_var`. If no correlation ID is present (e.g., cron-triggered tasks), the worker generates its own.

### 6. Correlation IDs + Structlog Integration

**Correlation ID flow:**

1. ObservabilityMiddleware generates or accepts `X-Request-ID`.
2. Stores it in contextvars (`request_id_var`).
3. Structlog processor reads `request_id` from contextvars → adds to every log entry.
4. A second structlog processor reads `trace_id` and `span_id` from the current OTel span context (`opentelemetry.trace.get_current_span()`) and injects them into every log entry. This links logs ↔ traces in Grafana.

**Worker correlation:**

- arq job enqueue passes `_correlation_id` from the current `request_id_var`.
- Worker task extracts `_correlation_id` from job kwargs, binds it to structlog context and `request_id_var` for the task duration.
- Worker telemetry creates a span per task; trace_id/span_id are injected into logs via the same processor.

### 7. Docker Compose — New Services

**New services added to `docker-compose.yml`:**

| Service | Image | Ports | Purpose |
|---------|-------|-------|---------|
| prometheus | `prom/prometheus:v3.10.0` | 9090 | Metrics scraping and storage |
| grafana | `grafana/grafana:12.4.1` | 3000 | Dashboards and trace visualization |
| tempo | `grafana/tempo:2.10.3` | 4317 (OTLP gRPC), 3200 (HTTP API) | Trace storage |

**Configuration files:**

```
config/
├── prometheus/
│   └── prometheus.yml        # scrape_configs: api:8000/metrics, interval 15s
├── tempo/
│   └── tempo.yaml            # monolithic mode, local storage, OTLP gRPC receiver
└── grafana/
    ├── provisioning/
    │   ├── datasources.yaml  # Prometheus + Tempo data sources
    │   └── dashboards.yaml   # dashboard provider → JSON files
    └── dashboards/
        └── proxymind-overview.json  # main dashboard (set A metrics)
```

**Grafana provisioning:** Auto-provisioned data sources and dashboards via volume-mounted config files. No manual setup required after `docker compose up`.

### 8. Grafana Dashboard Content (Set A)

The provisioned dashboard includes:

- **Request Rate** — `http_requests_total` rate by status code
- **Error Rate** — 4xx/5xx rates
- **Latency** — p50/p95/p99 from `http_request_duration_seconds`
- **Chat Responses** — `chat_responses_total` by status
- **Chat Latency** — `chat_response_latency_seconds` histogram
- **Rate Limit Hits** — `rate_limit_hits_total` rate
- **Queue Depth** — `arq_queue_depth` current value
- **Audit Activity** — `audit_logs_total` rate
- **Service Health** — up/down from scrape target status

## Dependencies (new packages)

**Backend (`pyproject.toml`):**

| Package | Purpose |
|---------|---------|
| `prometheus-client` | Prometheus metrics exposition |
| `opentelemetry-api` | OTel API |
| `opentelemetry-sdk` | OTel SDK |
| `opentelemetry-exporter-otlp` | OTLP gRPC exporter for Tempo |
| `opentelemetry-instrumentation-fastapi` | Auto-instrumentation for FastAPI |
| `opentelemetry-instrumentation-httpx` | Auto-instrumentation for httpx |
| `opentelemetry-instrumentation-sqlalchemy` | Auto-instrumentation for SQLAlchemy |
| `opentelemetry-instrumentation-redis` | Auto-instrumentation for Redis |

## Files Changed / Created

| Action | Path | Description |
|--------|------|-------------|
| Create | `backend/app/services/audit.py` | AuditService |
| Create | `backend/app/services/metrics.py` | Prometheus metric definitions |
| Create | `backend/app/api/metrics.py` | GET /metrics endpoint |
| Create | `backend/app/middleware/observability.py` | Observability middleware |
| Create | `backend/app/core/telemetry.py` | OTel TracerProvider setup |
| Modify | `backend/app/main.py` | Add ObservabilityMiddleware, telemetry init, metrics router |
| Modify | `backend/app/core/config.py` | Add OTEL_* settings |
| Modify | `backend/app/core/logging.py` | Add request_id + trace_id + span_id structlog processors |
| Modify | `backend/app/services/chat.py` | Call AuditService after message finalization (complete, partial, failed) |
| Modify | `backend/app/middleware/rate_limit.py` | Increment rate_limit_hits_total counter |
| Modify | `backend/app/api/dependencies.py` | Wire AuditService into ChatService; pass correlation_id on arq enqueue |
| Modify | `backend/app/workers/main.py` | Init/shutdown telemetry in on_startup/on_shutdown |
| Modify | `backend/app/workers/run.py` | Configure logging before worker start |
| Modify | `backend/pyproject.toml` | Add new dependencies |
| Modify | `docker-compose.yml` | Add prometheus, grafana, tempo services |
| Create | `config/prometheus/prometheus.yml` | Prometheus scrape config |
| Create | `config/tempo/tempo.yaml` | Tempo monolithic config |
| Create | `config/grafana/provisioning/datasources.yaml` | Grafana data sources |
| Create | `config/grafana/provisioning/dashboards.yaml` | Grafana dashboard provider |
| Create | `config/grafana/dashboards/proxymind-overview.json` | Main dashboard |

## Testing Strategy

**Unit tests:**

- `AuditService.log_response()` — mock AsyncSession, verify INSERT with correct fields
- Prometheus metrics — verify counters/histograms increment correctly
- Telemetry init/shutdown — verify TracerProvider created/destroyed

**Integration tests:**

- ObservabilityMiddleware via TestClient: verify `X-Request-ID` in response, structlog output contains `request_id`
- Full chat flow: send message → verify audit record created with correct snapshot_id, source_ids, config hashes
- `GET /metrics` returns Prometheus text format with expected metric names

**Docker smoke tests (manual verification):**

- `docker compose up` → Prometheus scrapes `/metrics` → metric values present
- Grafana dashboard loads with data
- Tempo receives traces (visible in Grafana Explore → Tempo)

## Out of Scope

- Infrastructure metrics (PostgreSQL connections, Redis memory, Qdrant size) — deferred, easy to add later
- Alerting rules — no alerting in v1, dashboard is sufficient for single-instance
- Log aggregation (Loki) — structured logs go to stdout, viewable via `docker compose logs`
- OTel Collector — direct export is sufficient at current scale
