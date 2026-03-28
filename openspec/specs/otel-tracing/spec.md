## Purpose

Define OpenTelemetry tracing configuration and lifecycle for the API and worker. Introduced by S7-02.

### Requirement: OTel TracerProvider initialization

The system SHALL provide an `init_telemetry()` function in `backend/app/services/telemetry.py` that initializes an OpenTelemetry `TracerProvider` with a `BatchSpanProcessor` exporting to an `OTLPSpanExporter` via gRPC. The function SHALL accept the application settings plus an optional `service_name` override. When `otel_enabled` is `False`, the function SHALL be a no-op. When `otel_enabled` is `True`, the function SHALL create a `TracerProvider` with a `Resource` containing `service.name`, normalize `http://tempo:4317`-style endpoints to the gRPC `host:port` form expected by the Python exporter, configure the OTLP exporter as insecure gRPC, and set the provider as the global tracer provider via `trace.set_tracer_provider()`.

#### Scenario: Telemetry initialized when enabled

- **WHEN** `init_telemetry(enabled=True, endpoint="http://tempo:4317", service_name="proxymind-api")` is called
- **THEN** a `TracerProvider` SHALL be created with `Resource(service.name="proxymind-api")`
- **AND** an `OTLPSpanExporter` SHALL be configured with `endpoint="tempo:4317"` and `insecure=True`
- **AND** a `BatchSpanProcessor` wrapping the exporter SHALL be added to the provider
- **AND** `trace.set_tracer_provider()` SHALL be called with the provider

#### Scenario: Telemetry disabled is a no-op

- **WHEN** `init_telemetry(enabled=False, endpoint="http://tempo:4317", service_name="proxymind-api")` is called
- **THEN** `trace.set_tracer_provider()` SHALL NOT be called
- **AND** no `TracerProvider` or exporter SHALL be created
- **AND** a structlog info event `telemetry.disabled` SHALL be emitted

---

### Requirement: OTel TracerProvider shutdown

The system SHALL provide a `shutdown_telemetry()` function that gracefully shuts down the `TracerProvider` by calling `provider.shutdown()`. Before shutdown, the function SHALL uninstrument FastAPI, SQLAlchemy, httpx, and Redis so repeated initialization does not leave stale hooks behind. Because the OpenTelemetry global tracer provider is write-once, the process SHALL treat telemetry initialization as single-use: after shutdown, the existing provider reference MAY be retained internally and subsequent re-initialization attempts in the same process SHALL be ignored with a warning instead of attempting to replace the global provider. If no provider was initialized (telemetry was disabled), `shutdown_telemetry()` SHALL be a no-op.

#### Scenario: Shutdown flushes and cleans up

- **WHEN** `shutdown_telemetry()` is called after a successful `init_telemetry(enabled=True, ...)`
- **THEN** the provider's `shutdown()` method SHALL be called
- **AND** the process SHALL mark telemetry as shut down so a second `init_telemetry()` call in the same process does not attempt to replace the global tracer provider
- **AND** a structlog info event `telemetry.shutdown` SHALL be emitted

#### Scenario: Re-initialization after shutdown is ignored

- **WHEN** `init_telemetry()` is called after `shutdown_telemetry()` in the same process
- **THEN** the function SHALL log a warning and return without calling `trace.set_tracer_provider()` again

#### Scenario: Shutdown is no-op when not initialized

- **WHEN** `shutdown_telemetry()` is called without prior `init_telemetry()` call (or after `init_telemetry(enabled=False)`)
- **THEN** no error SHALL be raised

---

### Requirement: OTel configuration via environment variables

The `Settings` class in `backend/app/core/config.py` SHALL include OTel configuration fields:

| Variable                      | Field                         | Type | Default             | Description                                                                                                                                                 |
| ----------------------------- | ----------------------------- | ---- | ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `OTEL_ENABLED`                | `otel_enabled`                | bool | `False`             | Kill switch for tracing. Default off to avoid noisy export errors when Tempo is not running. Enabled explicitly in docker-compose via environment variable. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `otel_exporter_otlp_endpoint` | str  | `http://tempo:4317` | Tempo gRPC endpoint                                                                                                                                         |
| `OTEL_SERVICE_NAME`           | `otel_service_name`           | str  | `proxymind-api`     | Service identifier                                                                                                                                          |

#### Scenario: Default OTel settings

- **WHEN** no OTel environment variables are set
- **THEN** `settings.otel_enabled` SHALL be `False`
- **AND** `settings.otel_exporter_otlp_endpoint` SHALL be `"http://tempo:4317"`
- **AND** `settings.otel_service_name` SHALL be `"proxymind-api"`

