# S7-01: API Security — Auth + Rate Limiting

## Overview

Add two independent security mechanisms to the ProxyMind API:

1. **Admin API authentication** — API key via `Authorization: Bearer` header, key from `.env`.
2. **Chat API rate limiting** — Redis-based sliding window counter, keyed by client IP.

Chat API remains public (no authentication). Admin auth and visitor identity remain decoupled (architectural requirement for future channel connectors).

## Decisions

### D1: Rate limit key — by IP address

**Chosen:** IP address only.
**Why:** Simplest and most robust approach for a public API without user authentication. Self-hosted product behind Caddy — IP is the only reliable client identifier. Session IDs can be trivially rotated to bypass limits.
**Trade-off:** Multiple users behind NAT share a single limit. Mitigated by choosing a generous default (D5).

### D2: Rate limiting algorithm — sliding window counter

**Chosen:** Sliding window counter using two adjacent Redis windows with weighted interpolation.
**Why:** Balances simplicity (3 Redis commands per request, pipelined into a single round-trip) and correctness (no burst-at-boundary problem that fixed window has). Token bucket is more complex with no benefit for our use case.

### D3: Rate limit scope — single limit on all Chat API endpoints

**Chosen:** One limit for all `/api/chat/*` endpoints.
**Why:** The expensive operation is `POST /api/chat/messages` (LLM call). Session creation and history reads are cheap. A single limit is simpler to configure and sufficient for self-hosted deployment. Per-endpoint granularity can be added later without breaking changes. YAGNI.

### D4: Admin API key — single key from `.env`

**Chosen:** Single `ADMIN_API_KEY` environment variable.
**Why:** Story explicitly specifies "key from `.env`". One instance = one twin = one owner. Key rotation: change in `.env`, restart. Multiple keys would be trivial to add later (comma-split) but are not needed now.

### D5: Default rate limit — 60 requests/minute

**Chosen:** 60 requests per 60-second window.
**Why:** Generous enough for multiple users behind NAT (real users send ~1 msg per 3-10 seconds while waiting for LLM response). Restrictive enough to stop scripts and accidental loops. Configurable via `.env` for owners with different needs.

### D6: Admin auth implementation — FastAPI Security dependency

**Chosen:** FastAPI `Security(HTTPBearer())` + dependency function on router level.
**Why:** Idiomatic FastAPI pattern. OpenAPI integration (Swagger lock icon, Authorize button). Granular control via `dependencies=[Depends(verify_admin_key)]` on the router. Already the project's DI pattern.

### D7: Rate limit implementation — ASGI middleware

**Chosen:** Starlette/ASGI middleware filtering by path prefix `/api/chat`.
**Why:** Rate limiting is a cross-cutting concern. Middleware intercepts before routing and deserialization — rejects early, saves resources. Standard practice for abuse protection.

### D8: Missing admin key behavior — fail-safe (503)

**Chosen:** Admin API returns 503 Service Unavailable when `ADMIN_API_KEY` is not configured.
**Why:** Secure-by-default per `docs/development.md`: "if there is no explicit permission, access is denied." App starts, health/chat work, but admin is locked until the owner consciously sets a key. Prevents accidental deployment without protection.

### D9: Rate limit Redis failure behavior — fail-open

**Chosen:** If Redis is unreachable during rate limit check, the request is allowed through.
**Why:** Rate limiting protects against abuse but is not critical for correctness. Chat should not break because Redis is temporarily down. Logged as a warning via structlog for operational visibility.

## Architecture

### Component overview

```
Request → Caddy → ASGI middleware (rate limit) → FastAPI routing
                                                    ├── /api/chat/* → (rate limit applied) → chat handlers
                                                    ├── /api/admin/* → verify_admin_key dependency → admin handlers
                                                    └── /health, /ready → no security (unchanged)
```

### New files

| File                                   | Purpose                                                  |
| -------------------------------------- | -------------------------------------------------------- |
| `backend/app/api/auth.py`              | `verify_admin_key` FastAPI dependency using `HTTPBearer` |
| `backend/app/middleware/rate_limit.py` | `RateLimitMiddleware` ASGI middleware for Chat API       |

### Modified files

| File                         | Change                                                                                    |
| ---------------------------- | ----------------------------------------------------------------------------------------- |
| `backend/app/core/config.py` | Add `ADMIN_API_KEY`, `CHAT_RATE_LIMIT`, `CHAT_RATE_WINDOW_SECONDS`, `TRUSTED_PROXY_DEPTH` |
| `backend/app/main.py`        | Mount `RateLimitMiddleware`                                                               |
| `backend/app/api/admin.py`   | Add `dependencies=[Depends(verify_admin_key)]` to router, remove TODO comments            |
| `backend/app/api/profile.py` | Add `dependencies=[Depends(verify_admin_key)]` to admin profile router                    |
| `backend/.env.example`       | Document new variables                                                                    |

## Admin Auth Detail

### Dependency: `verify_admin_key`

