# S7-03: End-User Authentication + Authenticated Chat API — Design Spec

## Overview

Transform ProxyMind from a local development tool into a production-ready system by implementing
email-based end-user authentication and protecting all chat/dialogue endpoints. Admin auth (API key)
remains separate and unchanged.

## Decisions Log

### D1: Token Strategy

**Chosen: JWT access + refresh tokens (Option A)**

Options considered:
- **A) JWT access + refresh tokens** — stateless access verification, refresh token in PostgreSQL
- **B) Redis session tokens** — every request checks Redis
- **C) Hybrid: JWT access + Redis blacklist** — JWT + Redis revocation check

**Rationale:** JWT scales better for future channel connectors (Phase 10). Redis is already used for
rate limiting and job queues — adding auth as another critical Redis path increases coupling.
Refresh token in PostgreSQL provides reliable revocation. Worst-case stale access window is 15
minutes (access token TTL), acceptable for a self-hosted single-twin product.

**Future:** Option C (Redis blacklist for immediate revocation) is trivial to add later (~20 lines)
if instant revocation becomes a requirement. Recorded in `docs/next.md`.

### D2: Email Delivery

**Chosen: Pluggable with Resend (Option C)**

Options considered:
- **A) Real email via SMTP** — external SMTP dependency
- **B) Console/log output only** — dev-only, no production path
- **C) Pluggable: abstraction + both implementations** — console (dev) + Resend (prod)

**Rationale:** Abstraction is trivial (protocol + 2 implementations). Self-hosted product needs
configurable email. Resend has a clean Python SDK and generous free tier. Console output is
essential for development and testing. Switching via `EMAIL_BACKEND` env var.

### D3: Email Verification at Registration

**Chosen: Mandatory verification before access (Option A)**

Options considered:
- **A) Mandatory verification** — register → verify email → access
- **B) No verification** — register → immediate access
- **C) Soft verification** — access immediately, remind to verify

**Rationale:** ProxyMind is a self-hosted twin for a specific person, not a mass service. Each
visitor is intentional, so verification friction is minimal. Password recovery requires a valid
email — without verification, recovery is unreliable. Every chat request costs LLM inference money,
so preventing spam registrations matters.

### D4: Password Hashing

**Chosen: argon2id via `argon2-cffi`**

No alternatives considered — argon2id is the OWASP-recommended algorithm (2026), memory-hard,
resistant to GPU/ASIC brute-force. Industry standard.

### D5: Frontend Auth Pages

**Chosen: Dedicated routes with AuthLayout (Option A)**

Spec requires pages ("MUST provide user-facing pages"), not dialogs. Standard SPA auth pattern
with `/auth/*` routes and a minimal layout (twin logo + centered form).

### D6: Access Token Storage (Frontend)

**Chosen: In-memory + httpOnly cookie for refresh (Option A)**

Options considered:
- **A) In-memory access + httpOnly cookie refresh** — XSS-safe, silent refresh on reload
- **B) localStorage access + httpOnly cookie refresh** — XSS-vulnerable
- **C) Both tokens in httpOnly cookies** — CSRF-vulnerable, bad for SPA + SSE

**Rationale:** Best security balance for SPA. Access token unreachable by XSS. Refresh token
protected by cookie flags. 50ms silent refresh on page reload is imperceptible. Backend is
client-agnostic: it only sees `Authorization: Bearer` header — each client (web, mobile, future)
decides its own storage strategy. Refresh endpoint accepts token from cookie OR request body to
support mobile clients.

**UX note:** Refresh token lives 7 days. User stays logged in as long as they visit at least once
per week. Refresh token rotation extends the window on each visit, so regular users are logged in
"forever".

### D7: Entity Naming

**Chosen: `users` (not `visitors`)**

Options considered:
- `visitors` — already in codebase, but implies transient/anonymous
- `users` — industry standard, clear semantics for registered accounts
- `members`, `contacts`, `audience` — non-standard for auth tables

**Rationale:** With email registration these are registered users, not anonymous visitors. No
conflict with admin — admin has no database record (API key only). Migration renames `visitor_id`
→ `user_id` in sessions table.

### D8: User Profile Separation

**Chosen: Separate `users` (auth) + `user_profiles` (data) tables**

Options considered:
- **A) Single `users` table** — simpler, fewer JOINs
- **B) Split `users` + `user_profiles`** — clean separation

