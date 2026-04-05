## Story

**S7-03: End-user authentication + authenticated chat API**

Verification criteria:
- `POST /api/chat/sessions` without auth → 401/403
- `POST /api/chat/messages` without auth → 401/403
- `GET /api/chat/sessions/:id` without auth → 401/403
- Unauthenticated user opening chat UI is redirected to sign-in
- Authenticated user can register, sign in, create a session, send a message, and read session history
- Password recovery flow is reachable
- Admin token page authorizes admin UI separately
- Guest access still works for `/api/auth/*`, `/health`, and `/ready`

Stable behavior that must be covered by tests: all chat and twin-profile endpoints must reject unauthenticated requests; session ownership must be enforced (user A cannot read user B's session); email verification and password reset flows must be tested end-to-end.

## Why

ProxyMind chat endpoints are currently public — anyone can create sessions, send messages, and read history without authentication. This is acceptable for local development but blocks production deployment. Every chat request costs LLM inference money, and there is no way to identify or manage visitors. S7-03 establishes the baseline security posture required before exposing any instance to untrusted traffic.

## What Changes

- **BREAKING**: All chat endpoints (`/api/chat/*`) require a valid JWT access token. Unauthenticated requests receive 401.
- **BREAKING**: Twin profile endpoints (`GET /api/chat/twin`, `GET /api/chat/twin/avatar`) require authentication.
- New email-based end-user registration, sign-in, email verification, and password recovery/reset flows.
- New `users`, `user_profiles`, `user_tokens`, `user_refresh_tokens` database tables.
- JWT access tokens (15 min, HS256) + refresh tokens (7 days, rotated, stored in PostgreSQL).
- Session ownership enforcement — users can only access their own chat sessions.
- Pluggable email service (console for dev, Resend for prod).
- Auth brute-force rate limiting on `/api/auth/sign-in`, `/api/auth/register`, `/api/auth/forgot-password`, `/api/auth/reset-password`.
- Frontend auth pages: sign-in, register, forgot-password, reset-password, verify-email.
- Dedicated admin sign-in page (`/admin/sign-in`) replacing the current modal dialog.
- Rename `sessions.visitor_id` → `sessions.user_id` with FK to `users`.

## Capabilities

### New Capabilities
- `end-user-auth`: Email-based registration, sign-in, email verification, password recovery/reset, JWT access/refresh token lifecycle, user profile management (`/api/auth/*` endpoints), `get_current_user` FastAPI dependency, pluggable email service, token cleanup job.

### Modified Capabilities
- `chat-dialogue`: All chat endpoints now require authenticated user context. Session creation sets `user_id`. Session read/write enforces ownership (403 for foreign sessions). `visitor_id` column renamed to `user_id`.
- `twin-profile`: `GET /api/chat/twin` and `GET /api/chat/twin/avatar` now require authentication. Twin name on auth pages provided via `VITE_TWIN_NAME` env variable.
- `chat-rate-limiting`: Rate limiter extended to cover auth brute-force targets (`/api/auth/sign-in`, `/api/auth/register`, `/api/auth/forgot-password`, `/api/auth/reset-password`) with stricter per-IP limits. `/api/auth/refresh` is NOT rate-limited.
- `admin-knowledge-ui`: Admin routing guard replaced — modal AuthDialog becomes dedicated `/admin/sign-in` page with redirect flow.
- `chat-ui-transport`: Transport adds Authorization header on SSE requests; handles 401 with silent refresh retry and 403 with session re-creation.
- `chat-ui`: Chat route requires authentication (ProtectedRoute); session persistence handles 403 (foreign session), clears on logout, starts fresh on login.

## Impact

- **Backend**: New auth models, services, router, dependency, migration (018). Modified chat router, profile router, rate limit middleware, config settings. New dependencies: PyJWT, argon2-cffi, resend, pydantic[email].
- **Frontend**: New AuthContext provider, auth API client, 5 auth pages, admin sign-in page, ProtectedRoute component. Modified App.tsx routing, api.ts, transport.ts (auth headers), useSession.ts (user-scoped persistence). Existing integration tests must be updated for auth.
- **Database**: 4 new tables, 1 column rename + FK addition in sessions.
- **Infrastructure**: New env vars (JWT_SECRET_KEY, EMAIL_BACKEND, RESEND_API_KEY, EMAIL_FROM, FRONTEND_URL).
