## Purpose

Delta modifications to the chat-dialogue capability for SSE streaming support. Introduced by S4-02.

## ADDED Requirements

### Requirement: Parent message ID for user-assistant pairing

The `messages` table SHALL have a `parent_message_id` column (nullable UUID, foreign key to `messages.id`). This column SHALL be set on assistant messages to link back to the user message they respond to. The column SHALL be added via an Alembic migration. User messages SHALL have `parent_message_id` set to `null`. This explicit pairing supports reliable idempotency lookup (finding the assistant response for a given user message) and is more robust than implicit pairing via timestamps or ordering.

#### Scenario: Assistant message linked to user message

- **WHEN** a user sends a message and the system generates an assistant response
- **THEN** the assistant message SHALL have `parent_message_id` set to the user message's `id`

#### Scenario: User message has no parent

- **WHEN** a user message is saved
- **THEN** `parent_message_id` SHALL be `null`

#### Scenario: Idempotency lookup uses parent_message_id

- **WHEN** an idempotency key matches a user message
- **THEN** the system SHALL find the paired assistant message by querying `parent_message_id` equal to the user message's `id`

---

### Requirement: Save partial content on disconnect

The `ChatService` SHALL provide a `save_partial_on_disconnect` method (or equivalent logic) that is invoked when a client disconnects during an active SSE stream. This method SHALL save the accumulated content buffer to the assistant message, update the assistant message status to PARTIAL, and persist the change to the database. This ensures no generated content is lost on client disconnect.

#### Scenario: Partial content saved on disconnect

- **WHEN** the client disconnects after the LLM has emitted some tokens
- **THEN** the assistant message SHALL be updated with status PARTIAL and the accumulated content

#### Scenario: Empty partial saved on early disconnect

- **WHEN** the client disconnects before any LLM tokens are received (but after the assistant message is created)
- **THEN** the assistant message SHALL be updated with status PARTIAL and empty content

---

### Requirement: Save failed content on timeout

The `ChatService` SHALL provide a `save_failed_on_timeout` method (or equivalent logic) that is invoked when the inter-token timeout fires during an active SSE stream. This method SHALL save any accumulated content buffer to the assistant message, update the assistant message status to FAILED, and persist the change to the database.

#### Scenario: Failed content saved on timeout

- **WHEN** the inter-token timeout fires after some tokens have been received
- **THEN** the assistant message SHALL be updated with status FAILED and the accumulated content

#### Scenario: Failed with no content on early timeout

- **WHEN** the inter-token timeout fires before any LLM tokens are received
- **THEN** the assistant message SHALL be updated with status FAILED and empty content

---

## MODIFIED Requirements

### Requirement: Message send via POST /api/chat/messages

The system SHALL provide a `POST /api/chat/messages` endpoint that accepts `session_id` (UUID), `text` (non-empty string), and an optional `idempotency_key` (string, client-generated) in the `SendMessageRequest`. The endpoint SHALL save the user message with `role=user`, `status=received`, and `idempotency_key` (when provided), then perform retrieval against the session's active snapshot, assemble a prompt using the retrieval context and the loaded `PersonaContext`, and stream the assistant's response as SSE (`text/event-stream; charset=utf-8`) with status 200.

The `ChatService` SHALL provide a `stream_answer()` method alongside the existing `answer()` method. The existing `answer()` method SHALL be preserved (used by tests and non-streaming internal calls such as query rewriting in S4-04). The `stream_answer()` method SHALL receive `PersonaContext` and pass it to `build_chat_prompt(query, chunks, persona)` for system message assembly that includes the safety policy and persona layers.

The assistant message SHALL be created with `role=assistant`, `status=streaming`, and `parent_message_id` set to the user message's `id` before the first SSE event is emitted. Upon successful completion, the assistant message SHALL be updated to `status=complete` with `content`, `model_name`, token counts (`token_count_prompt`, `token_count_completion`), deduplicated `source_ids` from retrieved chunks, and audit hashes (`config_commit_hash`, `config_content_hash` from `PersonaContext`).

Pre-stream errors (session not found, no active snapshot, concurrent stream conflict, idempotency conflict for STREAMING) SHALL return standard HTTP error codes (404, 409, 422) as JSON responses — the SSE stream SHALL NOT be opened for these cases. The old hardcoded `SYSTEM_PROMPT` SHALL be removed and replaced by `SYSTEM_SAFETY_POLICY` plus persona layers.

On every response — both the LLM-generated response path (`chat.assistant_completed`) and the code-level refusal path (`chat.refusal_returned`) — `ChatService` SHALL log `config_commit_hash` and `config_content_hash` from the `PersonaContext` via structlog. The response SHALL include a runtime-computed `retrieved_chunks_count` field (delivered in the `done` or `meta` SSE event as appropriate).

#### Scenario: Successful message with SSE streaming response

- **WHEN** `POST /api/chat/messages` is called with a valid `session_id` and `text`, and the session has an active snapshot with indexed chunks
- **THEN** the response SHALL be 200 with `Content-Type: text/event-stream; charset=utf-8`
- **AND** the SSE stream SHALL emit `meta` (with `message_id`, `session_id`, `snapshot_id`), then one or more `token` events, then `done` (with `token_count_prompt`, `token_count_completion`, `model_name`)

#### Scenario: User message is persisted before streaming begins

- **WHEN** `POST /api/chat/messages` is called with valid data
- **THEN** a user message record SHALL be saved with `role=user`, `status=received`, and `idempotency_key` (when provided) before the retrieval and LLM steps execute

