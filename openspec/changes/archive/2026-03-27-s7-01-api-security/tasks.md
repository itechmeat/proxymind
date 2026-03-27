## 1. Configuration

- [x] 1.1 Add security settings to `backend/app/core/config.py`: `admin_api_key` (str | None, default None), `chat_rate_limit` (int, default 60), `chat_rate_window_seconds` (int, default 60), `trusted_proxy_depth` (int, default 1). Add `admin_api_key` to the `normalize_empty_optional_strings` tuple.
- [x] 1.2 Write unit tests for new settings: defaults, env override, empty-string normalization.

## 2. Admin Auth Dependency

- [x] 2.1 Create `backend/app/api/auth.py` with `verify_admin_key` dependency using `Security(HTTPBearer(auto_error=False))` in the function signature for OpenAPI integration. Implement: 503 when key not configured, 401 when missing/invalid, timing-safe comparison via `secrets.compare_digest()`, structlog warning on failure.
- [x] 2.2 Write unit tests for auth dependency: valid key → 200, missing key → 401, wrong key → 401, key not configured → 503, timing-safe comparison verified via mock.

## 3. Wire Auth to Admin Routers

- [x] 3.1 Add `dependencies=[Depends(verify_admin_key)]` to admin router in `backend/app/api/admin.py`. Remove all three `TODO(S7-01)` comments.
- [x] 3.2 Add `dependencies=[Depends(verify_admin_key)]` to admin profile router in `backend/app/api/profile.py`.
- [x] 3.3 Update existing test fixtures in `backend/tests/conftest.py`: add `TEST_ADMIN_API_KEY` constant, set `admin_api_key` in `admin_app` and `profile_app` settings, add auth header to `api_client` and `profile_client` fixtures.
- [x] 3.4 Write wiring tests: admin sources without key → 401, with key → passes auth; profile admin endpoint without key → 401.
- [x] 3.5 Run full test suite to verify no regressions from auth wiring.

## 4. Rate Limit Middleware

- [x] 4.1 Create `backend/app/middleware/__init__.py` (empty package init).
- [x] 4.2 Create `backend/app/middleware/rate_limit.py` as pure ASGI middleware (not BaseHTTPMiddleware). Implement: path prefix filter `/api/chat`, sliding window counter via Redis pipeline, IP extraction with `TRUSTED_PROXY_DEPTH` (formula: `parts[len(parts) - depth - 1]`), rate limit headers injection via `send_with_headers` wrapper, fail-open on Redis failure, structlog warning on exceeded/Redis failure.
- [x] 4.3 Write unit tests: under limit → 200 with headers, over limit → 429 with Retry-After, admin routes not affected, Redis failure → fail-open, single-proxy XFF extraction, no-XFF fallback to direct connection IP.

## 5. Mount Middleware

- [x] 5.1 Import and mount `RateLimitMiddleware` in `backend/app/main.py` via `app.add_middleware()`.
- [x] 5.2 Write unit test verifying middleware is present in the app middleware stack.

## 6. Environment Documentation

- [x] 6.1 Add `ADMIN_API_KEY`, `CHAT_RATE_LIMIT`, `CHAT_RATE_WINDOW_SECONDS`, `TRUSTED_PROXY_DEPTH` with comments to `.env.example` (or `.env` template). Include a deployment note that Caddy MUST overwrite `X-Forwarded-For` with `header_up X-Forwarded-For {remote_host}` — otherwise rate limiting can be bypassed via XFF spoofing.
- [x] 6.2 Add a comment to `Caddyfile` in the reverse proxy block documenting the `header_up X-Forwarded-For {remote_host}` requirement for rate limiting.

## 7. Integration Tests

- [x] 7.1 Write integration test: admin auth full flow (401 without key, 401 with wrong key, 200 with correct key).
- [x] 7.2 Write integration test: chat rate limit full flow (N requests → 201, N+1 → 429 with Retry-After).
- [x] 7.3 Write integration test: service endpoints (`/health`, `/ready`) unaffected by auth or rate limiting — no `X-RateLimit-*` headers, no 401.
- [x] 7.4 Run full test suite to confirm no regressions.