**Rationale:** Profile will grow significantly over time (temperament, communication style, and
other behavioral fields). Auth table should remain stable and minimal. One-to-one relationship,
profile created automatically at registration. JOIN cost is negligible for the expected load.

### D9: Refresh Token Storage

**Chosen: Separate `user_refresh_tokens` table (Option B)**

Options considered:
- **A) Same table as email/reset tokens** — fewer tables
- **B) Separate table** — different access patterns

**Rationale:** Refresh tokens are high-frequency (created at login, rotated at refresh, deleted at
logout). Email verification and password reset tokens are rare. Separate cleanup jobs. `device_info`
field prepares for "active sessions" management when mobile clients arrive.

---

## Database Schema

### New Tables

#### `users`

| Column            | Type                                         | Constraints                |
|-------------------|----------------------------------------------|----------------------------|
| id                | UUID (uuid7)                                 | PK                         |
| email             | VARCHAR(255)                                 | UNIQUE, NOT NULL, indexed  |
| password_hash     | VARCHAR(255)                                 | NOT NULL                   |
| status            | ENUM('pending', 'active', 'blocked')         | NOT NULL, default 'pending'|
| email_verified_at | TIMESTAMP                                    | nullable                   |
| created_at        | TIMESTAMP                                    | NOT NULL                   |
| updated_at        | TIMESTAMP                                    | NOT NULL                   |

#### `user_profiles`

| Column       | Type           | Constraints                              |
|--------------|----------------|------------------------------------------|
| id           | UUID (uuid7)   | PK                                       |
| user_id      | UUID → users   | UNIQUE, NOT NULL, ON DELETE CASCADE       |
| display_name | VARCHAR(255)   | nullable                                 |
| avatar_url   | VARCHAR(2048)  | nullable                                 |
| created_at   | TIMESTAMP      | NOT NULL                                 |
| updated_at   | TIMESTAMP      | NOT NULL                                 |

#### `user_tokens`

For email verification and password reset. One-time, short-lived.

| Column     | Type                                              | Constraints                        |
|------------|---------------------------------------------------|------------------------------------|
| id         | UUID (uuid7)                                      | PK                                 |
| user_id    | UUID → users                                      | NOT NULL, ON DELETE CASCADE         |
| token_hash | VARCHAR(255)                                      | NOT NULL, indexed                  |
| token_type | ENUM('email_verification', 'password_reset')      | NOT NULL                           |
| expires_at | TIMESTAMP                                         | NOT NULL                           |
| used_at    | TIMESTAMP                                         | nullable                           |
| created_at | TIMESTAMP                                         | NOT NULL                           |

#### `user_refresh_tokens`

For JWT refresh tokens. High-frequency operations, rotation.

| Column      | Type          | Constraints                        |
|-------------|---------------|------------------------------------|
| id          | UUID (uuid7)  | PK                                 |
| user_id     | UUID → users  | NOT NULL, ON DELETE CASCADE, indexed|
| token_hash  | VARCHAR(255)  | NOT NULL, indexed                  |
| device_info | VARCHAR(512)  | nullable                           |
| expires_at  | TIMESTAMP     | NOT NULL                           |
| created_at  | TIMESTAMP     | NOT NULL                           |

### Migration: `sessions` Table

- Rename column: `visitor_id` → `user_id`
- Add FK: `sessions.user_id → users(id) ON DELETE SET NULL`
- `user_id` remains nullable (for future channel connectors using `external_user_id`)
- `external_user_id` and `channel_connector` — unchanged (Phase 10)

---

## Backend API Endpoints

### Auth Router (`/api/auth/*`) — Public, No Auth Required

| Method | Path                       | Description                                    | Response |
|--------|----------------------------|------------------------------------------------|----------|
| POST   | `/api/auth/register`       | Register (email, password, display_name?)       | 200      |
| POST   | `/api/auth/verify-email`   | Verify email with token                         | 200      |
| POST   | `/api/auth/sign-in`        | Login (email, password) → access + refresh      | 200      |
| POST   | `/api/auth/refresh`        | Refresh access token (cookie or body)           | 200      |
| POST   | `/api/auth/forgot-password`| Request password reset email                    | 200      |
| POST   | `/api/auth/reset-password` | Set new password with reset token               | 200      |
| POST   | `/api/auth/sign-out`       | Delete refresh token (logout)                   | 200      |
| GET    | `/api/users/me`            | Current user + profile (requires auth)          | 200      |
| PATCH  | `/api/profile`             | Update display_name, avatar_url (requires auth) | 200      |

