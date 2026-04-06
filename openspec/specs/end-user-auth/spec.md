## Purpose

Email-based end-user authentication: registration, sign-in, email verification, password recovery/reset, JWT access/refresh token lifecycle, user profile management, pluggable email service, and token cleanup. Introduced by S7-03.

---

## ADDED Requirements

### Requirement: User registration via POST /api/auth/register

The system SHALL expose `POST /api/auth/register` accepting `email` (string, required), `password` (string, required), and `display_name` (string, optional). The endpoint SHALL always return 200 with a generic message (e.g., "Check your email to verify your account") regardless of whether the email is already registered. This prevents email enumeration. When the email is new, the system SHALL create a `users` record with `status=pending`, hash the password with argon2id, create a `user_profiles` record (with `display_name` if provided), generate an email verification token (stored as SHA-256 hash in `user_tokens` with `token_type=email_verification` and 24-hour TTL), and send a verification email containing a link to `{FRONTEND_URL}/auth/verify-email?token={token}`. When the email already exists, the system SHALL take no action and SHALL NOT send any email.

#### Scenario: Successful registration with new email

- **WHEN** `POST /api/auth/register` is called with `{"email": "new@example.com", "password": "Str0ngP@ss!", "display_name": "Alice"}`
- **AND** no user with email `new@example.com` exists
- **THEN** the response SHALL be 200 with a generic "check your email" message
- **AND** a `users` record SHALL be created with `status=pending` and argon2id-hashed password
- **AND** a `user_profiles` record SHALL be created with `display_name="Alice"`
- **AND** a verification email SHALL be sent to `new@example.com`

#### Scenario: Registration with existing email (enumeration protection)

- **WHEN** `POST /api/auth/register` is called with an email that already exists in `users`
- **THEN** the response SHALL be 200 with the same generic message
- **AND** no new user SHALL be created
- **AND** no email SHALL be sent

#### Scenario: Registration without display_name

- **WHEN** `POST /api/auth/register` is called with `{"email": "user@example.com", "password": "P@ssw0rd!"}` and no `display_name`
- **THEN** the `user_profiles` record SHALL be created with `display_name=NULL`

---

### Requirement: Email verification via POST /api/auth/verify-email

The system SHALL expose `POST /api/auth/verify-email` accepting a `token` (string). The system SHALL hash the token with SHA-256, look up the hash in `user_tokens` where `token_type=email_verification`, `used_at IS NULL`, and `expires_at > now()`. On match, the system SHALL set `user.status=active`, set `user.email_verified_at` to the current timestamp, and mark the token as used (`used_at=now()`). The endpoint SHALL return 200 on success. On invalid or expired token, the endpoint SHALL return 400.

#### Scenario: Valid verification token

- **WHEN** `POST /api/auth/verify-email` is called with a valid, unused, non-expired token
- **THEN** the response SHALL be 200
- **AND** the user's `status` SHALL be updated to `active`
- **AND** the user's `email_verified_at` SHALL be set to the current timestamp
- **AND** the token's `used_at` SHALL be set to the current timestamp

#### Scenario: Expired verification token

- **WHEN** `POST /api/auth/verify-email` is called with a token whose `expires_at` is in the past
- **THEN** the response SHALL be 400

#### Scenario: Already-used verification token

- **WHEN** `POST /api/auth/verify-email` is called with a token that has `used_at IS NOT NULL`
- **THEN** the response SHALL be 400

---

### Requirement: Sign-in via POST /api/auth/sign-in

The system SHALL expose `POST /api/auth/sign-in` accepting `email` (string) and `password` (string). The system SHALL look up the user by email, verify the password against the stored argon2id hash using timing-safe comparison, check that `status=active` (email verified and not blocked), and on success return 200 with a JSON body containing `access_token` (JWT) and `token_type: "bearer"`. The response SHALL also set an httpOnly cookie named `refresh_token` with `Secure` controlled by `AUTH_COOKIE_SECURE`, `SameSite=Lax`, `Path=/api/auth`, and 7-day max-age. The refresh token SHALL be stored as SHA-256 hash in `user_refresh_tokens`. On invalid credentials, the endpoint SHALL return 401. On unverified email (`status=pending`), the endpoint SHALL return 403. On blocked user (`status=blocked`), the endpoint SHALL return 403.

