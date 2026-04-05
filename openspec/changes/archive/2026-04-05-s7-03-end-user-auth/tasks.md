## 1. Dependencies and Configuration

- [x] 1.1 Add backend dependencies: PyJWT, argon2-cffi, resend, pydantic[email] to pyproject.toml; rebuild container
- [x] 1.2 Add auth settings to config.py: JWT_SECRET_KEY, JWT_ACCESS_TOKEN_EXPIRE_MINUTES, JWT_REFRESH_TOKEN_EXPIRE_DAYS, EMAIL_BACKEND, RESEND_API_KEY, EMAIL_FROM, FRONTEND_URL, cookie_secure computed property
- [x] 1.3 Update .env.example files with auth configuration section

## 2. Backend Auth Primitives

- [x] 2.1 Add UserStatus and TokenType enums to enums.py
- [x] 2.2 Implement password hashing service (argon2id): hash_password, verify_password + tests
- [x] 2.3 Implement JWT utility: create_access_token, decode_access_token + tests
- [x] 2.4 Implement pluggable email service: EmailSender protocol, ConsoleEmailSender, ResendEmailSender, build_email_sender factory + tests

## 3. Database Models and Migration

- [x] 3.1 Create auth models: User, UserProfile, UserToken, UserRefreshToken in db/models/auth.py
- [x] 3.2 Export new models in db/models/__init__.py
- [x] 3.3 Rename Session.visitor_id → user_id with FK to users in dialogue.py
- [x] 3.4 Generate and review Alembic migration 018: 4 new tables + column rename
- [x] 3.5 Run migration and verify

## 4. Auth Service

- [x] 4.1 Implement AuthService: register (with enumeration protection), verify_email, sign_in, refresh (token rotation), sign_out, forgot_password, reset_password, get_user_with_profile, update_profile + unit tests

## 5. Auth API Layer