- Uses `Security(HTTPBearer(auto_error=False))` in the function signature so FastAPI includes the Bearer scheme in the OpenAPI spec (lock icon, Authorize button in Swagger).
- Reads `ADMIN_API_KEY` from `app.state.settings`.
- If `ADMIN_API_KEY` is not configured (None/empty): raises `HTTPException(503)`.
- If token is missing or invalid: raises `HTTPException(401)` with `WWW-Authenticate: Bearer`.
- Comparison via `secrets.compare_digest()` — timing-safe.
- Applied at router level: `admin_router = APIRouter(..., dependencies=[Depends(verify_admin_key)])`.
- Auth failures logged via structlog (IP, path, reason).

## Rate Limit Middleware Detail

### Middleware: `RateLimitMiddleware`

- Pure ASGI middleware (not `BaseHTTPMiddleware`) applied to the app in `main.py`. Pure ASGI avoids response-body wrapping issues with SSE streaming in chat endpoints.
- Filters by path prefix `/api/chat` — all other paths pass through untouched.
- IP extraction: reads `X-Forwarded-For` header, skips `TRUSTED_PROXY_DEPTH` entries from the right (those are from trusted proxies), takes the next entry as the client IP. With depth=1 (Caddy only) and XFF=`client, caddy_appended`, this correctly returns the client IP. Falls back to ASGI scope `client` when no XFF present.

### Sliding window algorithm

Two adjacent fixed windows with weighted interpolation:

1. Current window key: `ratelimit:{ip}:{current_window_start}`
2. Previous window key: `ratelimit:{ip}:{previous_window_start}`
3. Weighted count = `previous_count * (1 - elapsed_fraction) + current_count`
4. If weighted count ≥ limit → reject with 429.

Redis operations per request: `GET` (previous window) + `INCR` + `EXPIRE` (current window) — pipelined into a single round-trip.

### Response headers

Added to all `/api/chat` responses (both success and 429):

| Header                  | Value                                         |
| ----------------------- | --------------------------------------------- |
| `X-RateLimit-Limit`     | Configured limit (e.g., 60)                   |
| `X-RateLimit-Remaining` | Requests remaining in current window          |
| `X-RateLimit-Reset`     | Unix timestamp when the current window resets |
| `Retry-After`           | Seconds until reset (429 responses only)      |

### Redis failure

If Redis is unreachable: log warning, allow request through (fail-open). Rate limiting is a defense mechanism, not a correctness requirement.

## Configuration

| Variable                   | Type          | Default | Description                                                                                                                                                                                                          |
| -------------------------- | ------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ADMIN_API_KEY`            | `str \| None` | `None`  | API key for admin endpoints. Admin API is blocked (503) when not set                                                                                                                                                 |
| `CHAT_RATE_LIMIT`          | `int`         | `60`    | Max requests to Chat API per IP per window                                                                                                                                                                           |
| `CHAT_RATE_WINDOW_SECONDS` | `int`         | `60`    | Rate limit window duration in seconds                                                                                                                                                                                |
| `TRUSTED_PROXY_DEPTH`      | `int`         | `1`     | Number of trusted proxies at the end of the X-Forwarded-For chain. Client IP = entry at position `len(parts) - depth - 1`. With depth=1 (Caddy), the last XFF entry is skipped and the next one is used as client IP |

## Error Responses

| Situation                     | Status | Body                                         | Headers                        |
| ----------------------------- | ------ | -------------------------------------------- | ------------------------------ |
| Admin: key not configured     | 503    | `{"detail": "Admin API key not configured"}` | `WWW-Authenticate: Bearer`     |
| Admin: missing or invalid key | 401    | `{"detail": "Invalid or missing API key"}`   | `WWW-Authenticate: Bearer`     |
| Chat: rate limit exceeded     | 429    | `{"detail": "Rate limit exceeded"}`          | `Retry-After`, `X-RateLimit-*` |

## Testing

### Unit tests

- **Auth dependency:** valid key → passes, invalid key → 401, missing key → 401, key not configured → 503, timing-safe comparison verified.
- **Rate limiter logic:** under limit → passes, at limit → passes, over limit → 429, Redis unavailable → passes (fail-open), correct header values.

### Integration tests

- **Admin auth flow:** request without key → 401; request with wrong key → 401; request with correct key → 200; key not configured → 503.
- **Rate limit flow:** N requests within limit → all 200; N+1 request → 429 with correct `Retry-After`; after window reset → 200 again.
- Redis mocked with `fakeredis` for deterministic CI tests.

## Out of Scope

- CORS — handled by Caddy.
- HTTPS — Caddy auto-TLS.
- Service endpoint protection (`/health`, `/ready`, `/metrics`) — Caddy IP restriction or S7-02.
- Visitor identity — S11-01.
- OAuth / JWT — future phases.
- Rate limiting admin API — protected by API key, no need.
- Multiple API keys — YAGNI, trivial to add later.
