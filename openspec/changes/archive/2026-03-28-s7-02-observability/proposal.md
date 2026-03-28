## Story

**S7-02: Observability — audit logging + monitoring**

Verification criteria from plan:

- Conversation produces audit records with full data (snapshot_id, source_ids, config hashes, token counts, latency)
- Dashboard shows system metrics (request rate, error rate, latency percentiles, queue depth)
- Correlated request traces visible in Grafana (API and worker are separate trace trees linked by correlation_id/request_id; true end-to-end propagation through Redis/arq is out of scope)

## Why

Every twin response must be reproducible for debugging, compliance, and eval purposes — the audit_logs table exists but no code writes to it. The system has no metrics exposure, no distributed tracing, and no correlation IDs linking logs across request lifecycle. Without observability, diagnosing production issues requires manual log grep with no structured context.

## What Changes

- Implement AuditService that writes audit records after every chat response finalization (complete, partial, failed)
- Add ObservabilityMiddleware with X-Request-ID generation/propagation and Prometheus request metrics
- Add structlog processors for request_id + OTel trace_id/span_id correlation
- Expose GET /metrics endpoint in Prometheus text format for private-network scrapers and optional bearer-authenticated clients
- Initialize OpenTelemetry tracing with OTLP/gRPC export to Grafana Tempo
- Auto-instrument FastAPI, httpx, SQLAlchemy, Redis via OTel instrumentors
- Add Prometheus, Grafana, and Tempo services to Docker Compose with provisioned dashboards
- Propagate correlation IDs from API requests to arq worker tasks

## Capabilities

### New Capabilities

- `audit-logging`: AuditService writes audit_logs records for every chat response (complete/partial/failed) with snapshot_id, source_ids, config hashes, token counts, latency_ms
- `prometheus-metrics`: Prometheus metric definitions (http_requests_total, http_request_duration_seconds, chat_responses_total, chat_response_latency_seconds, rate_limit_hits_total, arq_queue_depth, audit_logs_total) and GET /metrics endpoint
- `otel-tracing`: OpenTelemetry TracerProvider with OTLP/gRPC exporter, auto-instrumentation for FastAPI/httpx/SQLAlchemy/Redis, Grafana Tempo as trace backend
- `observability-middleware`: X-Request-ID generation/propagation, structlog correlation (request_id + trace_id + span_id), request timing
- `monitoring-infrastructure`: Docker Compose services for Prometheus, Grafana, Tempo with provisioned data sources and dashboard

### Modified Capabilities

- `chat-dialogue`: ChatService gains \_log_audit calls at all terminal message states; save_partial_on_disconnect and save_failed_on_timeout load session context for audit; CHAT_RESPONSES_TOTAL metric incremented on status transitions; AuditService is now a required dependency
- `chat-rate-limiting`: RateLimitMiddleware increments rate_limit_hits_total Prometheus counter on rejection
- `infrastructure`: Docker Compose gains prometheus, grafana, tempo services with monitoring/ volumes; Tempo OTLP ingest stays internal to the Compose network
- `background-tasks`: Worker on_startup initializes telemetry; task functions accept correlation_id kwarg for log correlation; arq enqueue calls pass correlation_id from request context

## Impact

- **Backend code**: New files (audit.py, metrics.py, telemetry.py, observability.py, api/metrics.py). Modified files (chat.py, dependencies.py, config.py, logging.py, rate_limit.py, workers/main.py, db model for `AuditLog`). One Alembic migration (add `status` column to `audit_logs`)
- **Dependencies**: prometheus-client, opentelemetry-api/sdk/exporter-otlp, four OTel instrumentor packages
- **Infrastructure**: 3 new Docker Compose services (prometheus, grafana, tempo), 3 new config directories, 3 new named volumes
- **API surface**: New GET /metrics endpoint with private-network access control and optional bearer auth. X-Request-ID header added to all responses
- **Operational changes**: Prometheus scraping remains internal to the Docker network, and ChatService now requires an AuditService instance for reproducibility guarantees
