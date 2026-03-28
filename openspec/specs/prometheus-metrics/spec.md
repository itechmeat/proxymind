## Purpose

Define Prometheus metrics, exposition, and queue-depth probing for runtime observability. Introduced by S7-02.

### Requirement: Prometheus metric definitions

The system SHALL define Prometheus metrics in `backend/app/services/metrics.py` using the `prometheus-client` library. The following metrics SHALL be defined:

| Metric                          | Type      | Labels                           | Source                         |
| ------------------------------- | --------- | -------------------------------- | ------------------------------ |
| `http_requests_total`           | Counter   | method, path, status_code        | ObservabilityMiddleware        |
| `http_request_duration_seconds` | Histogram | method, path                     | ObservabilityMiddleware        |
| `chat_responses_total`          | Counter   | status (complete/partial/failed) | ChatService                    |
| `chat_response_latency_seconds` | Histogram | (none)                           | ChatService                    |
| `rate_limit_hits_total`         | Counter   | (none)                           | RateLimitMiddleware            |
| `arq_queue_depth`               | Gauge     | (none)                           | Periodic probe or enqueue hook |
| `audit_logs_total`              | Counter   | (none)                           | AuditService                   |

The histogram bucket boundaries SHALL be:

- `http_request_duration_seconds`: (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
- `chat_response_latency_seconds`: (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)

#### Scenario: All metrics are defined and importable

- **WHEN** `from app.services.metrics import HTTP_REQUESTS_TOTAL, HTTP_REQUEST_DURATION_SECONDS, CHAT_RESPONSES_TOTAL, CHAT_RESPONSE_LATENCY_SECONDS, RATE_LIMIT_HITS_TOTAL, ARQ_QUEUE_DEPTH, AUDIT_LOGS_TOTAL` is executed
- **THEN** the import SHALL succeed without error
- **AND** each metric SHALL be an instance of the correct prometheus-client type (Counter, Histogram, or Gauge)

#### Scenario: Counter labels match specification

- **WHEN** `http_requests_total` is inspected
- **THEN** it SHALL have labels: `method`, `path`, `status_code`

- **WHEN** `chat_responses_total` is inspected
- **THEN** it SHALL have a single label: `status`

- **WHEN** `rate_limit_hits_total` and `audit_logs_total` are inspected
- **THEN** they SHALL have no labels

---

### Requirement: record_request helper function

The `metrics.py` module SHALL provide a `record_request()` function that increments `http_requests_total` and observes `http_request_duration_seconds` for a completed HTTP request. The function SHALL accept `method`, `path`, `status_code`, and `duration` as keyword arguments.

#### Scenario: record_request increments counter and observes histogram

- **WHEN** `record_request(method="GET", path="/test", status_code=200, duration=0.05)` is called
- **THEN** `http_requests_total{method="GET", path="/test", status_code="200"}` SHALL be incremented by 1
- **AND** `http_request_duration_seconds{method="GET", path="/test"}` SHALL observe the value 0.05

#### Scenario: status_code is stored as string label

- **WHEN** `record_request()` is called with `status_code=404`
- **THEN** the `status_code` label value SHALL be the string `"404"` (not integer)

---

### Requirement: Path normalization for cardinality control

The `record_request()` function SHALL normalize URL paths before using them as metric labels to prevent high-cardinality label explosion. UUID segments (strings of 32+ hex characters including hyphens) SHALL be replaced with `:id`.

#### Scenario: UUID path segments normalized

- **WHEN** `record_request()` is called with `path="/api/chat/sessions/550e8400-e29b-41d4-a716-446655440000/messages"`
- **THEN** the `path` label SHALL be `/api/chat/sessions/:id/messages`

#### Scenario: Non-UUID paths preserved

- **WHEN** `record_request()` is called with `path="/api/chat/sessions"`
- **THEN** the `path` label SHALL be `/api/chat/sessions` (unchanged)

#### Scenario: Root path normalized

- **WHEN** `record_request()` is called with `path="/"`
- **THEN** the `path` label SHALL be `/`

---

### Requirement: GET /metrics endpoint

The system SHALL provide a `GET /metrics` endpoint in `backend/app/api/metrics.py` that returns Prometheus metrics in text exposition format. The endpoint SHALL return `Content-Type: text/plain; version=0.0.4; charset=utf-8`. The endpoint SHALL NOT be included in the OpenAPI schema (`include_in_schema=False`). When `admin_api_key` is not configured, access SHALL be limited to private-network clients. When `admin_api_key` is configured, the endpoint SHALL require bearer authentication using that same admin API key and SHALL NOT allow a private-network bypass.

#### Scenario: Metrics endpoint returns Prometheus format

- **WHEN** `GET /metrics` is called
- **THEN** the response status SHALL be 200
- **AND** the `Content-Type` header SHALL contain `text/plain`
- **AND** the response body SHALL contain Prometheus text exposition format with `# HELP` and `# TYPE` lines

#### Scenario: Metrics endpoint includes all defined metrics

- **WHEN** `GET /metrics` is called after some requests have been processed
- **THEN** the response body SHALL contain metric names: `http_requests_total`, `http_request_duration_seconds`, `chat_responses_total`, `chat_response_latency_seconds`, `rate_limit_hits_total`, `arq_queue_depth`, `audit_logs_total`

#### Scenario: Metrics endpoint allows private-network scraping without authentication when no admin key is configured

- **WHEN** `GET /metrics` is called from a private-network client without any authentication headers
- **AND** `admin_api_key` is not configured
- **THEN** the response SHALL be 200 (not 401 or 403)

#### Scenario: Metrics endpoint rejects public unauthenticated access when no admin key is configured

- **WHEN** `GET /metrics` is called from a non-private client without authentication headers
- **AND** `admin_api_key` is not configured
- **THEN** the response SHALL be 401 or 403

#### Scenario: Metrics endpoint rejects private unauthenticated access when admin key is configured

- **WHEN** `GET /metrics` is called from a private-network client without authentication headers
- **AND** `admin_api_key` is configured
- **THEN** the response SHALL be 401

#### Scenario: Metrics endpoint allows authenticated access when admin key is configured

- **WHEN** `GET /metrics` is called with `Authorization: Bearer <admin_api_key>`
- **AND** `admin_api_key` is configured
- **THEN** the response SHALL be 200

#### Scenario: Metrics endpoint excluded from OpenAPI

- **WHEN** the OpenAPI schema is inspected at `/openapi.json`
- **THEN** the `/metrics` path SHALL NOT be present in the schema

---

### Requirement: Periodic arq queue depth probe

The system SHALL update the `arq_queue_depth` gauge by querying Redis for the arq queue length via the `ZCARD arq:queue` command. This probe SHALL be implemented as an arq cron job that runs every 30 seconds. The cron function SHALL obtain a Redis connection from the arq worker context, execute `ZCARD arq:queue`, and set the `ARQ_QUEUE_DEPTH` gauge to the returned value.

#### Scenario: arq queue depth gauge updated on schedule

- **WHEN** the arq cron job fires (every 30 seconds)
- **THEN** the worker SHALL execute `ZCARD arq:queue` against Redis
- **AND** SHALL set `ARQ_QUEUE_DEPTH` gauge to the integer value returned by `ZCARD`

#### Scenario: arq queue depth reflects actual pending jobs

- **WHEN** 5 jobs are enqueued and none have been consumed
- **AND** the cron job fires
- **THEN** `ARQ_QUEUE_DEPTH` gauge SHALL be set to 5

#### Scenario: arq queue depth is zero when queue is empty

- **WHEN** no jobs are pending in the arq queue
- **AND** the cron job fires
- **THEN** `ARQ_QUEUE_DEPTH` gauge SHALL be set to 0

---

## Test Coverage

### CI tests (deterministic)

- **Metric import test**: verify all 7 metrics are importable and are the correct prometheus-client types.
- **record_request counter test**: call `record_request()`, verify `http_requests_total` label values incremented.
- **record_request histogram test**: call `record_request()`, verify `http_request_duration_seconds` observes the value.
- **Path normalization test**: verify UUID segments are replaced with `:id`, non-UUID paths are preserved, root path handled.
- **Metrics endpoint test**: use a private-network ASGI client, verify 200 response with `text/plain` content type and expected metric names in body.