#### Scenario: Successful sign-in

- **WHEN** `POST /api/auth/sign-in` is called with valid credentials for an active user
- **THEN** the response SHALL be 200 with `{"access_token": "<jwt>", "token_type": "bearer"}`
- **AND** an httpOnly `refresh_token` cookie SHALL be set
- **AND** a refresh token hash SHALL be stored in `user_refresh_tokens`

#### Scenario: Invalid password

- **WHEN** `POST /api/auth/sign-in` is called with valid email but wrong password
- **THEN** the response SHALL be 401

#### Scenario: Non-existent email

- **WHEN** `POST /api/auth/sign-in` is called with an email not in `users`
- **THEN** the response SHALL be 401

#### Scenario: Unverified email (pending status)

- **WHEN** `POST /api/auth/sign-in` is called with valid credentials for a user with `status=pending`
- **THEN** the response SHALL be 403

#### Scenario: Blocked user

- **WHEN** `POST /api/auth/sign-in` is called with valid credentials for a user with `status=blocked`
- **THEN** the response SHALL be 403

---

### Requirement: Token refresh via POST /api/auth/refresh

The system SHALL expose `POST /api/auth/refresh` that accepts a refresh token from either the `refresh_token` httpOnly cookie OR the request body (`refresh_token` field). The system SHALL hash the token with SHA-256, look up the hash in `user_refresh_tokens` where `expires_at > now()`, verify the associated user is active, delete the old refresh token, create a new refresh token (rotation), issue a new JWT access token, and return 200 with `{"access_token": "<jwt>", "token_type": "bearer"}` plus a new httpOnly `refresh_token` cookie. On invalid or expired refresh token, the endpoint SHALL return 401.

#### Scenario: Successful token refresh via cookie

- **WHEN** `POST /api/auth/refresh` is called with a valid `refresh_token` cookie
- **THEN** the response SHALL be 200 with a new `access_token`
- **AND** the old refresh token SHALL be deleted from `user_refresh_tokens`
- **AND** a new refresh token hash SHALL be stored in `user_refresh_tokens`
- **AND** a new httpOnly `refresh_token` cookie SHALL be set

#### Scenario: Successful token refresh via request body

- **WHEN** `POST /api/auth/refresh` is called with `{"refresh_token": "<token>"}` in the body
- **THEN** the response SHALL be 200 with a new `access_token`

#### Scenario: Expired refresh token

- **WHEN** `POST /api/auth/refresh` is called with an expired refresh token
- **THEN** the response SHALL be 401

#### Scenario: Invalid refresh token

- **WHEN** `POST /api/auth/refresh` is called with a token not found in `user_refresh_tokens`
- **THEN** the response SHALL be 401

---

### Requirement: Sign-out via POST /api/auth/sign-out

The system SHALL expose `POST /api/auth/sign-out` that reads the refresh token from the `refresh_token` cookie or request body, deletes the corresponding record from `user_refresh_tokens`, and clears the `refresh_token` cookie. The endpoint SHALL return 200. If no valid refresh token is provided, the endpoint SHALL still return 200 (idempotent).

#### Scenario: Successful sign-out

- **WHEN** `POST /api/auth/sign-out` is called with a valid `refresh_token` cookie
- **THEN** the response SHALL be 200
- **AND** the refresh token record SHALL be deleted from `user_refresh_tokens`
- **AND** the `refresh_token` cookie SHALL be cleared

#### Scenario: Sign-out without refresh token

- **WHEN** `POST /api/auth/sign-out` is called without a refresh token
- **THEN** the response SHALL be 200

---

### Requirement: Password recovery via POST /api/auth/forgot-password

The system SHALL expose `POST /api/auth/forgot-password` accepting `email` (string). The endpoint SHALL always return 200 with a generic message regardless of whether the email exists. When the email exists and the user is active, the system SHALL generate a password reset token (stored as SHA-256 hash in `user_tokens` with `token_type=password_reset` and 1-hour TTL) and send a reset email with a link to `{FRONTEND_URL}/auth/reset-password?token={token}`. When the email does not exist or the user is not active, the system SHALL take no action.

