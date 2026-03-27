## ADDED Requirements

### Requirement: Chat API rate limiting

All Chat API endpoints (`/api/chat/*`) SHALL be rate limited using a sliding window counter algorithm. The rate limit SHALL be applied per client IP address using Redis counters.

#### Scenario: Under rate limit

- **WHEN** a client sends a request to `/api/chat/*`
- **AND** the client has not exceeded the configured rate limit
- **THEN** the request SHALL be processed normally
- **AND** the response SHALL include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` headers

#### Scenario: Rate limit exceeded

- **WHEN** a client sends a request to `/api/chat/*`
- **AND** the client's weighted request count exceeds the configured limit
- **THEN** the system SHALL respond with 429 Too Many Requests
- **AND** the response body SHALL be `{"detail": "Rate limit exceeded"}`
- **AND** the response SHALL include `Retry-After` header with seconds until reset
- **AND** the response SHALL include `X-RateLimit-Limit` and `X-RateLimit-Remaining: 0` headers
- **AND** the response SHALL include `X-RateLimit-Reset` header

#### Scenario: Non-chat routes unaffected

- **WHEN** a request is made to `/api/admin/*`, `/health`, or `/ready`
- **THEN** the rate limiter SHALL NOT apply
- **AND** the response SHALL NOT include `X-RateLimit-*` headers

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

Rate limiting parameters SHALL be configurable via environment variables.

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

Rate limit events SHALL be logged for operational visibility.

#### Scenario: Rate limit exceeded logging

- **WHEN** a request is rejected due to rate limiting
- **THEN** the system SHALL log a warning with the client IP, request path, weighted count, and configured limit
