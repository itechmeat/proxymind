## Purpose

Protect public chat endpoints from abuse with a Redis-backed sliding-window rate limiter keyed by client IP.

## ADDED Requirements

### Requirement: Chat API rate limiting

All Chat API endpoints (`/api/chat/*`) SHALL be rate limited using a sliding window counter algorithm. The rate limit SHALL be applied per client IP address using Redis counters. Additionally, the following auth endpoints SHALL be rate limited at 10 requests per minute per IP: `/api/auth/sign-in`, `/api/auth/register`, `/api/auth/forgot-password`, `/api/auth/reset-password`. The auth rate limit SHALL use a separate Redis counter key prefix (`ratelimit:auth:`) distinct from the chat rate limit prefix (`ratelimit:chat:`). `/api/auth/refresh` SHALL NOT be rate limited (it fires on every page load during silent refresh and would throttle legitimate users).

#### Scenario: Under rate limit (chat)

- **WHEN** a client sends a request to `/api/chat/*`
- **AND** the client has not exceeded the configured chat rate limit
- **THEN** the request SHALL be processed normally
- **AND** the response SHALL include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` headers

#### Scenario: Rate limit exceeded (chat)

- **WHEN** a client sends a request to `/api/chat/*`
- **AND** the client's weighted request count exceeds the configured chat limit
- **THEN** the system SHALL respond with 429 Too Many Requests
- **AND** the response body SHALL be `{"detail": "Rate limit exceeded"}`
- **AND** the response SHALL include `Retry-After` header with seconds until reset
- **AND** the response SHALL include `X-RateLimit-Limit` and `X-RateLimit-Remaining: 0` headers
- **AND** the response SHALL include `X-RateLimit-Reset` header

#### Scenario: Auth brute-force endpoint rate limited

- **WHEN** a client sends more than 10 requests per minute to `/api/auth/sign-in`
- **THEN** the system SHALL respond with 429 Too Many Requests
- **AND** the response SHALL include `Retry-After` header

#### Scenario: Auth register endpoint rate limited

- **WHEN** a client sends more than 10 requests per minute to `/api/auth/register`
- **THEN** the system SHALL respond with 429 Too Many Requests

#### Scenario: Auth forgot-password endpoint rate limited

- **WHEN** a client sends more than 10 requests per minute to `/api/auth/forgot-password`
- **THEN** the system SHALL respond with 429 Too Many Requests

#### Scenario: Auth reset-password endpoint rate limited

- **WHEN** a client sends more than 10 requests per minute to `/api/auth/reset-password`
- **THEN** the system SHALL respond with 429 Too Many Requests

#### Scenario: Auth refresh endpoint NOT rate limited

- **WHEN** a client sends requests to `/api/auth/refresh`
- **THEN** the rate limiter SHALL NOT apply to these requests
- **AND** the response SHALL NOT include `X-RateLimit-*` headers

#### Scenario: Non-rate-limited routes unaffected

- **WHEN** a request is made to `/api/admin/*`, `/health`, or `/ready`
- **THEN** the rate limiter SHALL NOT apply
- **AND** the response SHALL NOT include `X-RateLimit-*` headers

### Requirement: Separate Redis key prefixes for auth and chat rate limits

The rate limiter SHALL use distinct Redis key prefixes for chat and auth rate limiting. Chat rate limit counters SHALL use keys prefixed with `ratelimit:chat:` and auth rate limit counters SHALL use keys prefixed with `ratelimit:auth:`. This separation ensures that auth and chat rate limits are tracked independently and do not interfere with each other.

#### Scenario: Chat rate limit uses chat prefix

- **WHEN** a request to `/api/chat/sessions` is processed by the rate limiter
- **THEN** the Redis counter key SHALL be prefixed with `ratelimit:chat:`

#### Scenario: Auth rate limit uses auth prefix

- **WHEN** a request to `/api/auth/sign-in` is processed by the rate limiter
- **THEN** the Redis counter key SHALL be prefixed with `ratelimit:auth:`

#### Scenario: Auth and chat limits are independent

- **WHEN** a client has exhausted the auth rate limit (10 req/min on `/api/auth/sign-in`)
- **AND** the client sends a request to `/api/chat/sessions`
- **THEN** the chat request SHALL be processed normally (the auth rate limit does not affect chat endpoints)

### Requirement: Sliding window algorithm

The rate limiter SHALL use a sliding window counter to avoid the burst-at-boundary problem of fixed windows.

#### Scenario: Smooth rate calculation

- **WHEN** the rate limiter checks the current count
- **THEN** it SHALL compute a weighted count: `previous_window_count * (1 - elapsed_fraction) + current_window_count`
- **AND** the weighted count SHALL be compared against the configured limit

### Requirement: Client IP extraction

The default deployment model is a single trusted proxy (Caddy). The rate limiter SHALL extract the client IP from the `X-Forwarded-For` header using the formula `parts[len(parts) - depth - 1]` where depth is `TRUSTED_PROXY_DEPTH` (default 1). This formula requires that Caddy overwrites the incoming `X-Forwarded-For` header with the direct peer IP (`header_up X-Forwarded-For {remote_host}`). Without this Caddy configuration, clients can spoof XFF entries to bypass rate limiting. `TRUSTED_PROXY_DEPTH` is retained for non-standard setups but the documented and tested model is single proxy.

#### Scenario: Single proxy (default deployment)

- **WHEN** `TRUSTED_PROXY_DEPTH` is 1
- **AND** Caddy overwrites `X-Forwarded-For` with the connecting client IP
- **AND** `X-Forwarded-For` contains a single entry (e.g., `1.2.3.4`)
- **THEN** the rate limiter SHALL use `1.2.3.4` as the client IP

#### Scenario: No X-Forwarded-For header

- **WHEN** no `X-Forwarded-For` header is present
- **THEN** the rate limiter SHALL use the direct connection IP from the ASGI scope

### Requirement: Configurable rate limits

Rate-limiting parameters SHALL be configurable via environment variables.

#### Scenario: Default configuration

- **WHEN** rate limit environment variables are not set
- **THEN** `CHAT_RATE_LIMIT` SHALL default to 60 (requests per window)
- **AND** `CHAT_RATE_WINDOW_SECONDS` SHALL default to 60 (seconds)
- **AND** `TRUSTED_PROXY_DEPTH` SHALL default to 1

#### Scenario: Custom configuration

- **WHEN** `CHAT_RATE_LIMIT=120` and `CHAT_RATE_WINDOW_SECONDS=30` are set
- **THEN** the rate limiter SHALL allow 120 requests per 30-second window

### Requirement: Fail-open on Redis failure

When Redis is unavailable, the rate limiter SHALL allow requests through rather than blocking chat functionality.

#### Scenario: Redis unreachable

- **WHEN** a request to `/api/chat/*` arrives
- **AND** Redis is unreachable or returns an error
- **THEN** the request SHALL be processed normally (fail-open)
- **AND** a warning SHALL be logged via structlog with the client IP

### Requirement: Pure ASGI middleware

The rate limiter SHALL be implemented as a pure ASGI middleware (not BaseHTTPMiddleware) to avoid response-body wrapping issues with SSE streaming endpoints.

#### Scenario: SSE streaming compatibility

- **WHEN** a chat message request triggers SSE streaming
- **AND** the rate limiter allows the request
- **THEN** the SSE stream SHALL function correctly without buffering or wrapping artifacts

### Requirement: Rate limit logging

**[Modified by S7-02]** Rate limit events SHALL be logged for operational visibility. Additionally, when a request is rejected due to rate limiting, the Prometheus metric `rate_limit_hits_total` SHALL be incremented via the code constant `RATE_LIMIT_HITS_TOTAL`.

#### Scenario: Rate limit exceeded logging

- **WHEN** a request is rejected due to rate limiting
- **THEN** the system SHALL log a warning with the client IP, request path, weighted count, and configured limit

#### Scenario: Rate limit Prometheus counter incremented on rejection

- **WHEN** a request is rejected due to rate limiting (429 response)
- **THEN** `RATE_LIMIT_HITS_TOTAL.inc()` SHALL be called
- **AND** the counter increment SHALL happen after the structlog warning is emitted

#### Scenario: Counter not incremented for allowed requests

- **WHEN** a request to `/api/chat/*` is allowed (under rate limit)
- **THEN** `RATE_LIMIT_HITS_TOTAL` SHALL NOT be incremented

#### Scenario: Counter import is resilient

- **WHEN** the `app.services.metrics` module is not available (e.g., in isolated tests)
- **THEN** the rate limiter SHALL still function correctly
- **AND** the missing import SHALL be handled gracefully (try/except or lazy import)

---

## Test Coverage

### CI tests (deterministic)

- **Rate limit counter test**: trigger a rate limit rejection, verify `RATE_LIMIT_HITS_TOTAL` counter is incremented.
- **Rate limit allowed test**: send a request under the limit, verify the counter is NOT incremented.
- **Existing rate limit tests pass**: verify all pre-existing `test_rate_limit.py` tests still pass with the metrics import added.