#### Scenario: Forgot password with existing active user

- **WHEN** `POST /api/auth/forgot-password` is called with an email belonging to an active user
- **THEN** the response SHALL be 200 with a generic message
- **AND** a password reset token SHALL be created in `user_tokens`
- **AND** a reset email SHALL be sent

#### Scenario: Forgot password with non-existent email (enumeration protection)

- **WHEN** `POST /api/auth/forgot-password` is called with an email not in `users`
- **THEN** the response SHALL be 200 with the same generic message
- **AND** no email SHALL be sent

---

### Requirement: Password reset via POST /api/auth/reset-password

The system SHALL expose `POST /api/auth/reset-password` accepting `token` (string) and `new_password` (string). The system SHALL hash the token with SHA-256, look up the hash in `user_tokens` where `token_type=password_reset`, `used_at IS NULL`, and `expires_at > now()`. On match, the system SHALL update the user's `password_hash` with the new argon2id-hashed password, mark the token as used, and return 200. On invalid or expired token, the endpoint SHALL return 400.

#### Scenario: Successful password reset

- **WHEN** `POST /api/auth/reset-password` is called with a valid reset token and new password
- **THEN** the response SHALL be 200
- **AND** the user's `password_hash` SHALL be updated with the argon2id hash of the new password
- **AND** the token's `used_at` SHALL be set

#### Scenario: Expired reset token

- **WHEN** `POST /api/auth/reset-password` is called with an expired token
- **THEN** the response SHALL be 400

#### Scenario: Already-used reset token

- **WHEN** `POST /api/auth/reset-password` is called with a token that has `used_at IS NOT NULL`
- **THEN** the response SHALL be 400

---

### Requirement: Current user via GET /api/users/me

The system SHALL expose `GET /api/users/me` requiring authentication (`get_current_user` dependency). The endpoint SHALL return 200 with the current user's data including `id`, `email`, `status`, `email_verified_at`, `created_at`, and nested `profile` object containing `display_name` and `avatar_url`.

#### Scenario: Authenticated user retrieves profile

- **WHEN** `GET /api/users/me` is called with a valid access token
- **THEN** the response SHALL be 200 with the user's data and profile

#### Scenario: Unauthenticated request to /api/users/me

- **WHEN** `GET /api/users/me` is called without a valid access token
- **THEN** the response SHALL be 401

---

### Requirement: Profile update via PATCH /api/profile

The system SHALL expose `PATCH /api/profile` requiring authentication. The endpoint SHALL accept optional `display_name` (string) and `avatar_url` (string) fields. Only provided fields SHALL be updated. The endpoint SHALL return 200 with the updated user data and profile.

#### Scenario: Update display_name

- **WHEN** `PATCH /api/profile` is called with `{"display_name": "Bob"}` by an authenticated user
- **THEN** the response SHALL be 200
- **AND** the user's `user_profiles.display_name` SHALL be updated to "Bob"

#### Scenario: Unauthenticated request to PATCH /api/profile

- **WHEN** `PATCH /api/profile` is called without a valid access token
- **THEN** the response SHALL be 401

---

### Requirement: Guest whitelist (no auth required)

The following routes SHALL NOT require authentication: all `/api/auth/*` endpoints, `/health`, and `/ready`. `GET /api/users/me`, `PATCH /api/profile`, and all `/api/chat/*` endpoints SHALL require a valid JWT access token.

#### Scenario: Auth endpoints accessible without token

- **WHEN** `POST /api/auth/register`, `POST /api/auth/sign-in`, `POST /api/auth/refresh`, `POST /api/auth/sign-out`, `POST /api/auth/verify-email`, `POST /api/auth/forgot-password`, or `POST /api/auth/reset-password` is called without an access token
- **THEN** the request SHALL be processed normally (no 401)

#### Scenario: Health and ready endpoints accessible without token

- **WHEN** `GET /health` or `GET /ready` is called without an access token
- **THEN** the request SHALL be processed normally (no 401)

#### Scenario: Chat endpoints require token

- **WHEN** any `/api/chat/*` endpoint is called without a valid access token
- **THEN** the response SHALL be 401

---

### Requirement: Access token lifecycle