- [x] 5.1 Implement get_current_user FastAPI dependency using Depends(get_session) + JWT decode + tests
- [x] 5.2 Create auth_schemas.py: RegisterRequest, SignInRequest, RefreshRequest, ForgotPasswordRequest, ResetPasswordRequest, VerifyEmailRequest, TokenResponse, MessageResponse, UserProfileResponse, UpdateProfileRequest
- [x] 5.3 Create auth_router.py with all /api/auth/* endpoints using Depends(get_auth_service)
- [x] 5.4 Add get_auth_service dependency to dependencies.py
- [x] 5.5 Create email sender in lifespan; include auth_router in main.py
- [x] 5.6 Write auth router endpoint tests; verify app starts with new endpoints in /docs

## 6. Protect Existing Endpoints

- [x] 6.1 Add get_current_user dependency to chat router; pass user_id to create_session
- [x] 6.2 Add session ownership checks: 403 for foreign sessions on get_session and the streaming send_message path
- [x] 6.3 Add user-filtered session list: GET /api/chat/sessions returns only current user's sessions
- [x] 6.4 Write chat auth tests: 401 without token, 403 for other user's session, filtered session list, streaming ownership
- [x] 6.5 Add get_current_user dependency to twin profile chat_router (profile.py)
- [x] 6.6 Update test_profile_api.py: unauthenticated → 401, authenticated → 200

## 7. Auth Rate Limiting and Cleanup

- [x] 7.1 Extend RateLimitMiddleware: add path-specific limits for /api/auth/sign-in, /register, /forgot-password, /reset-password (10 req/min); leave /api/auth/refresh unthrottled
- [x] 7.2 Add auth_sensitive_rate_limit and auth_sensitive_rate_window_seconds to config
- [x] 7.3 Implement token cleanup arq cron job (every 6h): delete expired tokens from user_tokens and user_refresh_tokens, AND delete used user_tokens (used_at IS NOT NULL) older than 24h; register in workers/main.py

## 8. Frontend Auth Core

- [x] 8.1 Create auth API client (auth-api.ts): register, signIn, refreshToken, signOut, forgotPassword, resetPassword, verifyEmail, getMe
- [x] 8.2 Create AuthContext (AuthProvider + useUserAuth hook): in-memory access token, silent refresh on mount, getAccessToken with dedup

## 9. Frontend Auth Pages

- [x] 9.1 Create AuthLayout (AuthPage.tsx): minimal wrapper with twin name from config
- [x] 9.2 Create SignInPage: email + password form, links to register and forgot-password
- [x] 9.3 Create RegisterPage: email + password + confirm + display_name, "check your email" success screen
- [x] 9.4 Create ForgotPasswordPage: email form, generic success message
- [x] 9.5 Create ResetPasswordPage: new password + confirm, token from URL query
- [x] 9.6 Create VerifyEmailPage: auto-submit token from URL, show success/error
- [x] 9.7 Create AdminSignInPage: dedicated admin API key entry page at /admin/sign-in

## 10. Frontend Routing and Integration

- [x] 10.1 Create ProtectedRoute component (redirect to /auth/sign-in if unauthenticated)
- [x] 10.2 Update App.tsx: add AuthProvider inside BrowserRouter, add /auth/* routes, wrap chat in ProtectedRoute, replace AdminRouteGuard modal with redirect to /admin/sign-in
- [x] 10.3 Add Authorization header to createSession and getSession in api.ts
- [x] 10.4 Add Authorization header to ProxyMindTransport SSE fetch in transport.ts; add accessToken to transport options
- [x] 10.5 Implement 401 retry in transport: on HTTP 401, call getAccessToken() for silent refresh, retry original request with new token; if refresh fails, redirect to /auth/sign-in
- [x] 10.6 Implement 403 handling in transport: on HTTP 403 (foreign session), surface error and trigger session re-creation via session hook
- [x] 10.7 Update useSession.ts: clear session on logout (via AuthContext signOut), handle 403 as session-not-found

## 11. Frontend Mocks and Tests

- [x] 11.1 Create MSW auth mock handlers (auth.ts): register, sign-in, refresh, sign-out, me, verify-email, forgot-password, reset-password
- [x] 11.2 Export auth handlers in mocks/handlers/index.ts
- [x] 11.3 Update api.test.ts: pass accessToken to createSession/getSession, verify Authorization header
- [x] 11.4 Update transport.test.ts: add accessToken to ProxyMindTransport options; add tests for 401 → silent refresh → retry, 401 → failed refresh → redirect to /auth/sign-in, and 403 → session re-creation trigger
- [x] 11.5 Update ChatPage.test.tsx: add /api/auth/refresh and /api/auth/me to fetchMock.mockImplementation URL handlers
- [x] 11.6 Update AdminPage.test.tsx: add auth URL handlers to fetchMock.mockImplementation
- [x] 11.7 Add ProtectedRoute tests: unauthenticated user redirected to /auth/sign-in, loading state during silent refresh, authenticated user sees chat
- [x] 11.8 Add useSession lifecycle tests: 403 from getSession triggers new session creation, sign-out clears proxymind_session_id from localStorage, sign-in creates fresh session
- [x] 11.9 Run bun run test and verify all frontend tests pass

## 12. Backend Integration Tests

- [x] 12.1 Write end-to-end auth flow test: register → verify → sign-in → access chat → refresh → sign-out → 401; AND forgot-password → reset-password → sign-in with new password
- [x] 12.2 Write ownership enforcement test: user A cannot access user B's session (403)
- [x] 12.3 Run full backend test suite and verify all pass

## 13. OpenSpec Sync and Finalization

- [x] 13.1 Create openspec/specs/end-user-auth/spec.md as new canonical spec (from delta)
- [x] 13.2 Update openspec/specs/chat-dialogue/spec.md with MODIFIED auth requirements
- [x] 13.3 Update openspec/specs/twin-profile/spec.md with MODIFIED auth requirements
- [x] 13.4 Update openspec/specs/chat-rate-limiting/spec.md with MODIFIED auth requirements
- [x] 13.5 Update openspec/specs/admin-knowledge-ui/spec.md with MODIFIED admin routing requirements
- [x] 13.6 Update openspec/specs/chat-ui-transport/spec.md with MODIFIED transport auth requirements
- [x] 13.7 Update openspec/specs/chat-ui/spec.md with MODIFIED session lifecycle requirements
- [x] 13.8 Update .env.example and docker-compose.yml with JWT_SECRET_KEY
