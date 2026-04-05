## Purpose

SSE transport adapter bridging the backend SSE format to the AI SDK (or custom hook), SSE parser, message format adapter, idempotency, dev proxy, and error handling. Introduced by S5-01.

## ADDED Requirements

### Requirement: SSE parser for ReadableStream

The SSE parser (`sse-parser.ts`) SHALL consume a `ReadableStream<Uint8Array>` from a fetch response and yield typed SSE events. The parser SHALL handle the SSE wire format: `event: {type}\ndata: {json}\n\n`. The parser SHALL support the following event types: `meta`, `token`, `citations`, `done`, `error`. The parser SHALL handle partial chunks that arrive across stream boundaries (i.e., an event split across two `ReadableStream` chunks). The parser SHALL skip heartbeat comments (lines starting with `:`). The parser SHALL handle malformed `data:` lines gracefully (skip without crashing).

#### Scenario: Parse complete SSE event

- **WHEN** the parser receives a chunk containing `event: token\ndata: {"content":"hello"}\n\n`
- **THEN** it SHALL yield a `TokenEvent` with `content: "hello"`

#### Scenario: Parse event split across chunks

- **WHEN** an SSE event is split across two ReadableStream chunks (e.g., first chunk ends mid-`data:` line)
- **THEN** the parser SHALL buffer the partial data and yield the complete event after the second chunk arrives

#### Scenario: Skip heartbeat comments

- **WHEN** the parser encounters `: heartbeat\n\n` in the stream
- **THEN** it SHALL skip the comment without yielding any event

#### Scenario: Handle malformed data gracefully

- **WHEN** the parser encounters a `data:` line containing invalid JSON
- **THEN** the parser SHALL skip that event without throwing an exception
- **AND** parsing SHALL continue for subsequent events

#### Scenario: Parse all five event types

- **WHEN** the parser receives events of types `meta`, `token`, `citations`, `done`, and `error`
- **THEN** it SHALL yield correctly typed events: `MetaEvent`, `TokenEvent`, `CitationsEvent`, `DoneEvent`, and `ErrorEvent` respectively

---

### Requirement: SSE event mapping to UI state

The transport SHALL map backend SSE events to UI state transitions as follows:

- `meta` event: capture `message_id`, `session_id`, and `snapshot_id` as message metadata.
- `token` event: emit as a text delta for incremental message rendering.
- `citations` event: invoke a sideband callback (`onCitations`) to store citations for future display (S5-02). Citations SHALL NOT be part of the text stream.
- `done` event: emit a finish signal. Capture `token_count_prompt`, `token_count_completion`, `model_name`, and `retrieved_chunks_count` as message metadata.
- `error` event: emit an error signal with the `detail` string.

#### Scenario: Meta event captures metadata

- **WHEN** the transport receives an SSE `meta` event with `message_id`, `session_id`, `snapshot_id`
- **THEN** the transport SHALL store these values as metadata on the current assistant message

#### Scenario: Token event produces text delta

- **WHEN** the transport receives an SSE `token` event with `content: "Hello"`
- **THEN** the transport SHALL emit a text delta that appends "Hello" to the assistant message

#### Scenario: Citations event invokes sideband callback

- **WHEN** the transport receives an SSE `citations` event
- **THEN** the transport SHALL invoke the `onCitations` callback with the parsed citation objects
- **AND** no text SHALL be appended to the message content

#### Scenario: Done event finishes stream

- **WHEN** the transport receives an SSE `done` event
- **THEN** the transport SHALL signal stream completion
- **AND** metadata fields (token counts, model name, chunk count) SHALL be stored on the message

#### Scenario: Error event surfaces error

- **WHEN** the transport receives an SSE `error` event with `detail: "LLM response timed out"`
- **THEN** the transport SHALL signal an error state with the detail message

---

### Requirement: Transport sends messages to backend

