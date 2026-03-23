## Purpose

SSE streaming protocol, event types, heartbeat, inter-token timeout, disconnect handling, idempotency replay, session concurrency guard, and LLM streaming abstraction. Introduced by S4-02.

## ADDED Requirements

### Requirement: SSE protocol and event types

The system SHALL stream chat responses using the Server-Sent Events (SSE) protocol with `Content-Type: text/event-stream; charset=utf-8`. The system SHALL support the following event types:

- `meta` — first event, payload `{message_id, session_id, snapshot_id}`, emitted after creating the assistant message with STREAMING status.
- `token` — payload `{content: "..."}`, emitted for each non-empty chunk from the LLM.
- `done` — payload `{token_count_prompt, token_count_completion, model_name, retrieved_chunks_count}`, emitted when generation is complete (COMPLETE status). Token count fields SHALL be nullable (for providers that do not report usage). `retrieved_chunks_count` SHALL be an integer representing the number of chunks passed to the LLM (0 for refusal responses).
- `citations` — payload `{citations: [...]}`, reserved for S4-03. SHALL NOT be emitted in S4-02.
- `error` — payload `{detail: "..."}`, emitted on LLM error or internal error (FAILED status).

Each event SHALL be formatted as `event: {type}\ndata: {json}\n\n`. The HTTP status SHALL always be `200` once streaming begins. Pre-stream errors (session not found, validation failure, concurrency conflict) SHALL use standard HTTP status codes (404, 409, 422) and SHALL NOT start an SSE stream.

#### Scenario: Normal SSE stream event sequence

- **WHEN** a message is sent and the LLM generates a response
- **THEN** the SSE stream SHALL emit events in the order: `meta` (exactly once), then one or more `token` events, then `done` (exactly once)
- **AND** each event SHALL conform to the wire format `event: {type}\ndata: {json}\n\n`

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

### Requirement: SSE heartbeat mechanism

The system SHALL emit SSE heartbeat comments at a configurable interval (`sse_heartbeat_interval_seconds`, default 15 seconds) to prevent proxy and load-balancer timeouts. The heartbeat SHALL be formatted as `: heartbeat\n\n` (a standard SSE comment, not a named event). The heartbeat timer SHALL reset on each emitted event (heartbeat is only sent during idle periods between events).

#### Scenario: Heartbeat emitted during idle period

- **WHEN** no SSE event has been emitted for `sse_heartbeat_interval_seconds` seconds during an active stream
- **THEN** the system SHALL emit a `: heartbeat\n\n` SSE comment

#### Scenario: Heartbeat does not interfere with events

- **WHEN** LLM tokens are arriving faster than the heartbeat interval
- **THEN** no heartbeat comments SHALL be emitted between the token events

#### Scenario: Custom heartbeat interval

- **WHEN** `sse_heartbeat_interval_seconds` is configured to 10
- **THEN** the heartbeat SHALL be emitted every 10 seconds of idle time instead of the default 15

---

### Requirement: Inter-token timeout

The system SHALL enforce a configurable inter-token timeout (`sse_inter_token_timeout_seconds`, default 30 seconds). If no token is received from the LLM within this interval, the system SHALL emit an `error` SSE event, update the assistant message status to FAILED (saving any accumulated content), and close the stream. The timeout deadline SHALL reset on each received LLM token.

#### Scenario: Timeout triggers FAILED status

- **WHEN** the LLM does not emit a token for longer than `sse_inter_token_timeout_seconds`
- **THEN** the system SHALL emit an `error` event with a detail indicating inter-token timeout
- **AND** the assistant message status SHALL be updated to FAILED
- **AND** any accumulated content SHALL be saved to the assistant message
- **AND** the stream SHALL be closed

#### Scenario: Timeout resets on each token

- **WHEN** the LLM emits tokens with intervals shorter than `sse_inter_token_timeout_seconds`
- **THEN** the inter-token timeout SHALL NOT trigger

#### Scenario: Custom inter-token timeout

- **WHEN** `sse_inter_token_timeout_seconds` is configured to 60
- **THEN** the timeout threshold SHALL be 60 seconds instead of the default 30

---

### Requirement: Idempotency key for message requests

The `POST /api/chat/messages` endpoint SHALL accept an optional `idempotency_key` field (string, client-generated) in the request body. When provided, the system SHALL use it to prevent duplicate processing on retry. The idempotency logic SHALL execute as follows:

1. Look up a user message with the given `idempotency_key` in the database.
2. If found, find the paired assistant message via `parent_message_id`:
   - **COMPLETE** — replay the saved response as an SSE stream: `meta` event, a single `token` event with the full saved content, then `done` event with saved usage stats.
   - **STREAMING** — return HTTP 409 Conflict (the original request is still being processed).
   - **PARTIAL or FAILED** — proceed with a new generation (re-generate).
3. If not found — proceed with normal message processing.

Replay of a COMPLETE message SHALL be allowed even if another stream is active in the session, because replay is read-only (no LLM call, no state mutation). The idempotency check SHALL run before the session concurrency guard.

#### Scenario: Idempotency replay of COMPLETE message

