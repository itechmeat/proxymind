## Purpose

Delta spec for chat-dialogue capability modifications introduced by S7-03. All chat endpoints now require authenticated user context, session creation sets user_id, and session read/write enforces ownership. The `visitor_id` column is renamed to `user_id`.

---

## MODIFIED Requirements

### Requirement: Session creation via POST /api/chat/sessions

The system SHALL provide a `POST /api/chat/sessions` endpoint that creates a new chat session. The endpoint SHALL require authentication via the `get_current_user` dependency. The endpoint SHALL accept an optional `channel` field (default `"web"`). The session SHALL be created with `agent_id` set to `DEFAULT_AGENT_ID` and `user_id` set to the authenticated user's `id`. The `snapshot_id` SHALL be set to the currently active snapshot at creation time, or `null` if no active snapshot exists. The endpoint SHALL return 201 Created with the session data. Unauthenticated requests SHALL receive 401.

#### Scenario: Create session with authenticated user

- **WHEN** `POST /api/chat/sessions` is called with a valid access token and `{"channel": "web"}` and an active snapshot exists
- **THEN** the response SHALL be 201
- **AND** the session's `user_id` SHALL be set to the authenticated user's `id`
- **AND** the response SHALL contain `id` (UUID), `snapshot_id` (UUID of the active snapshot), `channel` ("web"), `status` ("active"), `message_count` (0), and `created_at`

#### Scenario: Create session without authentication

- **WHEN** `POST /api/chat/sessions` is called without a valid access token
- **THEN** the response SHALL be 401

#### Scenario: Create session without active snapshot

- **WHEN** `POST /api/chat/sessions` is called with a valid access token and no active snapshot exists
- **THEN** the response SHALL be 201
- **AND** `snapshot_id` SHALL be `null`

#### Scenario: Create session with default channel

- **WHEN** `POST /api/chat/sessions` is called with a valid access token and an empty body
- **THEN** the response SHALL be 201 with `channel` set to `"web"`

---

### Requirement: Message send via POST /api/chat/messages

The system SHALL require authentication via the `get_current_user` dependency on `POST /api/chat/messages`. Before processing the message, the system SHALL verify that `session.user_id == current_user.id`. If the session belongs to a different user, the endpoint SHALL return 403 Forbidden. All other behavior (message persistence, query rewriting, retrieval, prompt assembly, SSE streaming, content type spans, audit logging, summary enqueue) SHALL remain unchanged from the existing spec.

#### Scenario: Authenticated user sends message to own session

- **WHEN** `POST /api/chat/messages` is called with a valid access token and a `session_id` belonging to the authenticated user
- **THEN** the message SHALL be processed normally (existing behavior preserved)

#### Scenario: Unauthenticated message send

- **WHEN** `POST /api/chat/messages` is called without a valid access token
- **THEN** the response SHALL be 401

#### Scenario: Message send to another user's session

- **WHEN** `POST /api/chat/messages` is called with a valid access token but a `session_id` belonging to a different user
- **THEN** the response SHALL be 403 Forbidden

---

### Requirement: Session history via GET /api/chat/sessions/:id

The system SHALL require authentication via the `get_current_user` dependency on `GET /api/chat/sessions/{session_id}`. Before returning the session, the system SHALL verify that `session.user_id == current_user.id`. If the session belongs to a different user, the endpoint SHALL return 403 Forbidden. All other behavior (message ordering, CitationResponse structure, 404 for non-existent sessions) SHALL remain unchanged from the existing spec.

#### Scenario: Authenticated user reads own session

- **WHEN** `GET /api/chat/sessions/{session_id}` is called with a valid access token and the session belongs to the authenticated user
- **THEN** the response SHALL be 200 with the session data and messages (existing behavior preserved)

#### Scenario: Unauthenticated session read

- **WHEN** `GET /api/chat/sessions/{session_id}` is called without a valid access token
- **THEN** the response SHALL be 401

#### Scenario: Reading another user's session

- **WHEN** `GET /api/chat/sessions/{session_id}` is called with a valid access token but the session belongs to a different user
- **THEN** the response SHALL be 403 Forbidden

#### Scenario: Non-existent session still returns 404

- **WHEN** `GET /api/chat/sessions/{session_id}` is called with a valid access token and a UUID that does not match any session
- **THEN** the response SHALL be 404 with detail "Session not found"

---

### Requirement: Session list filtered by authenticated user

The system SHALL require authentication via the `get_current_user` dependency on `GET /api/chat/sessions`. The endpoint SHALL return only sessions where `user_id == current_user.id`. A user SHALL NOT be able to see sessions belonging to other users.

#### Scenario: User sees only their own sessions

- **WHEN** `GET /api/chat/sessions` is called with a valid access token
- **THEN** the response SHALL contain only sessions where `user_id` matches the authenticated user's `id`

#### Scenario: Unauthenticated session list

- **WHEN** `GET /api/chat/sessions` is called without a valid access token
- **THEN** the response SHALL be 401

---

### Requirement: visitor_id renamed to user_id in sessions table

The `sessions` table column `visitor_id` SHALL be renamed to `user_id`. A foreign key `sessions.user_id -> users(id) ON DELETE SET NULL` SHALL be added. The `user_id` column SHALL remain nullable (for future channel connectors using `external_user_id`). The `external_user_id` and `channel_connector` columns SHALL remain unchanged.

#### Scenario: Column renamed in migration

- **WHEN** the migration is applied
- **THEN** the `sessions` table SHALL have a `user_id` column instead of `visitor_id`
- **AND** a foreign key to `users(id)` with `ON DELETE SET NULL` SHALL exist

#### Scenario: Existing sessions with NULL visitor_id migrate cleanly

- **WHEN** the migration runs on a database with existing sessions that have `visitor_id=NULL`
- **THEN** those sessions SHALL have `user_id=NULL` after migration
- **AND** no data loss SHALL occur