The transport SHALL send messages by POSTing to `/api/chat/messages` with the JSON body `{ session_id, text, idempotency_key }`. The `session_id` SHALL be injected by the transport (not provided by the component). The `Content-Type` SHALL be `application/json`. The transport SHALL parse the response as an SSE stream and bridge the events to the AI SDK `useChat` format (Approach A) or a custom chat hook (Approach B).

#### Scenario: POST request format

- **WHEN** the user sends a message with text "What is ProxyMind?"
- **THEN** the transport SHALL POST to `/api/chat/messages` with body `{ "session_id": "<uuid>", "text": "What is ProxyMind?", "idempotency_key": "<uuid>" }`
- **AND** the `Content-Type` header SHALL be `application/json`

#### Scenario: Response parsed as SSE stream

- **WHEN** the backend returns a `200` response with `Content-Type: text/event-stream`
- **THEN** the transport SHALL consume `response.body` as a `ReadableStream` and parse it via the SSE parser

---

### Requirement: Idempotency key generation

Each message send SHALL generate a new idempotency key via `crypto.randomUUID()`. On retry of a failed message, a new idempotency key SHALL be generated (new attempt = new key). The idempotency key SHALL be included in the request body as the `idempotency_key` field.

#### Scenario: Unique key per send

- **WHEN** the user sends two messages sequentially
- **THEN** each request SHALL contain a different `idempotency_key` value

#### Scenario: Retry generates new key

- **WHEN** the user retries a failed message
- **THEN** the retry request SHALL contain a new `idempotency_key` different from the original failed request

---

### Requirement: Message adapter converts backend history to UI format

The message adapter (`message-adapter.ts`) SHALL provide a `toUIMessages` function that converts an array of backend `MessageInHistory` objects to the UI message format. The mapping SHALL handle:

- `id` → message ID (string).
- `role` → "user" or "assistant".
- `content` → message text (mapped to the appropriate format for the chosen approach: `parts` array for AI SDK UIMessage, or flat `content` string for custom hook).
- `status`:
  - `"complete"` or `"received"` → rendered as a normal completed message.
  - `"partial"` → rendered with an "incomplete" visual indicator.
  - `"failed"` → rendered with error state and retry button.
  - `"streaming"` → rendered with streaming indicator (only during live streaming, not from history).
- `citations` → stored as metadata on the message (available for S5-02, not displayed in S5-01).
- `model_name` → stored as metadata (not displayed in S5-01).
- `created_at` → preserved for relative timestamp display.

#### Scenario: Convert complete assistant message

- **WHEN** `toUIMessages` receives a `MessageInHistory` with `role: "assistant"`, `status: "complete"`, `content: "Hello world"`
- **THEN** the output message SHALL have `role: "assistant"`, display text "Hello world", and a completed status

#### Scenario: Convert received status to complete

- **WHEN** `toUIMessages` receives a `MessageInHistory` with `status: "received"`
- **THEN** the output message status SHALL be mapped to "complete" (received is the user message status equivalent)

#### Scenario: Preserve citations as metadata

- **WHEN** `toUIMessages` receives a message with a non-null `citations` array
- **THEN** the output message SHALL include the citations array in its metadata

#### Scenario: Map failed status

- **WHEN** `toUIMessages` receives a message with `status: "failed"` and `content: "Partial text"`
- **THEN** the output message SHALL have a "failed" status indicator and the available content "Partial text"

#### Scenario: Map partial status

- **WHEN** `toUIMessages` receives a message with `status: "partial"` and `content: "Incomplete response"`
- **THEN** the output message SHALL have a "partial" status indicator and content "Incomplete response"

#### Scenario: Convert user message

- **WHEN** `toUIMessages` receives a `MessageInHistory` with `role: "user"`, `content: "Hi there"`
- **THEN** the output message SHALL have `role: "user"` and display text "Hi there"

---

### Requirement: HTTP error handling

The transport SHALL handle HTTP error responses from the backend as follows:

