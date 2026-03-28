## Purpose

Define request correlation, structured logging context, and request-level metric recording. Introduced by S7-02.

### Requirement: X-Request-ID generation and propagation

The system SHALL provide an `ObservabilityMiddleware` class in `backend/app/middleware/observability.py` implemented as a pure ASGI middleware. For every HTTP request, the middleware SHALL check for a client-provided `X-Request-ID` header. If present, the middleware SHALL use the provided value. If absent, the middleware SHALL generate a new UUID4 value. The `X-Request-ID` SHALL be set as a response header on all HTTP responses. Non-HTTP scopes (e.g., WebSocket, lifespan) SHALL be passed through without modification.

#### Scenario: Generates X-Request-ID when absent

- **WHEN** a client sends an HTTP request without an `X-Request-ID` header
- **THEN** the response SHALL include an `X-Request-ID` header with a valid UUID4 value

#### Scenario: Preserves client-provided X-Request-ID

- **WHEN** a client sends an HTTP request with `X-Request-ID: 550e8400-e29b-41d4-a716-446655440000`
- **THEN** the response SHALL include `X-Request-ID: 550e8400-e29b-41d4-a716-446655440000` (same value)

#### Scenario: Non-HTTP scope passthrough

- **WHEN** a non-HTTP scope (e.g., WebSocket) is received
- **THEN** the middleware SHALL pass it through to the next ASGI app without modification
- **AND** SHALL NOT crash or raise an exception

---

### Requirement: Request ID stored in contextvars

The middleware SHALL store the `request_id` in a `contextvars.ContextVar` named `request_id_var` (defined in `backend/app/core/logging.py`). The context variable SHALL be set before the request handler executes and cleared after the response completes via `clear_request_context()`.

#### Scenario: request_id available in contextvars during request

- **WHEN** the middleware processes an HTTP request
- **THEN** `request_id_var.get()` SHALL return the request ID (generated or client-provided) within the request handler scope

#### Scenario: request_id reset after response

- **WHEN** the response completes
- **THEN** the request-scoped context SHALL be cleared via `clear_request_context()`
- **AND** subsequent code outside the request scope SHALL NOT see the previous request's ID

---

### Requirement: Structlog processors for request_id, trace_id, and span_id

The structlog configuration in `backend/app/core/logging.py` SHALL include two additional processors:

1. `add_request_context` -- reads `request_id` from `request_id_var` contextvars and injects it into every log entry. When `request_id_var` is `None` (no active request), the field SHALL be omitted.
2. `add_trace_context` -- reads `trace_id` and `span_id` from the current OpenTelemetry span context via `opentelemetry.trace.get_current_span()` and injects them into every log entry as zero-padded hex strings. When OTel is not available (ImportError) or no active span exists, the fields SHALL be omitted.

The processors SHALL be added to the structlog processor chain after `TimeStamper` and before `redact_sensitive_fields`.

#### Scenario: request_id injected into log entries

- **WHEN** a structlog log entry is created during an HTTP request
- **THEN** the log entry SHALL contain a `request_id` field matching the current request's X-Request-ID

#### Scenario: request_id omitted outside request scope

- **WHEN** a structlog log entry is created outside an HTTP request (e.g., during startup)
- **THEN** the log entry SHALL NOT contain a `request_id` field

#### Scenario: trace_id and span_id injected when OTel is active

- **WHEN** a structlog log entry is created within an OTel span
- **THEN** the log entry SHALL contain `trace_id` (32-char hex) and `span_id` (16-char hex) fields

#### Scenario: trace_id and span_id omitted when OTel is disabled

- **WHEN** OTel is disabled (`OTEL_ENABLED=false`) and a structlog log entry is created
- **THEN** the log entry SHALL NOT contain `trace_id` or `span_id` fields
- **AND** no ImportError SHALL be raised

---

### Requirement: Request timing for Prometheus metrics

The middleware SHALL measure request latency using `time.perf_counter()` at the start and end of each HTTP request. After the response completes, the middleware SHALL call `record_request()` from `app.services.metrics` with the method, path, status code, and duration. The middleware SHALL prefer the resolved route template from `request.scope["route"]` for the `path` label and SHALL fall back to the raw path only when no route template is available.

#### Scenario: Request metrics recorded on success

- **WHEN** an HTTP request completes with status 200
- **THEN** `record_request()` SHALL be called with `method`, `path`, `status_code=200`, and `duration` (in seconds)

#### Scenario: Request metrics recorded on error

- **WHEN** an HTTP request completes with status 500
- **THEN** `record_request()` SHALL be called with `status_code=500`

#### Scenario: Metrics recorded even when handler raises

- **WHEN** the request handler raises an unhandled exception
- **THEN** `record_request()` SHALL still be called (in the `finally` block)
- **AND** the `status_code` SHALL default to 500

#### Scenario: Metrics import failure is silent

- **WHEN** the `app.services.metrics` module is not available (ImportError)
- **THEN** the middleware SHALL silently skip metrics recording
- **AND** the request SHALL proceed normally

---

### Requirement: Middleware ordering

The `ObservabilityMiddleware` SHALL be the outermost middleware in the FastAPI application. In Starlette/FastAPI, the last middleware added via `app.add_middleware()` is the outermost. The ordering SHALL be:

1. `ObservabilityMiddleware` (outermost -- wraps everything including rate limiting)
2. `RateLimitMiddleware`
3. Router handlers

This ensures that all requests -- including rate-limited ones -- are measured, correlated, and traced.

#### Scenario: ObservabilityMiddleware wraps RateLimitMiddleware

- **WHEN** a request is rate-limited (429 response)
- **THEN** the `X-Request-ID` header SHALL still be present in the 429 response
- **AND** the request SHALL be counted in Prometheus metrics

#### Scenario: Middleware order in main.py

- **WHEN** `main.py` is inspected
- **THEN** `app.add_middleware(RateLimitMiddleware)` SHALL appear before `app.add_middleware(ObservabilityMiddleware)` (so that ObservabilityMiddleware is outermost)

---

## Test Coverage

### CI tests (deterministic)

- **X-Request-ID generation test**: send request without header, verify response contains a valid UUID in `X-Request-ID`.
- **X-Request-ID preservation test**: send request with custom `X-Request-ID`, verify response echoes it.
- **Non-HTTP passthrough test**: verify WebSocket scope does not crash the middleware.
- **Structlog request_id injection test**: verify log entries contain `request_id` during request.
- **Structlog trace_id injection test**: verify `add_trace_context` adds `trace_id`/`span_id` when OTel span is active.
- **Structlog trace_id omission test**: verify `add_trace_context` gracefully handles ImportError or no active span.