The JWT access token SHALL use HS256 algorithm, be signed with `JWT_SECRET_KEY` from environment, and have a TTL of 15 minutes. The payload SHALL contain `sub` (user_id as string), `exp`, `iat`, and `jti` (uuid4). The `get_current_user` FastAPI dependency SHALL extract the token from the `Authorization: Bearer` header, decode and verify signature and expiry using PyJWT, extract `user_id` from `sub`, load the user from the database, verify `status=active`, and return the `User` object. On invalid/expired token or missing user, raise 401. On blocked user (`status=blocked`), raise 403 Forbidden.

#### Scenario: Valid access token accepted

- **WHEN** a request includes `Authorization: Bearer <valid-jwt>` with a non-expired token for an active user
- **THEN** `get_current_user` SHALL return the `User` object

#### Scenario: Expired access token rejected

- **WHEN** a request includes `Authorization: Bearer <expired-jwt>`
- **THEN** `get_current_user` SHALL raise 401

#### Scenario: Invalid signature rejected

- **WHEN** a request includes a JWT signed with a different secret
- **THEN** `get_current_user` SHALL raise 401

#### Scenario: Blocked user rejected even with valid token

- **WHEN** a request includes a valid JWT for a user with `status=blocked`
- **THEN** `get_current_user` SHALL raise 403 Forbidden (not 401, to prevent infinite refresh loop — transport treats 401 as retry-able, 403 as terminal)

---

### Requirement: Refresh token lifecycle

Refresh tokens SHALL be generated using `secrets.token_urlsafe(32)`. The raw token SHALL be transported via httpOnly cookie or request body. Only the SHA-256 hash SHALL be stored in `user_refresh_tokens`. Refresh tokens SHALL have a 7-day TTL. On each refresh, the old token SHALL be deleted and a new one created (rotation). The httpOnly cookie SHALL use `Secure` flag controlled by `AUTH_COOKIE_SECURE`, `SameSite=Lax`, and `Path=/api/auth`.

#### Scenario: Refresh token rotation

- **WHEN** `POST /api/auth/refresh` is called with a valid refresh token
- **THEN** the old token hash SHALL be deleted from `user_refresh_tokens`
- **AND** a new token hash SHALL be inserted into `user_refresh_tokens`

#### Scenario: Refresh token stored as SHA-256 hash

- **WHEN** a refresh token is created (at sign-in or refresh)
- **THEN** only the SHA-256 hash SHALL be stored in `user_refresh_tokens.token_hash`
- **AND** the raw token SHALL never be persisted in the database

---

### Requirement: Password hashing with argon2id