- **HTTP 401** (unauthorized): Attempt a silent token refresh via `AuthProvider.getAccessToken()`. If refresh succeeds, retry the original request with the new access token. If refresh fails, surface an authentication error to the UI and redirect to `/auth/sign-in`.
- **HTTP 403** (forbidden / session ownership): Surface the error to the UI. Trigger session re-creation via the session hook (the current session belongs to a different user).
- **HTTP 409** (concurrent stream or idempotency conflict): Surface the error to the UI. This SHALL NOT be silently ignored — both cases (active concurrent stream and idempotency conflict while streaming) are real rejections.
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

#### Scenario: HTTP 409 surfaced as error

- **WHEN** the backend responds with HTTP 409 and body `{"detail": "Concurrent stream active"}`
- **THEN** the transport SHALL surface an error to the UI with the detail message
- **AND** the error SHALL NOT be silently swallowed

#### Scenario: HTTP 422 surfaced as knowledge not ready

- **WHEN** the backend responds with HTTP 422
- **THEN** the transport SHALL surface a "knowledge not ready" error to the UI

#### Scenario: Network failure surfaced as connection error

- **WHEN** the `fetch` call throws a `TypeError` (e.g., network unreachable)
- **THEN** the transport SHALL surface a connection error to the UI

---

### Requirement: Authentication header on SSE requests

The transport SHALL include an `Authorization: Bearer <access_token>` header on all fetch requests to `POST /api/chat/messages`. The access token SHALL be provided via the transport options at construction time. Since the transport uses `fetch()` (not `EventSource`), custom headers are natively supported — the token SHALL NOT be passed as a query parameter.

#### Scenario: SSE request includes auth header

- **WHEN** the transport sends a message via `POST /api/chat/messages`
- **THEN** the fetch request SHALL include `Authorization: Bearer <access_token>` header

#### Scenario: Missing access token prevents request

- **WHEN** the transport attempts to send a message without an access token
- **THEN** the transport SHALL surface an authentication error to the UI

---

### Requirement: SSE mid-stream error handling

If an SSE `error` event is received during an active stream, the transport SHALL stop processing further events and signal an error state to the UI. If the SSE connection drops unexpectedly (no events including heartbeats within expected interval), the transport SHALL attempt one automatic reconnect. If reconnect fails, the transport SHALL signal a connection lost error.

#### Scenario: SSE error stops stream

- **WHEN** the parser yields an `ErrorEvent` with `detail: "LLM response timed out"` during streaming
- **THEN** the transport SHALL stop processing the stream
- **AND** the UI SHALL show the error in the message bubble

#### Scenario: Connection drop triggers one retry

- **WHEN** the SSE connection drops mid-stream (ReadableStream closes unexpectedly)
- **THEN** the transport SHALL attempt one automatic reconnect
- **AND** if the reconnect fails, a connection lost error SHALL be surfaced to the UI

---

### Requirement: Vite dev proxy

The Vite development server SHALL be configured with `server.proxy` to forward all requests matching `/api` to the backend at `http://localhost:8000`. This eliminates CORS issues in development by keeping all requests on the same origin. No CORS middleware SHALL be added to the backend for frontend dev purposes. The frontend code SHALL use relative paths (`/api/...`) for all API requests.

#### Scenario: Dev proxy forwards API requests

- **WHEN** the Vite dev server is running and the frontend makes a request to `/api/chat/sessions`
- **THEN** the request SHALL be proxied to `http://localhost:8000/api/chat/sessions`

#### Scenario: Frontend uses relative API paths

- **WHEN** the API client constructs a request URL
- **THEN** the URL SHALL be a relative path starting with `/api/` (not an absolute URL with a hostname)

---

### Requirement: Test coverage for transport layer

All stable transport behavior (SSE parsing, event mapping, message adapter, idempotency, error handling) MUST be covered by unit tests before archive, per Phase 5 requirements. Tests SHALL be deterministic and SHALL mock `fetch` responses — no real backend connections.

#### Scenario: Transport unit tests pass in CI

- **WHEN** `bun run test` is executed
- **THEN** all SSE parser, transport, and message adapter tests SHALL pass
- **AND** no test SHALL make real HTTP requests
