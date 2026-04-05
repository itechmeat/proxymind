## Purpose

Twin profile management: backend API for reading and updating the twin's name and avatar, frontend profile loading with fallback chain, settings modal with avatar upload/preview, and avatar storage contract via SeaweedFS proxy. Introduced by S5-02.

---

## ADDED Requirements

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

---

### Requirement: Admin profile name update

The system SHALL expose `PUT /api/admin/agent/profile` to update the agent's name. The `name` field MUST be a non-empty string with a maximum length of 255 characters. The endpoint SHALL return the updated profile as `{ "name": "<new name>", "has_avatar": <boolean> }`.

#### Scenario: Valid name update

- **WHEN** `PUT /api/admin/agent/profile` is called with `{ "name": "Marcus Aurelius" }`
- **THEN** the agent's name SHALL be updated in the database
- **AND** the response SHALL be 200 with the updated profile

#### Scenario: Name exceeds maximum length

- **WHEN** `PUT /api/admin/agent/profile` is called with a name longer than 255 characters
- **THEN** the response SHALL be 422 (validation error)

---

### Requirement: Admin avatar upload

The system SHALL expose `POST /api/admin/agent/avatar` accepting a multipart form upload with field `file`. The endpoint SHALL validate that the declared content type is one of `image/jpeg`, `image/png`, `image/webp`, `image/gif`, SHALL verify that the uploaded bytes match the declared image signature, and SHALL reject files larger than 2 MB. On success, the endpoint SHALL store the file in SeaweedFS, save the object key in `agents.avatar_url`, and delete the previous avatar file from SeaweedFS if one existed.

#### Scenario: Valid image upload

- **WHEN** a valid PNG file under 2 MB is uploaded via `POST /api/admin/agent/avatar`
- **THEN** the file SHALL be stored in SeaweedFS with key format `agents/{agent_id}/avatar/{uuid}.{ext}`
- **AND** `agents.avatar_url` SHALL be updated to the new object key
- **AND** the response SHALL be 200 with `{ "has_avatar": true }`

#### Scenario: Previous avatar replaced

- **WHEN** an avatar is uploaded and the agent already has an existing avatar
- **THEN** the old avatar file SHALL be deleted from SeaweedFS (best-effort)
- **AND** `agents.avatar_url` SHALL be updated to the new object key

#### Scenario: Invalid content type rejected

- **WHEN** a file with content type `text/plain` is uploaded via `POST /api/admin/agent/avatar`
- **THEN** the response SHALL be 422
- **AND** no file SHALL be stored in SeaweedFS

#### Scenario: Spoofed image content rejected

- **WHEN** a file is uploaded with declared content type `image/png` but the file bytes are not a valid PNG image
- **THEN** the response SHALL be 422
- **AND** no file SHALL be stored in SeaweedFS

#### Scenario: Oversized file rejected

- **WHEN** a file larger than 2 MB is uploaded via `POST /api/admin/agent/avatar`
- **THEN** the response SHALL be 422
- **AND** no file SHALL be stored in SeaweedFS

---

### Requirement: Admin avatar deletion

The system SHALL expose `DELETE /api/admin/agent/avatar` to remove the agent's avatar. The endpoint SHALL delete the file from SeaweedFS (best-effort) and set `agents.avatar_url` to `NULL`.

#### Scenario: Avatar exists and is deleted

- **WHEN** `DELETE /api/admin/agent/avatar` is called and the agent has an avatar
- **THEN** the avatar file SHALL be deleted from SeaweedFS
- **AND** `agents.avatar_url` SHALL be set to `NULL`
- **AND** the response SHALL be 200 with `{ "has_avatar": false }`

#### Scenario: No avatar to delete

- **WHEN** `DELETE /api/admin/agent/avatar` is called and the agent has no avatar
- **THEN** `agents.avatar_url` SHALL remain `NULL`
- **AND** the response SHALL be 200 with `{ "has_avatar": false }`

---

### Requirement: Frontend profile loading

The ChatPage component SHALL fetch the twin profile from `GET /api/chat/twin` on mount. If the API call fails, the system SHALL fall back to environment variables (`appConfig.twinName`, `appConfig.twinAvatarUrl`). If environment variables are also absent, the system SHALL use defaults (name: "ProxyMind", avatar: initials-based fallback).

#### Scenario: API returns profile successfully

- **WHEN** the ChatPage mounts and `GET /api/chat/twin` returns 200
- **THEN** the header and message avatars SHALL display the name and avatar from the API response

#### Scenario: API unavailable, env vars present

- **WHEN** the ChatPage mounts and `GET /api/chat/twin` fails
- **AND** `appConfig.twinName` is set
- **THEN** the header SHALL display the name from `appConfig.twinName`

#### Scenario: API unavailable, no env vars

- **WHEN** the ChatPage mounts and `GET /api/chat/twin` fails
- **AND** no environment variables are configured
- **THEN** the header SHALL display "ProxyMind" as the default name

