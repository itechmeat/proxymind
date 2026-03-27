## Purpose

SSE streaming protocol, event types, heartbeat, inter-token timeout, disconnect handling, idempotency replay, session concurrency guard, and LLM streaming abstraction. Introduced by S4-02. Extended by S6-01 with a `products` SSE event type for product recommendations.

## ADDED Requirements

### Requirement: ChatStreamProducts event type

The system SHALL define a `ChatStreamProducts` dataclass in `backend/app/services/chat.py` alongside the existing stream event types (`ChatStreamMeta`, `ChatStreamToken`, `ChatStreamDone`, `ChatStreamError`, `ChatStreamCitations`). The dataclass SHALL have a `products` field containing a list of product recommendation dicts (serialized via `ProductRecommendation.to_dict()`). `ChatStreamProducts` SHALL be included in the `ChatStreamEvent` union type.

The API layer (`backend/app/api/chat.py`) SHALL serialize `ChatStreamProducts` as an SSE event with `event: products` via the existing `format_event()` function. The serialization SHALL produce `event: products\ndata: {"products": [...]}\n\n`.

#### Scenario: ChatStreamProducts dataclass defined

- **WHEN** the `ChatStreamEvent` union type is inspected
- **THEN** it SHALL include `ChatStreamProducts` alongside `ChatStreamMeta`, `ChatStreamToken`, `ChatStreamCitations`, `ChatStreamDone`, and `ChatStreamError`

#### Scenario: ChatStreamProducts serialized as SSE event

- **WHEN** a `ChatStreamProducts` event is yielded from the chat service stream
- **THEN** the `format_event()` function SHALL serialize it as `event: products\ndata: {"products": [...]}\n\n`

#### Scenario: ChatStreamProducts with one recommendation

- **WHEN** the product recommendation service produces 1 product recommendation
- **THEN** the `ChatStreamProducts` event SHALL contain 1 product dict in its `products` list
- **AND** the dict SHALL include `index`, `catalog_item_id`, `name`, `sku`, `item_type`, `url`, `image_url`, `text_recommendation`

#### Scenario: ChatStreamProducts not emitted when no recommendations

- **WHEN** the LLM output contains no `[product:N]` markers or catalog items list is empty
- **THEN** the `products` SSE event SHALL NOT be emitted

---

### Requirement: Products event position in SSE sequence

The `products` event SHALL be emitted after the `citations` event and before the `done` event. This ordering ensures the frontend receives all enriched data before the completion signal. The `products` event SHALL only be emitted when at least one product recommendation was extracted.

#### Scenario: Normal SSE stream with products

- **WHEN** a message is sent, the LLM generates a response with both `[source:N]` and `[product:N]` markers
- **THEN** the SSE stream SHALL emit events in the order: `meta`, one or more `token` events, `citations`, `products`, `done`

#### Scenario: SSE stream without products

- **WHEN** a message is sent and the LLM generates a response with `[source:N]` but no `[product:N]` markers
- **THEN** the SSE stream SHALL emit events in the order: `meta`, one or more `token` events, `citations`, `done`
- **AND** no `products` event SHALL be emitted

#### Scenario: SSE stream with products but no citations

- **WHEN** a message is sent and the LLM generates a response with `[product:1]` but no `[source:N]` markers
- **THEN** the SSE stream SHALL emit events in the order: `meta`, one or more `token` events, `citations` (with empty array), `products`, `done`

---

### Requirement: Products event not emitted for partial or failed messages

For assistant messages that reach `partial` or `failed` status, the `products` event SHALL NOT be emitted. This is consistent with the behavior of the `citations` event, which is also not emitted for incomplete messages.

#### Scenario: Products event not emitted for PARTIAL message

- **WHEN** the client disconnects mid-stream and the assistant message status becomes PARTIAL
- **THEN** the `products` event SHALL NOT be emitted

#### Scenario: Products event not emitted for FAILED message

- **WHEN** an LLM error or inter-token timeout occurs and the assistant message status becomes FAILED
- **THEN** the `products` event SHALL NOT be emitted

---

### Requirement: Products in persisted message format

The `products` field SHALL be included in the persisted message response schemas (`MessageResponse`, `MessageInHistory`). The field SHALL be an optional list of product recommendation dicts, or `null` when no products were recommended. This enables the frontend to render product cards from message history.

#### Scenario: Products field in GET sessions/:id response

- **WHEN** `GET /api/chat/sessions/:id` returns message history and an assistant message has product recommendations
- **THEN** the `products` field SHALL contain an array of product recommendation dicts

#### Scenario: Products field null when no recommendations

- **WHEN** `GET /api/chat/sessions/:id` returns message history and an assistant message has no product recommendations
- **THEN** the `products` field SHALL be `null`

---

### Requirement: Idempotency replay includes products

When replaying a COMPLETE message via idempotency key, the replay stream SHALL include the `products` event reconstructed from the `Message.products` JSONB field, in the correct position after `citations` and before `done`. When `Message.products` is `null` or empty, the `products` event SHALL NOT be included in the replay.

#### Scenario: Replay includes products event

- **WHEN** a COMPLETE assistant message with persisted `products` data is replayed via idempotency key
- **THEN** the replayed stream SHALL emit `meta`, `token` (full content), `citations`, `products`, `done`

#### Scenario: Replay without products

- **WHEN** a COMPLETE assistant message with `products=null` is replayed via idempotency key
- **THEN** the replayed stream SHALL emit `meta`, `token` (full content), `citations`, `done`
- **AND** no `products` event SHALL be emitted

