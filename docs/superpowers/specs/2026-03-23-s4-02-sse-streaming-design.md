# S4-02: SSE Streaming — Design Spec

## Story

> Switch `POST /api/chat/messages` to SSE streaming. Message state machine: received → streaming → complete/partial/failed. Idempotency key. Persist user + assistant messages in PG.

## Approach

**Async generator pipeline.** `LLMService.stream()` yields raw tokens → `ChatService.stream_answer()` yields domain events → API layer formats as SSE via `StreamingResponse`.

**Why this approach:**
- Follows existing service → API architecture
- Each layer has single responsibility (SOLID SRP)
- Async generators are idiomatic Python for stream processing
- Each layer is independently testable
- Minimal changes to existing code

**Rejected alternatives:**
- **Callback-based:** Less Pythonic, harder to test, no advantages over generators.
- **Background worker + Redis pub/sub:** Over-engineered for current scale (YAGNI). Adds latency per token. Idempotency key + retry handles the API-restart edge case.

## Design Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | Backward compatibility | SSE-only (no JSON fallback) | Plan says "switch". JSON fallback = YAGNI. Frontend (S5-01) will use SSE. Tests work via `httpx-sse`. |
| D2 | Idempotency key generation | Client-generated, optional field | Standard retry pattern. Optional keeps simple clients simple. |
| D3 | Idempotency storage | DB only (existing unique index) | `Message.idempotency_key` already has a unique partial index. Redis adds complexity without benefit at this scale. |
| D13 | User↔Assistant message pairing | Explicit `parent_message_id` FK on Message | Implicit pairing via timestamps/ordering is fragile. Explicit FK makes idempotency lookup robust and future-proof. Requires one small migration (nullable UUID column). |
| D14 | Replay during active stream | Allowed (replay is read-only) | Replaying a COMPLETE message doesn't start a new LLM call or mutate state. The concurrency guard exists to prevent concurrent LLM generation, not to prevent reading saved responses. Idempotency check runs before concurrency guard intentionally. |
| D4 | COMPLETE replay format | Single `token` event with full content + `done` | Client handles it identically to streaming. Simple and honest. |
| D5 | SSE reconnection / Last-Event-ID | Not implemented | LLM streaming + Last-Event-ID adds significant complexity. Idempotency key covers the retry case. |
| D6 | Heartbeat | SSE comment every 15s | Standard practice to prevent proxy/load-balancer timeout. |
| D7 | Initial metadata event | Separate `meta` event before tokens | Clean separation. Client gets `message_id` immediately. Extensible. |
| D8 | Concurrent streams per session | Rejected with 409 Conflict | UI sends one message at a time. Prevents undefined behavior. |
| D9 | Partial content accumulation | In-memory buffer, single DB write | Less DB pressure than periodic saves. Content saved on complete/partial/failed. |
| D10 | Token counting | LiteLLM `stream_options.include_usage` | Supported by major providers. Fields are nullable for providers that don't support it. |
| D11 | Inter-token timeout | Configurable, 30s default | Prevents hung connections from unresponsive LLM providers. |
| D12 | Keep existing `answer()` / `complete()` | Yes, do not remove | Used by tests, useful for non-streaming internal calls (e.g., query rewriting in S4-04). |

## SSE Protocol

### Event Types

| Event | Payload | When |
|-------|---------|------|
| `meta` | `{message_id, session_id, snapshot_id}` | First event, after creating assistant message (STREAMING status) |
| `token` | `{content: "..."}` | Each chunk from LLM |
| `done` | `{token_count_prompt, token_count_completion, model_name, retrieved_chunks_count}` | Generation complete (COMPLETE status) |
| `citations` | `{citations: [...]}` | Reserved for S4-03 (Citation Builder). Not emitted in S4-02. |
| `error` | `{detail: "..."}` | LLM error or internal error (FAILED status) |

### Wire Format

```
event: meta
data: {"message_id":"550e8400-e29b-41d4-a716-446655440000","session_id":"...","snapshot_id":"..."}

event: token
data: {"content":"Hello"}

event: token
data: {"content":" world"}

event: done
data: {"token_count_prompt":150,"token_count_completion":42,"model_name":"openai/gpt-4o"}
```

**Heartbeat:** `: heartbeat\n\n` (SSE comment, not a named event).

**Content-Type:** `text/event-stream; charset=utf-8`.

**HTTP status:** Always `200` once streaming begins. Pre-stream errors use standard HTTP codes (404, 409, 422).

## Request Flow

### Normal Flow

