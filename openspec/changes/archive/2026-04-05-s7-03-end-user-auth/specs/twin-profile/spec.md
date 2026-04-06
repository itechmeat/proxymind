## Purpose

Delta spec for twin-profile capability modifications introduced by S7-03. Twin profile and avatar endpoints now require authentication. Twin name on auth pages is provided via `VITE_TWIN_NAME` env variable.

---

## MODIFIED Requirements

### Requirement: Public twin profile endpoint

The system SHALL expose `GET /api/chat/twin` as an authenticated endpoint (requires `get_current_user` dependency). The endpoint SHALL return a JSON object with `name` (string) and `has_avatar` (boolean) fields, sourced from the `agents` table for `DEFAULT_AGENT_ID`. The `has_avatar` field SHALL be derived from `avatar_url IS NOT NULL`. The response SHALL NOT expose any internal URLs or storage keys. Unauthenticated requests SHALL receive 401.

#### Scenario: Authenticated request with agent that has avatar

- **WHEN** `GET /api/chat/twin` is called with a valid access token and the agent has a non-null `avatar_url`
- **THEN** the response SHALL be 200 with `{ "name": "<agent name>", "has_avatar": true }`

#### Scenario: Authenticated request with agent without avatar

- **WHEN** `GET /api/chat/twin` is called with a valid access token and the agent has `avatar_url = NULL`
- **THEN** the response SHALL be 200 with `{ "name": "<agent name>", "has_avatar": false }`

#### Scenario: Unauthenticated request to twin profile

- **WHEN** `GET /api/chat/twin` is called without a valid access token
- **THEN** the response SHALL be 401

#### Scenario: Agent not found

- **WHEN** `GET /api/chat/twin` is called with a valid access token and no agent exists for `DEFAULT_AGENT_ID`
- **THEN** the response SHALL be 404

---

### Requirement: Public avatar proxy endpoint

The system SHALL expose `GET /api/chat/twin/avatar` as an authenticated endpoint (requires `get_current_user` dependency) that proxies the avatar image from SeaweedFS. The endpoint SHALL return the image bytes with the correct `Content-Type` header derived from the file extension. The browser SHALL NOT communicate with SeaweedFS directly. Unauthenticated requests SHALL receive 401.

#### Scenario: Authenticated request with avatar exists

- **WHEN** `GET /api/chat/twin/avatar` is called with a valid access token and the agent has a non-null `avatar_url`
- **THEN** the response SHALL contain the image bytes from SeaweedFS
- **AND** the `Content-Type` header SHALL match the image format (e.g., `image/png`, `image/jpeg`)

#### Scenario: Authenticated request with no avatar set

- **WHEN** `GET /api/chat/twin/avatar` is called with a valid access token and the agent has `avatar_url = NULL`
- **THEN** the response SHALL be 404

#### Scenario: Unauthenticated request to twin avatar

- **WHEN** `GET /api/chat/twin/avatar` is called without a valid access token
- **THEN** the response SHALL be 401

---

### Requirement: Twin name for unauthenticated UI via VITE_TWIN_NAME

The twin name displayed on frontend auth pages (sign-in, register, forgot-password, reset-password, verify-email) SHALL be sourced from the `VITE_TWIN_NAME` environment variable, NOT from the `/api/chat/twin` API endpoint. The `/api/chat/twin` endpoint is only available after authentication and SHALL NOT be called on auth pages. If `VITE_TWIN_NAME` is not set, the frontend SHALL fall back to "ProxyMind" as the default twin name.

#### Scenario: Auth pages display twin name from env var

- **WHEN** `VITE_TWIN_NAME=Marcus` is set and the user views the sign-in page
- **THEN** the page SHALL display "Marcus" as the twin name

#### Scenario: Auth pages fall back to default when env var not set

- **WHEN** `VITE_TWIN_NAME` is not set and the user views the sign-in page
- **THEN** the page SHALL display "ProxyMind" as the twin name

#### Scenario: Auth pages do not call twin API

- **WHEN** any auth page (`/auth/*`) is rendered
- **THEN** the frontend SHALL NOT make a request to `GET /api/chat/twin`