**Note:** current-user lookup and self-service profile update are separated from the auth prefix.
`GET /api/users/me` represents the authenticated user resource, while `PATCH /api/profile`
updates the dedicated `user_profiles` record.

**Registration behavior:** `POST /api/auth/register` always returns 200 with a generic "check your
email" message, regardless of whether the email is already registered. This prevents email
enumeration. If the email exists, no action is taken (no email sent, no error revealed).

### Protected Chat Endpoints — Require `get_current_user`

| Method | Path                            | Changes                                      |
|--------|---------------------------------|----------------------------------------------|
| POST   | `/api/chat/sessions`            | + auth dependency, sets `session.user_id`    |
| POST   | `/api/chat/messages`            | + auth dependency, ownership check           |
| GET    | `/api/chat/sessions`            | + auth dependency, filter by current user    |
| GET    | `/api/chat/sessions/:id`        | + auth dependency, ownership check           |
| GET    | `/api/chat/messages/:id/stream` | + auth dependency, ownership check           |
| GET    | `/api/chat/twin`                | + auth dependency (twin profile)             |
| GET    | `/api/chat/twin/avatar`         | + auth dependency (twin avatar)              |

**Note on twin profile:** The twin name displayed on auth pages comes from `VITE_TWIN_NAME`
env variable, not from the API. The `/api/chat/twin` endpoint is only needed after authentication.

### Guest Whitelist (No Auth)

- `/api/auth/*`
- `/health`
- `/ready`
- `/metrics` (has its own IP-based access control)

### Admin Endpoints — Unchanged

`/api/admin/*` continues to use `verify_admin_key` (Bearer API key). No changes.

---

## Auth Middleware Architecture

### FastAPI Dependency

```
get_current_user(token: str = Depends(oauth2_scheme)) -> User
  ├── Extract access token from Authorization header
  ├── Decode JWT, verify signature and expiry (PyJWT)
  ├── Extract user_id from payload
  ├── Load User from DB
  ├── Verify status == 'active'
  └── Return User object or raise 401
```

### Router-Level Protection

- `chat_router`: add `dependencies=[Depends(get_current_user)]` at router level
- `auth_router`: no auth dependency (public)
- `admin_router`: keep `verify_admin_key` (unchanged)
- `health_router`, `metrics_router`: no changes

### Session Ownership Enforcement

- Create session: `session.user_id = current_user.id`
- Read/write session: verify `session.user_id == current_user.id`, else 403
- List sessions: filter by `user_id == current_user.id`

---

## Token Lifecycle

### Access Token (JWT)

- Algorithm: HS256
- Secret: `JWT_SECRET_KEY` from `.env`
- TTL: 15 minutes
- Payload: `{ sub: user_id (str), exp, iat, jti (uuid4) }`
- Storage: in-memory (frontend JS variable)

### Refresh Token

- Generation: `secrets.token_urlsafe(32)`
- Storage: SHA-256 hash in `user_refresh_tokens` table
- TTL: 7 days
- Transport: httpOnly cookie (`refresh_token`, Secure via `AUTH_COOKIE_SECURE`, SameSite=Lax) OR request body
- Rotation: on each refresh, old token is deleted, new one is created

### Email Verification Token

- Generation: `secrets.token_urlsafe(32)`
- Storage: SHA-256 hash in `user_tokens`
- TTL: 24 hours
- One-time use (marked with `used_at`)

### Password Reset Token

- Generation: `secrets.token_urlsafe(32)`
- Storage: SHA-256 hash in `user_tokens`
- TTL: 1 hour
- One-time use (marked with `used_at`)

---

## Email Service

### Pluggable Architecture

```
Protocol: EmailSender
  async send(to: str, subject: str, html_body: str) -> None

Implementations:
  ConsoleEmailSender  — logs delivery metadata and can persist to an outbox dir (dev/test)
  ResendEmailSender   — sends via Resend API (prod)
```

### Configuration (.env)

```
EMAIL_BACKEND=console|resend
RESEND_API_KEY=re_...          # resend only
EMAIL_FROM=noreply@example.com
FRONTEND_URL=http://localhost:5173  # for email links
```

### Email Templates (2)

1. **Email verification** — link to `{FRONTEND_URL}/auth/verify-email?token={token}`
2. **Password reset** — link to `{FRONTEND_URL}/auth/reset-password?token={token}`