#### Scenario: OTel disabled via environment variable

- **WHEN** `OTEL_ENABLED=false` is set
- **THEN** `settings.otel_enabled` SHALL be `False`

---

### Requirement: Auto-instrumentation for framework libraries

The system SHALL enable auto-instrumentation for the following libraries using OpenTelemetry instrumentor packages:

- `opentelemetry-instrumentation-fastapi` -- instruments FastAPI routes and middleware
- `opentelemetry-instrumentation-httpx` -- instruments outgoing HTTP requests via httpx
- `opentelemetry-instrumentation-sqlalchemy` -- instruments database queries via SQLAlchemy
- `opentelemetry-instrumentation-redis` -- instruments Redis operations

Auto-instrumentation SHALL be activated during telemetry initialization (when enabled). Auto-instrumentation SHALL NOT be activated when telemetry is disabled.

#### Scenario: FastAPI auto-instrumentation active

- **WHEN** telemetry is enabled and a request is processed by FastAPI
- **THEN** an OTel span SHALL be created with `http.method` and `http.route` attributes

#### Scenario: httpx auto-instrumentation active

- **WHEN** telemetry is enabled and an outgoing httpx request is made (e.g., to embedding API)
- **THEN** an OTel span SHALL be created for the outgoing request

#### Scenario: SQLAlchemy auto-instrumentation active

- **WHEN** telemetry is enabled and a database query is executed
- **THEN** an OTel span SHALL be created for the database operation

#### Scenario: Redis auto-instrumentation active

- **WHEN** telemetry is enabled and a Redis operation is performed
- **THEN** an OTel span SHALL be created for the Redis operation

#### Scenario: No auto-instrumentation when disabled

- **WHEN** `OTEL_ENABLED=false`
- **THEN** no instrumentors SHALL be activated
- **AND** no spans SHALL be created for framework operations

---

### Requirement: Telemetry lifecycle in FastAPI lifespan

The `init_telemetry()` function SHALL be called during FastAPI lifespan startup after `configure_logging()` and inside the protected startup block, before HTTP clients and database engines are created. The `shutdown_telemetry()` function SHALL be called during FastAPI lifespan shutdown after application resources are closed and after the final `app.shutdown` log is emitted. The settings SHALL be read from the `Settings` class.

#### Scenario: Telemetry initialized at startup

- **WHEN** the FastAPI application starts
- **THEN** `init_telemetry()` SHALL be called with `enabled=settings.otel_enabled`, `endpoint=settings.otel_exporter_otlp_endpoint`, `service_name=settings.otel_service_name`

#### Scenario: Telemetry shut down on application exit

- **WHEN** the FastAPI application shuts down
- **THEN** `shutdown_telemetry()` SHALL be called after resource cleanup and after the final shutdown log

---

### Requirement: Worker telemetry with separate service name

The arq worker SHALL initialize telemetry in its `on_startup` hook with `service.name=proxymind-worker` (distinct from the API's `proxymind-api`). The worker SHALL shut down telemetry in its `on_shutdown` hook. One OTel span SHALL be created per arq task execution.

#### Scenario: Worker initializes telemetry on startup

- **WHEN** the arq worker starts via `on_startup`
- **THEN** `init_telemetry()` SHALL be called with `service_name="proxymind-worker"`

#### Scenario: Worker shuts down telemetry on exit

- **WHEN** the arq worker shuts down via `on_shutdown`
- **THEN** `shutdown_telemetry()` SHALL be called

#### Scenario: Each worker task gets its own span

- **WHEN** the worker executes a task
- **THEN** an OTel span SHALL be created for the task execution
- **AND** the span SHALL include the task name and correlation_id (if available)

---

## Test Coverage

### CI tests (deterministic)

- **init_telemetry enabled test**: mock TracerProvider, OTLPSpanExporter, BatchSpanProcessor; verify `trace.set_tracer_provider()` is called.
- **init_telemetry disabled test**: mock trace; verify `set_tracer_provider()` is NOT called.
- **shutdown_telemetry test**: init with mocked provider, then shutdown; verify `provider.shutdown()` is called.
- **shutdown_telemetry no-op test**: call `shutdown_telemetry()` without init; verify no error.
- **OTel config defaults test**: verify `Settings` defaults for `otel_enabled`, `otel_exporter_otlp_endpoint`, `otel_service_name`.
- **OTel config disabled test**: set `OTEL_ENABLED=false`, verify `settings.otel_enabled` is `False`.

### Evals (non-deterministic, manual verification)

- **End-to-end trace visibility**: send a chat message, verify a trace appears in Grafana Tempo with spans for FastAPI, httpx, SQLAlchemy.