All user passwords SHALL be hashed using argon2id via the `argon2-cffi` library. Password verification SHALL use timing-safe comparison (`secrets.compare_digest` or argon2-cffi's built-in verify). Plaintext passwords SHALL never be stored or logged.

#### Scenario: Password hashed at registration

- **WHEN** a new user registers with a password
- **THEN** the `users.password_hash` column SHALL contain an argon2id hash
- **AND** the plaintext password SHALL not appear in any database column or log

#### Scenario: Password verified at sign-in

- **WHEN** a user signs in with the correct password
- **THEN** the system SHALL verify the password against the stored argon2id hash using timing-safe comparison

---

### Requirement: Database tables for authentication

The system SHALL create four new tables: `users` (id UUID PK, email VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL, status ENUM pending/active/blocked default pending, email_verified_at TIMESTAMP nullable, created_at, updated_at), `user_profiles` (id UUID PK, user_id UUID FK to users UNIQUE NOT NULL ON DELETE CASCADE, display_name VARCHAR(255) nullable, avatar_url VARCHAR(2048) nullable, created_at, updated_at), `user_tokens` (id UUID PK, user_id UUID FK to users NOT NULL ON DELETE CASCADE, token_hash VARCHAR(255) NOT NULL indexed, token_type ENUM email_verification/password_reset NOT NULL, expires_at TIMESTAMP NOT NULL, used_at TIMESTAMP nullable, created_at), and `user_refresh_tokens` (id UUID PK, user_id UUID FK to users NOT NULL ON DELETE CASCADE indexed, token_hash VARCHAR(255) NOT NULL indexed, device_info VARCHAR(512) nullable, expires_at TIMESTAMP NOT NULL, created_at). All IDs SHALL use uuid7.

#### Scenario: Users table structure

- **WHEN** the migration is applied
- **THEN** the `users` table SHALL exist with columns `id`, `email`, `password_hash`, `status`, `email_verified_at`, `created_at`, `updated_at`
- **AND** `email` SHALL have a UNIQUE index

#### Scenario: User profiles table with cascade delete

- **WHEN** a user is deleted from `users`
- **THEN** the corresponding `user_profiles` record SHALL be automatically deleted (ON DELETE CASCADE)

#### Scenario: Token tables indexed on token_hash

- **WHEN** the migration is applied
- **THEN** `user_tokens.token_hash` and `user_refresh_tokens.token_hash` SHALL be indexed for efficient lookup

---

### Requirement: Pluggable email service

The system SHALL define an `EmailSender` protocol with method `async send(to: str, subject: str, html_body: str) -> None`. Two implementations SHALL be provided: `ConsoleEmailSender` (logs delivery metadata via structlog and MAY persist raw messages to `EMAIL_OUTBOX_DIR` in dev/test) and `ResendEmailSender` (sends via Resend API, used in production). The active implementation SHALL be selected via `EMAIL_BACKEND` environment variable (`console` or `resend`). Additional configuration: `RESEND_API_KEY` (required for resend backend), `EMAIL_FROM` (sender address), `FRONTEND_URL` (for constructing email links), `AUTH_COOKIE_SECURE` (refresh cookie Secure flag), and optional `EMAIL_OUTBOX_DIR` (console mail outbox for test automation). Email templates for verification and password reset SHALL be plain HTML strings in code.

#### Scenario: Console email backend in development

- **WHEN** `EMAIL_BACKEND=console`
- **THEN** the `ConsoleEmailSender` SHALL be used
- **AND** delivery metadata SHALL be logged via structlog instead of sending the email
- **AND** if `EMAIL_OUTBOX_DIR` is configured, the raw email payload SHALL be written there for test automation

#### Scenario: Resend email backend in production

- **WHEN** `EMAIL_BACKEND=resend`
- **THEN** the `ResendEmailSender` SHALL be used
- **AND** emails SHALL be sent via the Resend API using `RESEND_API_KEY`

#### Scenario: Verification email contains correct link

- **WHEN** a verification email is sent
- **THEN** the email body SHALL contain a link in the format `{FRONTEND_URL}/auth/verify-email?token={token}`

#### Scenario: Password reset email contains correct link

- **WHEN** a password reset email is sent
- **THEN** the email body SHALL contain a link in the format `{FRONTEND_URL}/auth/reset-password?token={token}`

---

### Requirement: Token cleanup job

Expired tokens in `user_tokens` and `user_refresh_tokens` SHALL be cleaned up by an arq cron job running every 6 hours. The job SHALL delete rows where `expires_at < now()`. For `user_tokens`, it SHALL also delete rows where `used_at IS NOT NULL` and `created_at` is older than 24 hours (already consumed tokens).

#### Scenario: Expired tokens cleaned up

- **WHEN** the token cleanup job runs
- **THEN** all rows in `user_tokens` with `expires_at < now()` SHALL be deleted
- **AND** all rows in `user_refresh_tokens` with `expires_at < now()` SHALL be deleted

#### Scenario: Cleanup job runs on schedule

- **WHEN** the arq worker is running
- **THEN** the token cleanup job SHALL execute every 6 hours

---

### Requirement: Token hashing security

All tokens (refresh tokens, email verification tokens, password reset tokens) SHALL be stored as SHA-256 hashes in the database. Raw tokens SHALL never be persisted. Token verification SHALL hash the incoming token and compare against the stored hash using timing-safe comparison (`secrets.compare_digest`).

#### Scenario: Token stored as hash

- **WHEN** any token (refresh, verification, reset) is created
- **THEN** only the SHA-256 hash SHALL be stored in the respective table's `token_hash` column

#### Scenario: Token verified via hash comparison

- **WHEN** a token is presented for verification (refresh, email verify, password reset)
- **THEN** the system SHALL hash the presented token with SHA-256 and compare against the stored hash using `secrets.compare_digest`
