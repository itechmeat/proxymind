## Story

**S4-02: SSE streaming** — Switch `POST /api/chat/messages` to SSE streaming. Message state machine: received → streaming → complete/partial/failed. Idempotency key. Persist user + assistant messages in PG.

**Verification criteria:** send message → SSE token stream → response saved; disconnect → partial; retry → idempotent result.

**Stable behavior requiring test coverage:** All existing chat-dialogue behavior (session creation, message send, lazy snapshot bind, refusal, error handling, session history) MUST remain covered. New streaming, idempotency, concurrency guard, and disconnect behavior MUST be tested.

## Why

Chat responses are currently blocking — the user waits for the full LLM response before seeing anything. SSE streaming enables real-time token delivery, which is essential for the frontend chat UI (S5-01) and dramatically improves perceived responsiveness. This is the next story in Phase 4 (Dialog Expansion) and unblocks all downstream stories that depend on streaming (citations S4-03, query rewriting S4-04, frontend S5-01).

## What Changes

- **BREAKING**: `POST /api/chat/messages` switches from JSON response to `text/event-stream` (SSE). Clients that expect JSON will break.
- `LLMService` gains a `stream()` method alongside existing `complete()`.
- `ChatService` gains a `stream_answer()` method alongside existing `answer()`.
- Message state machine enforced: user messages `RECEIVED`; assistant messages `STREAMING → COMPLETE | PARTIAL | FAILED`.
- Idempotency key (optional, client-generated) prevents duplicate processing on retry.
- Session concurrency guard: one active stream per session (409 on conflict).
- `parent_message_id` column added to `messages` table for explicit user↔assistant pairing.
- Heartbeat (SSE comment every 15s) and inter-token timeout (30s, configurable).
- Disconnect detection saves accumulated content as PARTIAL.

## Capabilities

### New Capabilities

- `sse-streaming`: SSE protocol, event types (meta/token/done/error), heartbeat, inter-token timeout, disconnect handling, idempotency replay.

### Modified Capabilities

- `chat-dialogue`: Message endpoint switches from JSON to SSE. New error codes (409 for concurrency/idempotency conflict). Retrieval error handling now includes pre-stream FAILED message persistence. `parent_message_id` added for explicit message pairing. `SendMessageRequest` gains optional `idempotency_key` field.

## Impact

- **API**: `POST /api/chat/messages` response format changes from `application/json` to `text/event-stream`. Breaking change for all current consumers.
- **Database**: One Alembic migration — `parent_message_id` (nullable UUID FK) on `messages` table.
- **Dependencies**: `httpx-sse` added as dev dependency for SSE test parsing.
- **Code modified**: `app/services/llm.py`, `app/services/chat.py`, `app/api/chat.py`, `app/api/chat_schemas.py`, `app/core/config.py`, `app/api/dependencies.py`, `app/db/models/dialogue.py`.
- **Tests**: Existing chat integration tests require migration from JSON to SSE parsing. Mock fixtures need `stream` method alongside `complete`.