```
1. Validate request (session_id, text, optional idempotency_key)
2. If idempotency_key provided:
   a. Lookup user message with this key in DB
   b. If found → find paired assistant message via parent_message_id:
      - COMPLETE → replay (meta + single token with full content + done)
      - STREAMING → 409 Conflict (still processing)
      - PARTIAL/FAILED → proceed to step 3 (re-generate)
   c. If not found → continue to step 3
   NOTE: Replay of COMPLETE is allowed even if another stream is active in the session
         (replay is read-only — no LLM call, no state mutation). See D14.
3. Session concurrency guard: any STREAMING message in session → 409
4. Load session, lazy-bind snapshot if needed
5. Save user message (status=RECEIVED, idempotency_key)
6. Retrieve chunks via hybrid search (scoped by active snapshot_id)
   On retrieval failure: persist FAILED assistant message (parent_message_id=user_message.id), then raise → HTTP 500
7. Build prompt (persona + retrieval context + query)
8. Create assistant message (status=STREAMING, parent_message_id=user_message.id)
   NOTE: Steps 5-8 all happen before the first yield (pre-stream boundary).
         Exceptions in steps 1-8 propagate as standard HTTP errors.
         After step 8, the stream is committed — errors become SSE error events.
9. Return StreamingResponse (200, text/event-stream)
10. Yield meta event (message_id, session_id, snapshot_id)
11. Stream LLM tokens → yield token events, accumulate content in buffer
12. On LLM complete → update assistant message to COMPLETE (content, source_ids, usage, audit hashes)
13. Yield done event
```

### Idempotency Replay Flow

```
1. Client sends request with previously used idempotency_key
2. User message found in DB → paired assistant message is COMPLETE
3. Return StreamingResponse (200)
4. Yield meta event (existing message_id)
5. Yield single token event with full saved content
6. Yield done event (saved usage stats)
```

### Disconnect Flow

```
1. Client disconnects mid-stream
2. Detected via asyncio.CancelledError or request.is_disconnected()
3. Update assistant message: status=PARTIAL, content=accumulated buffer
4. Close stream
```

### Error Flow

```
1. LLM error or internal error mid-stream
2. Yield error event with detail
3. Update assistant message: status=FAILED, content=accumulated buffer (if any)
4. Close stream
```

### No-Context Refusal

When retrieved chunks are below the `min_retrieved_chunks` threshold, the refusal response is streamed as normal token events with COMPLETE status. It is a valid response, not an error.

## Message State Machine

```
User message:
  → RECEIVED (saved before any processing begins)

Assistant message:
  → STREAMING (created before first token is sent)
      ├→ COMPLETE  (LLM finished, full content + metadata saved)
      ├→ PARTIAL   (client disconnected, accumulated content saved)
      └→ FAILED    (LLM error or internal error, partial content saved if any)
```

All statuses are already defined in `MessageStatus` enum. The only migration is for `parent_message_id` (see Database Changes).

## Service Layer Changes

### LLMService

New method `stream()` alongside existing `complete()`. Existing method is preserved.

**Stream event types:**

```python
LLMStreamEvent = LLMToken | LLMStreamEnd

@dataclass
class LLMToken:
    content: str

@dataclass
class LLMStreamEnd:
    model_name: str | None
    token_count_prompt: int | None
    token_count_completion: int | None
```

**Contract:**
- `stream(messages, *, temperature=None) -> AsyncIterator[LLMStreamEvent]`
- Uses `litellm.acompletion(..., stream=True, stream_options={"include_usage": True})`
- Yields `LLMToken` for each non-empty content chunk
- Yields `LLMStreamEnd` as the final event (with usage stats when available from provider)
- Raises `LLMError` on provider failure

**Why typed union instead of mutable accumulator:** No hidden state, consumer checks type per event, easy to test with a list of events.

### ChatService

New method `stream_answer()` alongside existing `answer()`. Existing method is preserved.

**Domain events:**

```python
ChatStreamEvent = ChatStreamMeta | ChatStreamToken | ChatStreamDone | ChatStreamError

@dataclass
class ChatStreamMeta:
    message_id: UUID
    session_id: UUID
    snapshot_id: UUID | None

@dataclass
class ChatStreamToken:
    content: str

@dataclass
class ChatStreamDone:
    token_count_prompt: int | None
    token_count_completion: int | None
    model_name: str | None
    retrieved_chunks_count: int | None

@dataclass
class ChatStreamError:
    detail: str
```

**Responsibilities:**
- Session loading, snapshot binding — delegates to existing snapshot service
- Message persistence (create, update status) — owns the lifecycle
- Content accumulation — in-memory buffer, written to DB on terminal state
- Prompt assembly — delegates to `prompt.py` (no changes)
- LLM streaming — delegates to `LLMService.stream()`
- Source ID deduplication — from retrieved chunks (same as current `answer()`)
- Audit hashes — `config_commit_hash` + `config_content_hash` from PersonaContext

### API Layer

`POST /api/chat/messages` returns `StreamingResponse(media_type="text/event-stream")`.

**SSE formatting utility:** `format_sse_event(event_type: str, data: dict) -> str` — produces `event: {type}\ndata: {json}\n\n`.

**Pre-stream / mid-stream boundary:** All validation and retrieval happen before the first `yield` in `stream_answer()`. Exceptions before the first yield propagate as standard Python exceptions and are caught by the API layer as HTTP errors. After the first `yield` (always `ChatStreamMeta`), the stream is committed — errors become SSE `error` events.

