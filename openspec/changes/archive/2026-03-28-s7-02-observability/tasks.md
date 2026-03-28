## 1. Dependencies and Configuration

- [x] 1.1 Add observability dependencies to pyproject.toml (prometheus-client, opentelemetry-api/sdk/exporter-otlp, four OTel instrumentor packages)
- [x] 1.2 Add OTel settings to Settings class (otel_enabled, otel_exporter_otlp_endpoint, otel_service_name) with tests
- [x] 1.3 Rebuild backend container to verify dependency resolution

## 2. Observability Middleware and Structlog

- [x] 2.1 Add request_id_var contextvars to logging.py
- [x] 2.2 Add add_request_context structlog processor (injects request_id from contextvars)
- [x] 2.3 Add add_trace_context structlog processor (injects trace_id + span_id from OTel span context)
- [x] 2.4 Implement ObservabilityMiddleware (X-Request-ID generation/propagation, request timing, metrics recording)
- [x] 2.5 Write unit tests for ObservabilityMiddleware (generates ID when absent, preserves client ID, non-HTTP passthrough)
- [x] 2.6 Write unit tests for structlog request_id injection (verify request_id appears in log output when set in contextvars)
- [x] 2.7 Write unit tests for structlog trace_id/span_id injection (verify trace context appears in log output when OTel span is active)

## 3. Prometheus Metrics

- [x] 3.1 Create metrics.py with metric definitions (http_requests_total, http_request_duration_seconds, chat_responses_total, chat_response_latency_seconds, rate_limit_hits_total, arq_queue_depth, audit_logs_total) and record_request helper with path normalization
- [x] 3.2 Create api/metrics.py with GET /metrics endpoint (Prometheus text format, restricted to private-network clients with optional bearer auth)
- [x] 3.3 Write unit tests for metrics endpoint and record_request
- [x] 3.4 Add rate_limit_hits_total increment to RateLimitMiddleware on rejection

## 4. Audit Service

- [x] 4.1 Add `status` column (String, nullable) to AuditLog model and create Alembic migration
- [x] 4.2 Implement AuditService with log_response method (writes AuditLog record including status field, increments audit_logs_total, structlog event)
- [x] 4.3 Write unit tests for AuditService (correct fields including status, Prometheus counter increment, noop scenarios)

## 5. ChatService Audit Integration

- [x] 5.1 Add required audit_service parameter to ChatService.**init**
- [x] 5.2 Implement \_log_audit private method with exception isolation
- [x] 5.3 Add \_log_audit calls in stream_answer complete path (after session commit, before yield citations)
- [x] 5.4 Add \_log_audit calls in answer method (success and refusal paths)
- [x] 5.5 Add \_log_audit calls in stream_answer failed path (except block after commit)
- [x] 5.6 Add audit to save_partial_on_disconnect (load session from DB, call \_log_audit after status update)
- [x] 5.7 Add audit to save_failed_on_timeout (same pattern as partial)
- [x] 5.8 Add CHAT_RESPONSES_TOTAL metric increment at all terminal states
- [x] 5.9 Add start_time = time.perf_counter() at start of answer() and stream_answer()
- [x] 5.10 Write unit test for \_log_audit delegation (correct field mapping, noop when None)
- [x] 5.11 Wire AuditService into ChatService construction in dependencies.py
- [x] 5.12 Observe CHAT_RESPONSE_LATENCY_SECONDS histogram at all terminal states (latency_ms / 1000)

## 6. OpenTelemetry Tracing

- [x] 6.1 Implement telemetry.py with init_telemetry (TracerProvider, OTLP/gRPC exporter, kill switch) and shutdown_telemetry
- [x] 6.2 Add \_instrument_libraries for global auto-instrumentation (FastAPI, httpx, SQLAlchemy, Redis)
- [x] 6.3 Write unit tests for telemetry init/shutdown (mock provider, verify setup/teardown, disabled noop)

## 7. App Wiring

- [x] 7.1 Add ObservabilityMiddleware to main.py (outermost — added after RateLimitMiddleware so it wraps it)
- [x] 7.2 Add telemetry init in lifespan startup (before client/engine creation) and shutdown in finally block
- [x] 7.3 Add metrics_router to app router list
- [x] 7.4 Run existing app and health tests to verify nothing broke

## 8. Worker Telemetry and Correlation

- [x] 8.1 Add telemetry init/shutdown to worker on_startup/on_shutdown in workers/main.py (service.name=proxymind-worker)
- [x] 8.2 Add configure_logging call in worker on_startup (single init point)
- [x] 8.3 Pass correlation_id kwarg from request_id_var when enqueuing arq jobs in dependencies.py
- [x] 8.4 Add correlation_id parameter to worker task functions and bind to request_id_var
- [x] 8.5 Create an OTel span per worker task execution (span name = task function name, attributes: correlation_id, task_name)
- [x] 8.6 Run existing worker tests to verify nothing broke
- [x] 8.7 Implement periodic arq queue depth probe (ZCARD arq:queue → arq_queue_depth gauge, 30s interval via arq cron)

## 9. Docker Compose and Monitoring Infrastructure

- [x] 9.1 Create monitoring/prometheus/prometheus.yml (scrape api:8000/metrics at 15s interval)
- [x] 9.2 Create monitoring/tempo/tempo.yml (monolithic mode, local storage, OTLP gRPC receiver on 4317, not published to the host)
- [x] 9.3 Create monitoring/grafana/provisioning/datasources/datasources.yml (Prometheus + Tempo data sources)
- [x] 9.4 Create monitoring/grafana/provisioning/dashboards/dashboards.yml (dashboard provider pointing to JSON files)
- [x] 9.5 Create monitoring/grafana/dashboards/proxymind-overview.json (Set A: request rate, error rate, latency p50/p95/p99, chat responses, chat latency, rate limit hits, aggregated queue depth, audit activity, service health via `up` metric)
- [x] 9.6 Add prometheus, tempo, grafana services to docker-compose.yml with health checks and config volumes
- [x] 9.7 Add prometheus-data, tempo-data, grafana-data named volumes
- [x] 9.8 Verify docker compose config is valid

## 10. Integration Tests

- [x] 10.1 Write integration test: full chat flow produces audit record in audit_logs (verify snapshot_id, source_ids, config hashes, latency_ms)
- [x] 10.2 Run full test suite in backend-test container

## 11. Smoke Test

- [x] 11.1 Start full stack with docker compose up
- [x] 11.2 Verify GET /metrics returns Prometheus text format with expected metric names for an allowed private-network or authenticated client
- [x] 11.3 Verify Prometheus scrape target is healthy
- [x] 11.4 Verify Grafana dashboard loads at localhost:3000
- [x] 11.5 Verify Tempo is ready at localhost:3200
- [ ] 11.6 Send test chat message and verify: metrics increment, dashboard shows data, traces visible in Grafana Explore