Plain HTML string templates in code. No external templating dependencies.

---

## Frontend

### New Routes

```
/auth/sign-in           — login form
/auth/register          — registration form
/auth/forgot-password   — request password reset
/auth/reset-password    — set new password (token from URL query)
/auth/verify-email      — email confirmation (token from URL query)
```

### Layout Structure

- **AuthLayout** — minimal (twin logo + centered form), no sidebar
- **ChatLayout** — current layout, wrapped in `ProtectedRoute`
- **AdminLayout** — current layout, with dedicated `/admin/sign-in` page (replaces modal AuthDialog)

### Auth State Management

- `AuthProvider` (React Context) — stores access token in memory
- Provides: `user`, `isAuthenticated`, `login()`, `logout()`, `refreshToken()`
- On App mount: silent refresh via `/api/auth/refresh` (cookie already present)
- On 401 from any request: attempt refresh → if failed, redirect to `/auth/sign-in`
- Existing `useAuth` hook for admin — remains separate (per spec requirement)

### API Client Integration

- `transport.ts`: add interceptor — on 401 → attempt refresh → retry original request
- Access token sent via `Authorization: Bearer` header
- SSE streaming: uses `fetch()` with `Authorization: Bearer` header (not EventSource, so
  custom headers are supported natively)

### Pages

**Sign-in:** Email + Password. Links to Register and Forgot Password.

**Register:** Email + Password + Confirm Password + Display Name (optional). After submit →
"Check your email" screen.

**Forgot Password:** Email input. After submit → "Email sent" screen (always, even if email not
found — enumeration protection).

**Reset Password:** New Password + Confirm. Token from URL query param.

**Verify Email:** Auto-submits token from URL. Shows success ("Email verified, go to chat") or
error ("Link expired").

**Admin Sign-in (`/admin/sign-in`):** Dedicated page (not a modal) for entering the admin API key.
Replaces the current `AuthDialog` modal flow. Separate from end-user auth pages. Redirects to
`/admin/sources` on success.

### Session Lifecycle and Auth

- On **logout**: clear `proxymind_session_id` from localStorage
- On **login**: do NOT restore a previous session — create a new one for the authenticated user
- On **403** from `getSession()`: treat like 404 — clear stored session and create new
- This prevents cross-user session access when switching accounts

---

## Security Considerations

1. **Password hashing:** argon2id via `argon2-cffi`
2. **Timing-safe comparison:** for all token verifications (`secrets.compare_digest`)
3. **Email enumeration protection:** `/forgot-password` and `/register` never reveal whether
   an email exists
4. **Rate limiting:** extend the existing rate limiter to cover brute-force targets:
   `/api/auth/sign-in`, `/api/auth/register`, `/api/auth/forgot-password`,
   `/api/auth/reset-password` (10 requests/minute per IP). Do NOT rate-limit
   `/api/auth/refresh` — it fires on every page load during silent refresh and would
   throttle legitimate users
5. **Token hashing:** all tokens (refresh, verification, reset) stored as SHA-256 hash, never
   plaintext
6. **CORS:** add `credentials: true` to allow cookie transmission
7. **SameSite=Lax** for refresh cookie — CSRF protection while allowing navigation
8. **Cleanup job:** periodic cleanup of expired tokens from `user_tokens` and
   `user_refresh_tokens` (arq background task, runs every 6 hours)
9. **Refresh cookie `Secure` flag:** drive it explicitly via `AUTH_COOKIE_SECURE`.
   Development defaults to `false`; production deployments should set it to `true`.
10. **User-scoped session persistence:** clear stored `proxymind_session_id` on logout; on login,
    start fresh session for the new user to prevent cross-user session access (403)

---

## New Dependencies

### Backend

| Package      | Purpose                  |
|--------------|--------------------------|
| PyJWT        | JWT encoding/decoding    |
| argon2-cffi  | Password hashing         |
| resend       | Resend Python SDK        |

### Frontend

No new dependencies. Uses existing React Router and Radix UI.

---

## Out of Scope

- OAuth / social login (Google, GitHub)
- Immediate revocation via Redis blacklist (Option C from D1)
- Admin user accounts in database (admin stays as API key)
- Multi-factor authentication (MFA/2FA)
- Account deletion / GDPR compliance
- Per-user rate limiting (currently per-IP)
- External channel identity integration (Phase 10)