---

## Existing Requirements (unchanged)

### Requirement: SSE protocol and event types

The system SHALL stream chat responses using the Server-Sent Events (SSE) protocol with `Content-Type: text/event-stream; charset=utf-8`. The system SHALL support the following event types:

- `meta` — first event, payload `{message_id, session_id, snapshot_id}`, emitted after creating the assistant message with STREAMING status.
- `token` — payload `{content: "..."}`, emitted for each non-empty chunk from the LLM.
- `citations` — payload `{citations: [...]}`, emitted after all `token` events and before `products` (if present) or `done`. The `citations` array SHALL contain citation objects produced by the citation service. When no citations are extracted, the event SHALL still be emitted with an empty array (`{citations: []}`). For assistant messages that reach `partial` or `failed` status, the `citations` event SHALL NOT be emitted.
- `products` — payload `{products: [...]}`, emitted after `citations` and before `done`. Only emitted when product recommendations were extracted. For partial or failed messages, this event SHALL NOT be emitted.
- `done` — payload `{token_count_prompt, token_count_completion, model_name, retrieved_chunks_count}`, emitted when generation is complete (COMPLETE status). Token count fields SHALL be nullable (for providers that do not report usage). `retrieved_chunks_count` SHALL be an integer representing the number of chunks passed to the LLM (0 for refusal responses).
- `error` — payload `{detail: "..."}`, emitted on LLM error or internal error (FAILED status).

Each event SHALL be formatted as `event: {type}\ndata: {json}\n\n`. The HTTP status SHALL always be `200` once streaming begins. Pre-stream errors (session not found, validation failure, concurrency conflict) SHALL use standard HTTP status codes (404, 409, 422) and SHALL NOT start an SSE stream.

#### Scenario: Normal SSE stream event sequence with products

- **WHEN** a message is sent and the LLM generates a response with both citations and product recommendations
- **THEN** the SSE stream SHALL emit events in the order: `meta` (exactly once), then one or more `token` events, then `citations` (exactly once), then `products` (exactly once), then `done` (exactly once)
- **AND** each event SHALL conform to the wire format `event: {type}\ndata: {json}\n\n`

#### Scenario: Normal SSE stream event sequence without products

- **WHEN** a message is sent and the LLM generates a response without product recommendations
- **THEN** the SSE stream SHALL emit events in the order: `meta` (exactly once), then one or more `token` events, then `citations` (exactly once), then `done` (exactly once)

#### Scenario: Citations event with no citations

- **WHEN** the LLM generates a response and the citation service extracts zero citations
- **THEN** the SSE stream SHALL emit a `citations` event with payload `{citations: []}`
- **AND** the event SHALL appear after all `token` events and before `products` or `done`

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
   - **COMPLETE** — replay the saved response as an SSE stream: `meta` event, a single `token` event with the full saved content, then `citations` event reconstructed from the `Message.citations` DB field, then `products` event reconstructed from `Message.products` DB field (if non-null), then `done` event with saved usage stats.
   - **STREAMING** — return HTTP 409 Conflict (the original request is still being processed).
   - **PARTIAL or FAILED** — proceed with a new generation (re-generate).
3. If not found — proceed with normal message processing.

Replay of a COMPLETE message SHALL be allowed even if another stream is active in the session, because replay is read-only (no LLM call, no state mutation). The idempotency check SHALL run before the session concurrency guard.

#### Scenario: Idempotency replay of COMPLETE message

- **WHEN** `POST /api/chat/messages` is called with an `idempotency_key` that matches a user message whose paired assistant message has status COMPLETE
- **THEN** the response SHALL be 200 with an SSE stream
- **AND** the stream SHALL emit `meta`, then a single `token` event with the full saved content, then `citations` event reconstructed from `Message.citations`, then `products` event if `Message.products` is non-null, then `done`
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

---

### Requirement: ChatStreamCitations event type

The system SHALL define a `ChatStreamCitations` dataclass in `backend/app/services/chat.py` alongside the existing stream event types (`ChatStreamMeta`, `ChatStreamToken`, `ChatStreamDone`, `ChatStreamError`). The dataclass SHALL have a `citations` field containing a list of citation objects. `ChatStreamCitations` SHALL be included in the `ChatStreamEvent` union type.

The API layer (`backend/app/api/chat.py`) SHALL serialize `ChatStreamCitations` as an SSE event with `event: citations` via the existing `format_event()` function. The serialization SHALL produce `event: citations\ndata: {"citations": [...]}\n\n`.

#### Scenario: ChatStreamCitations dataclass defined

- **WHEN** the `ChatStreamEvent` union type is inspected
- **THEN** it SHALL include `ChatStreamCitations` alongside `ChatStreamMeta`, `ChatStreamToken`, `ChatStreamProducts`, `ChatStreamDone`, and `ChatStreamError`

#### Scenario: ChatStreamCitations serialized as SSE event

- **WHEN** a `ChatStreamCitations` event is yielded from the chat service stream
- **THEN** the `format_event()` function SHALL serialize it as `event: citations\ndata: {"citations": [...]}\n\n`

#### Scenario: ChatStreamCitations with populated citations

- **WHEN** the citation service produces 3 citation objects
- **THEN** the `ChatStreamCitations` event SHALL contain all 3 citation objects in its `citations` list

#### Scenario: ChatStreamCitations with empty citations

- **WHEN** the citation service produces zero citation objects
- **THEN** the `ChatStreamCitations` event SHALL contain an empty list (`citations: []`)