- **WHEN** `POST /api/chat/messages` is called with an `idempotency_key` that matches a user message whose paired assistant message has status COMPLETE
- **THEN** the response SHALL be 200 with an SSE stream
- **AND** the stream SHALL emit `meta`, then a single `token` event with the full saved content, then `done`
- **AND** no new LLM call SHALL be made

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

### Requirement: Session concurrency guard

The system SHALL enforce that only one active LLM stream is allowed per session at a time. Before starting a new stream, the system SHALL check if any assistant message in the session has status STREAMING. If found, the endpoint SHALL return HTTP 409 Conflict. The concurrency guard SHALL run after the idempotency check. Replay of a COMPLETE message via idempotency key SHALL bypass the concurrency guard (D14), because replay is read-only.

#### Scenario: Second stream request rejected with 409

- **WHEN** a session has an assistant message with status STREAMING
- **AND** a new `POST /api/chat/messages` request arrives for the same session without an idempotency key (or with a new idempotency key)
- **THEN** the response SHALL be 409 Conflict

#### Scenario: First stream request accepted

- **WHEN** a session has no assistant messages with status STREAMING
- **AND** `POST /api/chat/messages` is called for that session
- **THEN** the request SHALL proceed with normal stream processing

#### Scenario: Replay bypasses concurrency guard

- **WHEN** a session has an active STREAMING assistant message
- **AND** a request with an idempotency key matching a COMPLETE assistant message arrives
- **THEN** the replay SHALL be allowed (not blocked by the concurrency guard)

---

### Requirement: Disconnect handling

When the client disconnects during an active SSE stream, the system SHALL detect the disconnection (via `asyncio.CancelledError` or `request.is_disconnected()`), save the accumulated content buffer to the assistant message, update the assistant message status to PARTIAL, and close the stream. No error event SHALL be emitted (the client is already gone).

#### Scenario: Client disconnect saves PARTIAL content

- **WHEN** the client disconnects mid-stream after receiving some token events
- **THEN** the assistant message status SHALL be updated to PARTIAL
- **AND** the assistant message content SHALL contain all tokens accumulated up to the point of disconnection

#### Scenario: Client disconnect before any tokens

- **WHEN** the client disconnects after the `meta` event but before any `token` events
- **THEN** the assistant message status SHALL be updated to PARTIAL
- **AND** the assistant message content SHALL be empty or null

---

### Requirement: LLM streaming via LLMService.stream()

The `LLMService` SHALL provide a `stream()` method alongside the existing `complete()` method. The existing `complete()` method SHALL be preserved unchanged.

**Contract:** `stream(messages, *, temperature=None) -> AsyncIterator[LLMStreamEvent]`

The method SHALL use `litellm.acompletion(..., stream=True, stream_options={"include_usage": True})`. It SHALL yield `LLMToken` events for each non-empty content chunk, and a final `LLMStreamEnd` event with usage statistics (when available from the provider). On provider failure, it SHALL raise `LLMError`.

**Stream event types:**
- `LLMToken` — dataclass with `content: str`
- `LLMStreamEnd` — dataclass with `model_name: str | None`, `token_count_prompt: int | None`, `token_count_completion: int | None`
- `LLMStreamEvent = LLMToken | LLMStreamEnd` (typed union)

#### Scenario: Successful LLM stream yields tokens and end event

- **WHEN** `LLMService.stream()` is called with valid messages
- **THEN** it SHALL yield one or more `LLMToken` events with non-empty content
- **AND** the final event SHALL be an `LLMStreamEnd` with model name and token counts (nullable)

#### Scenario: LLM stream error raises LLMError

- **WHEN** the LiteLLM `acompletion(stream=True)` call raises an exception
- **THEN** the service SHALL log the error via structlog
- **AND** SHALL raise `LLMError`

#### Scenario: Existing complete() method preserved

- **WHEN** `LLMService` is used after S4-02 implementation
- **THEN** the `complete()` method SHALL remain available and functional with the same signature and behavior

---

### Requirement: SSE configuration settings

The `Settings` class in `app/core/config.py` SHALL include the following new settings:

- `sse_heartbeat_interval_seconds` — integer, default `15`. Controls the interval between SSE heartbeat comments.
- `sse_inter_token_timeout_seconds` — integer, default `30`. Controls the maximum wait time between LLM tokens before the stream is marked as FAILED.

These settings SHALL be configurable via environment variables (`SSE_HEARTBEAT_INTERVAL_SECONDS`, `SSE_INTER_TOKEN_TIMEOUT_SECONDS`).

#### Scenario: Default SSE configuration values

- **WHEN** no SSE environment variables are set
- **THEN** `sse_heartbeat_interval_seconds` SHALL default to `15`
- **AND** `sse_inter_token_timeout_seconds` SHALL default to `30`

#### Scenario: Custom SSE configuration via environment variables

- **WHEN** `SSE_HEARTBEAT_INTERVAL_SECONDS=10` and `SSE_INTER_TOKEN_TIMEOUT_SECONDS=60` are set
- **THEN** the settings SHALL reflect `sse_heartbeat_interval_seconds=10` and `sse_inter_token_timeout_seconds=60`