#### Scenario: Assistant message created with STREAMING status before first event

- **WHEN** the system is about to start streaming the LLM response
- **THEN** an assistant message SHALL be created with `status=streaming` and `parent_message_id` set to the user message's `id`
- **AND** the `meta` SSE event SHALL be emitted with this assistant message's `id`

#### Scenario: Session message_count is updated after successful response

- **WHEN** a message exchange completes successfully (assistant message reaches COMPLETE status)
- **THEN** the session's `message_count` SHALL be incremented to reflect both the user and assistant messages

#### Scenario: PersonaContext is injected into prompt assembly

- **WHEN** `ChatService.stream_answer()` assembles the LLM prompt
- **THEN** it SHALL call `build_chat_prompt(query, chunks, persona)` with the `PersonaContext` from `app.state`
- **AND** the system message SHALL contain the safety policy followed by persona layers (identity, soul, behavior) with empty sections skipped

#### Scenario: Config hashes logged on successful LLM response

- **WHEN** the LLM returns a successful response and the assistant message is saved with `status=complete`
- **THEN** structlog SHALL emit a `chat.assistant_completed` event
- **AND** the log entry SHALL include `config_commit_hash` and `config_content_hash` from the `PersonaContext`

#### Scenario: Config hashes logged on code-level refusal

- **WHEN** retrieval returns fewer chunks than `min_retrieved_chunks` and the system returns a refusal without calling the LLM
- **THEN** structlog SHALL emit a `chat.refusal_returned` event
- **AND** the log entry SHALL include `config_commit_hash` and `config_content_hash` from the `PersonaContext`

#### Scenario: Old SYSTEM_PROMPT no longer used

- **WHEN** the chat message flow assembles a prompt
- **THEN** the old hardcoded `SYSTEM_PROMPT` constant SHALL NOT be referenced
- **AND** the system message SHALL be assembled from `SYSTEM_SAFETY_POLICY` plus persona layers via `build_chat_prompt`

#### Scenario: SendMessageRequest accepts optional idempotency_key

- **WHEN** `POST /api/chat/messages` is called with `{"session_id": "...", "text": "...", "idempotency_key": "client-key-123"}`
- **THEN** the request SHALL be accepted and the `idempotency_key` SHALL be stored on the user message

#### Scenario: Existing answer() method preserved

- **WHEN** `ChatService` is used after S4-02 implementation
- **THEN** the `answer()` method SHALL remain available and functional with the same signature and behavior

---

### Requirement: Error handling for chat endpoints

The chat endpoints SHALL handle errors as follows:

- Session not found: `ChatService` SHALL raise `SessionNotFoundError`, router SHALL return 404.
- No active snapshot after lazy-bind attempt: `ChatService` SHALL raise `NoActiveSnapshotError`, router SHALL return 422.
- Empty or missing `text` in message request: Pydantic validation SHALL return 422 automatically.
- Concurrent stream in session: the system SHALL detect an existing STREAMING assistant message in the session and return 409 Conflict. This check runs after the idempotency check.
- Idempotency conflict (STREAMING in flight): when the idempotency key matches a user message whose paired assistant message has status STREAMING, the endpoint SHALL return 409 Conflict.
- LLM call failure during stream: the system SHALL emit an `error` SSE event, save the assistant message with `status=failed` (including any accumulated content), and close the stream.
- Qdrant or embedding failure (retrieval error): `ChatService` SHALL persist an assistant message with `status=failed` before re-raising; router SHALL return 500. This occurs pre-stream, so standard HTTP error codes are used.

After a user message is saved, any subsequent error MUST result in a persisted assistant message with `status=failed` (for pre-stream errors) or appropriate terminal status (FAILED for mid-stream errors, PARTIAL for disconnect) for observability.

#### Scenario: Session not found returns 404

- **WHEN** `POST /api/chat/messages` is called with a `session_id` that does not exist
- **THEN** the response SHALL be 404 with detail "Session not found"

#### Scenario: No active snapshot returns 422

- **WHEN** `POST /api/chat/messages` is called for a session with `snapshot_id=null` and no active snapshot exists
- **THEN** the response SHALL be 422

#### Scenario: Empty text returns 422

- **WHEN** `POST /api/chat/messages` is called with `text` as an empty string or missing
- **THEN** the response SHALL be 422 (Pydantic validation error)

#### Scenario: Concurrent stream returns 409

- **WHEN** `POST /api/chat/messages` is called for a session that already has an assistant message with status STREAMING
- **THEN** the response SHALL be 409 Conflict

#### Scenario: Idempotency conflict for STREAMING returns 409

- **WHEN** `POST /api/chat/messages` is called with an `idempotency_key` whose paired assistant message has status STREAMING
- **THEN** the response SHALL be 409 Conflict

#### Scenario: LLM failure during stream emits error event and saves FAILED

- **WHEN** the LLM call fails during SSE streaming
- **THEN** an `error` SSE event SHALL be emitted with a detail describing the failure
- **AND** the assistant message SHALL be saved with `status=failed` and any accumulated content
- **AND** the stream SHALL be closed

#### Scenario: Qdrant failure returns 500 with failed message persisted

- **WHEN** the Qdrant search fails during message processing (pre-stream)
- **THEN** an assistant message SHALL be saved with `status=failed`
- **AND** the response SHALL be 500

#### Scenario: Retrieval error persists FAILED then raises

- **WHEN** the embedding or Qdrant call fails during retrieval
- **THEN** the system SHALL persist an assistant message with `status=failed`
- **AND** SHALL re-raise the exception so the router returns HTTP 500