**Generator function:**
- Pre-stream checks (idempotency, concurrency, session, snapshot, retrieval) happen BEFORE returning `StreamingResponse`
- If pre-stream check indicates replay → return replay generator
- Otherwise → return streaming generator wrapping `chat_service.stream_answer()`
- Heartbeat: `asyncio.wait_for` with heartbeat interval, emit SSE comment on timeout
- Inter-token timeout: deadline resets on each event, exceeded → `error` event + FAILED
- Disconnect detection: `asyncio.CancelledError` → save PARTIAL

## Pydantic Schema Changes

**`SendMessageRequest`** — add optional field:
- `idempotency_key: str | None = None`

**No other schema changes.** `MessageResponse` is retained for the session history endpoint (`GET /api/chat/sessions/:id`).

## Database Changes

**One small migration required.** Add `parent_message_id` (nullable UUID) to the `messages` table:

- `parent_message_id` — nullable UUID FK to `messages.id`. Set on assistant messages to link back to the user message they respond to. Used for reliable idempotency lookup (D13).

**Existing fields already present (no changes):**
- `Message.idempotency_key` — unique partial index (when non-null)
- `Message.status` — STREAMING, PARTIAL, FAILED enums
- `Message.source_ids`, `citations`, `content_type_spans` — for future stories
- `Message.token_count_prompt/completion`, `model_name` — for done event metadata
- `Message.config_commit_hash`, `config_content_hash` — for audit

## Configuration

New settings in `Settings` (`app/core/config.py`):

| Setting | Type | Default | Purpose |
|---------|------|---------|---------|
| `sse_heartbeat_interval_seconds` | `int` | `15` | Interval between SSE heartbeat comments |
| `sse_inter_token_timeout_seconds` | `int` | `30` | Max wait time between LLM tokens before FAILED |

## Error Handling Summary

| Scenario | Detection | Response | Message Status |
|----------|-----------|----------|----------------|
| Session not found | Before stream | HTTP 404 | — |
| No active snapshot | Before stream | HTTP 422 | — |
| Concurrent stream in session | Before stream | HTTP 409 | — |
| Idempotency: STREAMING in flight | Before stream | HTTP 409 | — |
| Idempotency: COMPLETE | Before stream | 200 replay stream (allowed even during active stream — read-only, D14) | — (existing) |
| Retrieval error | Before stream | Persist FAILED assistant message, then raise → HTTP 500 (same semantics as current `answer()`) | FAILED |
| Insufficient retrieval context | During stream | Normal refusal streamed as tokens | COMPLETE |
| LLM provider error | During stream | `error` event + close | FAILED |
| Internal error | During stream | `error` event + close | FAILED |
| Inter-token timeout | During stream | `error` event + close | FAILED |
| Client disconnect | During stream | Save accumulated content | PARTIAL |

## Testing Strategy

### Unit Tests (CI, deterministic)

- **LLMService.stream():** Mock `litellm.acompletion(stream=True)`, verify yields `LLMToken` events followed by `LLMStreamEnd`.
- **ChatService.stream_answer():** Mock LLMService and DB, verify domain event sequence: `meta → token* → done`.
- **Idempotency logic:** COMPLETE replay returns saved content. PARTIAL/FAILED triggers re-generation. STREAMING returns 409.
- **Session concurrency guard:** Second request to same session while streaming → 409.
- **SSE format function:** Correct wire format for all event types.
- **Heartbeat timing:** Verify heartbeat emission after configured interval.
- **No-context refusal:** Streamed as tokens with COMPLETE status.

### Integration Tests (CI, test DB)

- **Full SSE stream:** `httpx.AsyncClient` + SSE parser, verify event sequence and message persistence.
- **Message persistence:** User message saved as RECEIVED, assistant message as COMPLETE with content, source_ids, usage stats, audit hashes.
- **Disconnect simulation:** Close connection mid-stream → message saved as PARTIAL with accumulated content. **Note:** In-process ASGI testing (httpx + ASGITransport) may not perfectly reproduce the `asyncio.CancelledError` path of a real network disconnect. This test verifies the save logic but should be complemented with manual testing against a real server for full confidence.
- **Idempotency replay:** Send same idempotency_key twice → second returns same content via SSE.
- **Concurrent stream rejection:** Two simultaneous requests to same session → second gets 409.

### Out of Scope (future stories)

- `citations` SSE event (S4-03)
- Query rewriting before retrieval (S4-04)
- Content type spans in response (S4-06)
- Conversation memory in prompt (S4-07)

## Dependencies

- **Existing code modified:** `app/api/chat.py`, `app/services/llm.py`, `app/services/chat.py`, `app/api/chat_schemas.py`, `app/core/config.py`, `app/db/models/dialogue.py`
- **New code:** Stream event dataclasses (in `chat.py` or separate module), SSE formatting utility
- **New dev dependency:** `httpx-sse` for SSE parsing in tests
- **One Alembic migration:** Add `parent_message_id` (nullable UUID FK) to `messages` table (D13)
