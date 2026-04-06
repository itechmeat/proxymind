## MODIFIED Requirements

### Requirement: HTTP error handling

The transport SHALL handle HTTP error responses from the backend as follows:

- **HTTP 401** (unauthorized): Attempt a silent token refresh via `AuthProvider.getAccessToken()`. If refresh succeeds, retry the original request with the new access token. If refresh fails, surface an authentication error to the UI and redirect to `/auth/sign-in`.
- **HTTP 403** (forbidden): Surface the error to the UI. Trigger session re-creation via the session hook only when the backend detail indicates session ownership (`"Session belongs to a different user"`). Other 403 responses SHALL remain terminal UI errors and SHALL NOT invalidate the session.
- **HTTP 409** (concurrent stream or idempotency conflict): Surface the error to the UI. This SHALL NOT be silently ignored.
- **HTTP 422** (no active snapshot): Surface a "knowledge not ready" error to the UI.
- **HTTP 404** (session not found): Trigger session re-creation via the session hook.
- **Network failure** (`TypeError` from fetch): Surface a connection error to the UI.

#### Scenario: HTTP 401 triggers silent refresh and retry

- **WHEN** the backend responds with HTTP 401
- **THEN** the transport SHALL attempt to refresh the access token
- **AND** if refresh succeeds, the transport SHALL retry the original request with the new token

#### Scenario: HTTP 401 after failed refresh redirects to sign-in

- **WHEN** the backend responds with HTTP 401
- **AND** the token refresh also fails
- **THEN** the transport SHALL surface an authentication error
- **AND** the user SHALL be redirected to `/auth/sign-in`

#### Scenario: HTTP 403 triggers session re-creation

- **WHEN** the backend responds with HTTP 403 (session belongs to another user)
- **THEN** the transport SHALL surface an error to the UI
- **AND** the session hook SHALL clear the stored session and create a new one

#### Scenario: Non-ownership HTTP 403 stays terminal

- **WHEN** the backend responds with HTTP 403 for a reason other than session ownership
- **THEN** the transport SHALL surface the error to the UI
- **AND** the current session SHALL remain intact

#### Scenario: HTTP 409 surfaced as error

- **WHEN** the backend responds with HTTP 409 and body `{"detail": "Concurrent stream active"}`
- **THEN** the transport SHALL surface an error to the UI with the detail message
- **AND** the error SHALL NOT be silently swallowed

#### Scenario: HTTP 422 surfaced as knowledge not ready

- **WHEN** the backend responds with HTTP 422
- **THEN** the transport SHALL surface a "knowledge not ready" error to the UI

#### Scenario: Network failure surfaced as connection error

- **WHEN** the fetch request throws a `TypeError`
- **THEN** the transport SHALL surface a connection error to the UI

---

### Requirement: Authentication header on SSE requests

The transport SHALL include an `Authorization: Bearer <access_token>` header on all fetch requests to `POST /api/chat/messages`. The access token SHALL be retrieved at request time via the transport's `getAccessToken()` option so silent refresh can update the value between sends. Since the transport uses `fetch()` (not `EventSource`), custom headers are natively supported — the token SHALL NOT be passed as a query parameter.

#### Scenario: SSE request includes auth header

- **WHEN** the transport sends a message via `POST /api/chat/messages`
- **THEN** the fetch request SHALL include `Authorization: Bearer <access_token>` header

#### Scenario: Missing access token prevents request

- **WHEN** the transport attempts to send a message without an access token
- **THEN** the transport SHALL surface an authentication error to the UI
