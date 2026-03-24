## Purpose

Delta spec for S4-03 Citation Builder: activates the `citations` SSE event type reserved in S4-02, adds citation replay to idempotency, and defines the `ChatStreamCitations` event dataclass.

## MODIFIED Requirements

### Requirement: SSE protocol and event types

The system SHALL stream chat responses using the Server-Sent Events (SSE) protocol with `Content-Type: text/event-stream; charset=utf-8`. The system SHALL support the following event types:

- `meta` — first event, payload `{message_id, session_id, snapshot_id}`, emitted after creating the assistant message with STREAMING status.
- `token` — payload `{content: "..."}`, emitted for each non-empty chunk from the LLM.
- `citations` — payload `{citations: [...]}`, emitted after all `token` events and before `done`. The `citations` array SHALL contain citation objects produced by the citation service. When no citations are extracted, the event SHALL still be emitted with an empty array (`{citations: []}`). For assistant messages that reach `partial` or `failed` status, the `citations` event SHALL NOT be emitted.
- `done` — payload `{token_count_prompt, token_count_completion, model_name, retrieved_chunks_count}`, emitted when generation is complete (COMPLETE status). Token count fields SHALL be nullable (for providers that do not report usage). `retrieved_chunks_count` SHALL be an integer representing the number of chunks passed to the LLM (0 for refusal responses).
- `error` — payload `{detail: "..."}`, emitted on LLM error or internal error (FAILED status).

Each event SHALL be formatted as `event: {type}\ndata: {json}\n\n`. The HTTP status SHALL always be `200` once streaming begins. Pre-stream errors (session not found, validation failure, concurrency conflict) SHALL use standard HTTP status codes (404, 409, 422) and SHALL NOT start an SSE stream.

#### Scenario: Normal SSE stream event sequence

- **WHEN** a message is sent and the LLM generates a response
- **THEN** the SSE stream SHALL emit events in the order: `meta` (exactly once), then one or more `token` events, then `citations` (exactly once), then `done` (exactly once)
- **AND** each event SHALL conform to the wire format `event: {type}\ndata: {json}\n\n`

#### Scenario: Citations event with no citations

- **WHEN** the LLM generates a response and the citation service extracts zero citations
- **THEN** the SSE stream SHALL emit a `citations` event with payload `{citations: []}`
- **AND** the event SHALL appear after all `token` events and before `done`

#### Scenario: Citations event not emitted for partial messages

- **WHEN** the client disconnects mid-stream and the assistant message status becomes PARTIAL
- **THEN** the `citations` event SHALL NOT be emitted

#### Scenario: Citations event not emitted for failed messages

- **WHEN** an LLM error or inter-token timeout occurs and the assistant message status becomes FAILED
- **THEN** the `citations` event SHALL NOT be emitted

#### Scenario: Content-Type header

- **WHEN** the SSE stream response is returned
- **THEN** the `Content-Type` header SHALL be `text/event-stream; charset=utf-8`

#### Scenario: HTTP 200 once streaming begins

- **WHEN** the SSE stream has started (first event emitted)
- **THEN** the HTTP status code SHALL be `200`
- **AND** any errors after this point SHALL be delivered as `error` SSE events, not HTTP error codes

#### Scenario: Pre-stream errors use standard HTTP codes

- **WHEN** an error occurs before the SSE stream starts (e.g., session not found, no active snapshot, concurrent stream conflict)
- **THEN** the response SHALL use the appropriate HTTP status code (404, 409, 422)
- **AND** no SSE stream SHALL be opened

#### Scenario: Error event during stream

- **WHEN** an LLM error or internal error occurs after streaming has begun
- **THEN** the system SHALL emit an `error` event with a `detail` field describing the error
- **AND** the stream SHALL be closed after the error event

---

### Requirement: Idempotency key for message requests

The `POST /api/chat/messages` endpoint SHALL accept an optional `idempotency_key` field (string, client-generated) in the request body. When provided, the system SHALL use it to prevent duplicate processing on retry. The idempotency logic SHALL execute as follows:

1. Look up a user message with the given `idempotency_key` in the database.
2. If found, find the paired assistant message via `parent_message_id`:
   - **COMPLETE** — replay the saved response as an SSE stream: `meta` event, a single `token` event with the full saved content, then `citations` event reconstructed from the `Message.citations` DB field, then `done` event with saved usage stats.
   - **STREAMING** — return HTTP 409 Conflict (the original request is still being processed).
   - **PARTIAL or FAILED** — proceed with a new generation (re-generate).