---

### Requirement: Settings button gated by VITE_ADMIN_MODE

The ChatHeader SHALL render a Settings icon button only when `import.meta.env.VITE_ADMIN_MODE === "true"`. This is a UI-only visibility guard. It SHALL NOT protect backend endpoints. Backend admin endpoints SHALL remain unprotected until S7-01 (auth + rate limiting) is implemented, which MUST happen before any non-local deployment.

#### Scenario: Admin mode enabled

- **WHEN** `VITE_ADMIN_MODE` is set to `"true"`
- **THEN** the Settings button SHALL be visible in the ChatHeader

#### Scenario: Admin mode disabled or unset

- **WHEN** `VITE_ADMIN_MODE` is not set or is set to a value other than `"true"`
- **THEN** the Settings button SHALL NOT be rendered in the ChatHeader

#### Scenario: UI guard does not protect backend

- **WHEN** `VITE_ADMIN_MODE` is `"false"` but a direct HTTP request is made to `PUT /api/admin/agent/profile`
- **THEN** the backend SHALL still process the request (no server-side auth check exists until S7-01)

---

### Requirement: ProfileEditModal

The system SHALL provide a `ProfileEditModal` component using Radix Dialog. The modal SHALL contain: a name text input pre-filled with the current name, a Save button that calls the profile update API, an avatar upload zone that triggers a hidden file input on click, a Remove Avatar button (visible only when an avatar exists), and a close mechanism via Escape key, click outside, or X button.

#### Scenario: Name editing and save

- **WHEN** the user changes the name input and clicks Save
- **THEN** `PUT /api/admin/agent/profile` SHALL be called with the new name
- **AND** the ChatHeader and message avatars SHALL reflect the updated name without page reload

#### Scenario: Avatar upload with local preview

- **WHEN** the user selects a file via the avatar upload zone
- **THEN** the modal SHALL immediately display a local preview using `URL.createObjectURL(file)` before the upload completes
- **AND** `POST /api/admin/agent/avatar` SHALL be called with the selected file
- **AND** on success, the avatar in the header and messages SHALL update

#### Scenario: Avatar removal

- **WHEN** the user clicks "Remove avatar" and an avatar exists
- **THEN** `DELETE /api/admin/agent/avatar` SHALL be called
- **AND** the avatar SHALL revert to the initials fallback

#### Scenario: Modal close

- **WHEN** the user presses Escape, clicks outside the modal, or clicks the X button
- **THEN** the modal SHALL close
- **AND** any unsaved name changes SHALL be discarded

#### Scenario: No avatar — remove button hidden

- **WHEN** the modal is open and `has_avatar` is `false`
- **THEN** the "Remove avatar" button SHALL NOT be rendered

---

### Requirement: Avatar storage contract

The `agents.avatar_url` column SHALL store the SeaweedFS object key (e.g., `agents/{agent_id}/avatar/{uuid}.{ext}`), NOT a full URL. The browser SHALL access avatar images exclusively through the `GET /api/chat/twin/avatar` proxy endpoint. The frontend SHALL construct the avatar `<img src>` as `buildApiUrl("/api/chat/twin/avatar")`, not from any field in the profile API response.

#### Scenario: Database stores object key

- **WHEN** an avatar is uploaded successfully
- **THEN** `agents.avatar_url` SHALL contain a path like `agents/{id}/avatar/{uuid}.png`
- **AND** SHALL NOT contain a protocol prefix (e.g., `http://`)

#### Scenario: Frontend uses proxy URL

- **WHEN** the frontend renders an avatar image
- **THEN** the `<img src>` attribute SHALL be set to the proxy endpoint URL (`/api/chat/twin/avatar`)
- **AND** SHALL NOT reference SeaweedFS directly

---

### Requirement: Test coverage for profile behavior

All stable profile behavior MUST be covered by deterministic CI tests. Backend tests SHALL cover: `GET /api/chat/twin` success, `PUT /api/admin/agent/profile` name update, `POST /api/admin/agent/avatar` type validation and size validation, `GET /api/chat/twin/avatar` 404 when no avatar, and `DELETE /api/admin/agent/avatar` removal. Frontend tests SHALL cover: ProfileEditModal rendering, name save interaction, avatar file input presence, local preview after file selection, remove button visibility, and settings button gating by admin mode.

#### Scenario: Backend profile API tests pass

- **WHEN** the backend test suite runs
- **THEN** tests for all five profile endpoints SHALL pass
- **AND** avatar upload tests SHALL cover both declared content type validation and file-signature validation
- **AND** tests SHALL be deterministic (no dependency on external services)

#### Scenario: Frontend profile component tests pass

- **WHEN** the frontend test suite runs
- **THEN** tests for ProfileEditModal (open/close, name save, file input, local preview, remove button visibility) SHALL pass
- **AND** tests for ChatHeader settings button gating SHALL pass
