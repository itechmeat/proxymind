## Purpose

Delta spec for chat-rate-limiting capability modifications introduced by S7-03. Rate limiter extended to cover auth brute-force endpoints with separate Redis key prefix.

---

## MODIFIED Requirements

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

---

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
