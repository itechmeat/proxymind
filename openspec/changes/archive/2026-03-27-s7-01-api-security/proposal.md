## Story

**S7-01: API security — auth + rate limiting** (Phase 7: Operations Layer)

Verification criteria from `docs/plan.md`:
- Admin without key → 401; with key → 200
- Exceed rate limit → 429; after cooldown → ok

Stable behavior requiring test coverage: admin auth (401/503/200 flows), chat rate limiting (429 with correct headers, fail-open on Redis failure).

## Why

The Chat API has been public since S2-04 and Admin API endpoints have accumulated across Phases 2–6, but neither has any security controls. Admin endpoints are fully unprotected — anyone who can reach the API can upload sources, publish snapshots, or modify the product catalog. Chat endpoints have no abuse protection — a single script can exhaust the LLM budget. This is explicitly called out in `docs/plan.md` as a baseline security requirement that MUST be resolved before any production deployment.

## What Changes

- Add API key authentication to all Admin API endpoints (`/api/admin/*`) via `Authorization: Bearer` header
- Add Redis-based sliding window rate limiting to all Chat API endpoints (`/api/chat/*`)
- Add four new `.env` configuration variables: `ADMIN_API_KEY`, `CHAT_RATE_LIMIT`, `CHAT_RATE_WINDOW_SECONDS`, `TRUSTED_PROXY_DEPTH`
- Remove existing `TODO(S7-01)` stub comments from `admin.py`
- Admin auth is isolated from visitor identity (architectural requirement for future channel connectors per S11-01)

## Capabilities

### New Capabilities
- `admin-auth`: API key authentication for admin endpoints — Bearer token validation, fail-safe when unconfigured (503), timing-safe comparison
- `chat-rate-limiting`: Redis-based sliding window rate limiting for chat endpoints — per-IP throttling, configurable limits, fail-open on Redis failure, standard rate limit headers

### Modified Capabilities
_(none — these are new security controls, not changes to existing spec-level behavior)_

## Impact

- **Backend code**: new `app/api/auth.py` (dependency), new `app/middleware/rate_limit.py` (ASGI middleware), changes to `app/core/config.py`, `app/main.py`, `app/api/admin.py`, `app/api/profile.py`
- **Test harness**: existing admin test fixtures (`conftest.py`) must add auth headers — cascading update across all admin/profile test clients
- **APIs**: Admin API now requires `Authorization: Bearer <key>` header. Chat API responses gain `X-RateLimit-*` headers. Three new error responses: 401 (invalid/missing key), 503 (key not configured), 429 (rate limit exceeded)
- **Dependencies**: no new packages — uses stdlib `secrets`, existing `redis.asyncio`, FastAPI `Security`
- **Infrastructure**: Redis (already present for arq) stores rate limit counters with auto-expiry