3. If not found — proceed with normal message processing.

Replay of a COMPLETE message SHALL be allowed even if another stream is active in the session, because replay is read-only (no LLM call, no state mutation). The idempotency check SHALL run before the session concurrency guard.

#### Scenario: Idempotency replay of COMPLETE message

- **WHEN** `POST /api/chat/messages` is called with an `idempotency_key` that matches a user message whose paired assistant message has status COMPLETE
- **THEN** the response SHALL be 200 with an SSE stream
- **AND** the stream SHALL emit `meta`, then a single `token` event with the full saved content, then `citations` event reconstructed from `Message.citations`, then `done`
- **AND** no new LLM call SHALL be made

#### Scenario: Idempotency replay includes empty citations

- **WHEN** a COMPLETE assistant message has an empty `citations` field (empty array or null)
- **AND** a replay is triggered via `idempotency_key`
- **THEN** the replayed stream SHALL emit a `citations` event with payload `{citations: []}`

#### Scenario: Idempotency conflict for STREAMING message

- **WHEN** `POST /api/chat/messages` is called with an `idempotency_key` that matches a user message whose paired assistant message has status STREAMING
- **THEN** the response SHALL be 409 Conflict

#### Scenario: Re-generation for PARTIAL message

- **WHEN** `POST /api/chat/messages` is called with an `idempotency_key` that matches a user message whose paired assistant message has status PARTIAL
- **THEN** the system SHALL proceed with a new generation (normal flow)

#### Scenario: Re-generation for FAILED message

- **WHEN** `POST /api/chat/messages` is called with an `idempotency_key` that matches a user message whose paired assistant message has status FAILED
- **THEN** the system SHALL proceed with a new generation (normal flow)

#### Scenario: New idempotency key proceeds normally

- **WHEN** `POST /api/chat/messages` is called with an `idempotency_key` that does not match any existing user message
- **THEN** the system SHALL proceed with normal message processing

#### Scenario: Replay allowed during active stream in session (D14)

- **WHEN** a session has an active STREAMING assistant message
- **AND** a request arrives with an `idempotency_key` whose paired assistant message is COMPLETE
- **THEN** the replay SHALL be returned successfully (200 with SSE stream)
- **AND** the concurrency guard SHALL NOT block the replay

#### Scenario: No idempotency key proceeds normally

- **WHEN** `POST /api/chat/messages` is called without an `idempotency_key` field
- **THEN** the system SHALL proceed with normal message processing without any idempotency check

---

## ADDED Requirements

### Requirement: ChatStreamCitations event type

The system SHALL define a `ChatStreamCitations` dataclass in `backend/app/services/chat.py` alongside the existing stream event types (`ChatStreamMeta`, `ChatStreamToken`, `ChatStreamDone`, `ChatStreamError`). The dataclass SHALL have a `citations` field containing a list of citation objects. `ChatStreamCitations` SHALL be included in the `ChatStreamEvent` union type.

The API layer (`backend/app/api/chat.py`) SHALL serialize `ChatStreamCitations` as an SSE event with `event: citations` via the existing `format_event()` function. The serialization SHALL produce `event: citations\ndata: {"citations": [...]}\n\n`.

#### Scenario: ChatStreamCitations dataclass defined

- **WHEN** the `ChatStreamEvent` union type is inspected
- **THEN** it SHALL include `ChatStreamCitations` alongside `ChatStreamMeta`, `ChatStreamToken`, `ChatStreamDone`, and `ChatStreamError`

#### Scenario: ChatStreamCitations serialized as SSE event

- **WHEN** a `ChatStreamCitations` event is yielded from the chat service stream
- **THEN** the `format_event()` function SHALL serialize it as `event: citations\ndata: {"citations": [...]}\n\n`

#### Scenario: ChatStreamCitations with populated citations

- **WHEN** the citation service produces 3 citation objects
- **THEN** the `ChatStreamCitations` event SHALL contain all 3 citation objects in its `citations` list

#### Scenario: ChatStreamCitations with empty citations

- **WHEN** the citation service produces zero citation objects
- **THEN** the `ChatStreamCitations` event SHALL contain an empty list (`citations: []`)
