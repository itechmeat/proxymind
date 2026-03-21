# S2-04: Minimal Chat — Design

## Story

> `POST /api/chat/messages` — accept a question, find relevant chunks in Qdrant (dense vector search against active snapshot), assemble prompt (minimal: system + retrieval context + question), call LLM via LiteLLM, return response (JSON, no streaming).

**Outcome:** a question can be asked and answered based on uploaded knowledge.

**Verification:** upload document → publish → `POST /api/chat/messages {"text": "..."}` → response based on document content.

## Scope

### In scope (S2-04)

- `POST /api/chat/sessions` — explicit session creation
- `POST /api/chat/messages` — send message, retrieve chunks, call LLM, return JSON response
- `GET /api/chat/sessions/{session_id}` — session history with messages
- RetrievalService — dense-only vector search in Qdrant scoped by active snapshot
- LLMService — LiteLLM wrapper (async completion, no streaming)
- Prompt assembly — minimal: system instruction + retrieval context + user question
- User + assistant message persistence in PostgreSQL
- LLM configuration via `.env` (LLM_MODEL, LLM_API_KEY, LLM_API_BASE)

### Out of scope (separate stories)

| Feature | Story |
|---------|-------|
| SSE streaming | S4-02 |
| Persona files (IDENTITY/SOUL/BEHAVIOR) | S4-01 |
| Citation builder | S4-03 |
| Query rewriting | S4-04 |
| Audit logging | S7-03 |
| Rate limiting | S7-02 |
| BM25 sparse vectors | S3-02 |
| Hybrid search + RRF | S3-03 |
| Idempotency key | S4-02 |
| Content type spans | S4-06 |

## Design Decisions

### D1: Explicit session creation

**Decision:** sessions are created explicitly via `POST /api/chat/sessions`. The `POST /api/chat/messages` endpoint requires a `session_id`.

**Why:** matches the API contract already documented in `architecture.md` (three Chat API endpoints). Clean REST semantics — session creation and message sending are separate responsibilities. For S2-04 (no frontend, testing via curl), two requests are not a burden. When frontend arrives (S5-01), it will call `POST /sessions` on chat open.

**Rejected alternatives:**
- *Auto-create session on first message:* convenient but creates a side effect in the messages endpoint — blurs responsibility, harder to test and document.
- *Both explicit and auto-create:* maximum flexibility but two paths to the same result — harder to maintain, violates KISS.

### D2: LLM configuration — three explicit env vars

**Decision:** configure LLM via `LLM_MODEL` (LiteLLM model string), `LLM_API_KEY` (provider API key), and `LLM_API_BASE` (custom endpoint URL).

**Why:** for a self-hosted product, all LLM configuration MUST be visible and explicit in `.env`, without hidden conventions. `LLM_API_BASE` is required for ZAI (the default provider) and any proxy/self-hosted LLM setups. Three variables are the minimum for full control without over-engineering.

**Rejected alternatives:**
- *Single `LLM_MODEL` relying on LiteLLM naming conventions for API keys:* implicit dependency on env var naming (`OPENAI_API_KEY`, `GEMINI_API_KEY`, etc.) — not transparent for self-hosted deployments.
- *Two vars `LLM_PROVIDER` + `LLM_MODEL`:* redundant — LiteLLM already supports the `provider/model` prefix format in a single string.

### D3: HTTP 422 when no active snapshot

**Decision:** `POST /api/chat/messages` returns HTTP 422 when the session has no associated active snapshot.

**Why:** from spec.md: *"the twin responds only from the active published snapshot."* Without a snapshot the twin cannot answer — this is not a server error but an unprocessable state. 422 (Unprocessable Entity) correctly reflects: the request is syntactically valid but the system cannot process it. Easy for clients (and future frontend) to handle.

**Rejected alternatives:**
- *Answer without context (LLM receives only the question):* violates the "responds only from published snapshot" principle; LLM may hallucinate.
- *HTTP 503 (Service Unavailable):* semantically imprecise — 503 implies temporary infrastructure unavailability, not missing data.

### D4: Explicit refusal without LLM call when no relevant chunks

**Decision:** when retrieval returns fewer chunks than `min_retrieved_chunks` (default: 1), the system saves an assistant message with a hardcoded refusal text and returns it without calling the LLM.

**Why:** from rag.md: *"if retrieval returns fewer than `min_retrieved_chunks` — the digital twin responds 'no answer found in the knowledge base'."* This is backend logic, not an LLM decision. Avoids a wasted LLM call for a predictable outcome. Eliminates hallucination risk when there is no grounding context.

**Rejected alternative:** *pass the question to the LLM with an instruction to refuse* — extra cost for a predictable result; LLM may ignore the instruction and hallucinate.

### D5: Dedicated ChatService orchestrator

**Decision:** a thin `ChatService` orchestrates the chat flow by coordinating `RetrievalService`, `LLMService`, `SnapshotService`, and `prompt_builder`. Each responsibility is a separate service/module.

**Why:**
- `architecture.md` defines `retrieval.py` and `llm.py` as separate modules in `services/`.
- The project follows a stateless services + DI pattern — this approach fits naturally.
- `RetrievalService` will be extended in S3-02/S3-03 (BM25, hybrid, RRF) — isolation is critical.
- `LLMService` will be reused in query rewriting (S4-04) — a separate service enables this.
- `ChatService` remains a thin orchestrator (~60-80 lines), easy to extend.

**Rejected alternatives:**
- *Fat endpoint (router orchestrates directly):* business logic leaks into the router — violates SRP, harder to test, grows uncontrollably with streaming/citations/persona.
- *Monolithic ChatService (embedding + search + LLM all in one):* violates SRP, 500+ lines, impossible to reuse retrieval or LLM independently.

### D6: Score threshold — configurable but disabled by default

**Decision:** `RetrievalService` accepts a `min_dense_similarity` parameter. It is exposed in Settings with a default of `None` (disabled). When set to a float, chunks with cosine similarity below the threshold are filtered out before being returned.

**Why:** from rag.md: *"min_dense_similarity — to be determined via evals."* Without empirical data a specific threshold value would be arbitrary. However, the filtering *mechanism* MUST exist from S2-04 — without it, dense top-N over a non-empty collection will almost always return at least one chunk, making the `min_retrieved_chunks` check practically unreachable. The mechanism is in place; the exact calibration value will come from evals (S8-02).

**Known limitation:** with `min_dense_similarity=None`, the system may pass weakly relevant context to the LLM. The system prompt instructs the LLM to refuse when context is insufficient, but this is a soft guard. Operators who want stricter filtering before evals can set `MIN_DENSE_SIMILARITY` to a conservative value (e.g., 0.3–0.5) in `.env`.

### D7: Lazy-bind snapshot_id on first message

**Decision:** `session.snapshot_id` is set to the currently active snapshot when the session is created. If no active snapshot exists at creation time, `snapshot_id` is set to `None`. On the first message, if `snapshot_id` is still `None`, the system attempts a lazy bind: it checks for the current active snapshot and, if one exists, binds it to the session before proceeding. If no active snapshot exists at message time either — 422.

**Why:** fixing the snapshot per session prevents mid-conversation inconsistency — once bound, the session stays on that snapshot even if a new one is published. Lazy bind solves the "session created before first publish" problem: the frontend can create a session and render UI before any knowledge is published. When the owner later publishes and the user sends their first message, the session picks up the newly active snapshot automatically. Without lazy bind, such a session would be permanently broken (always returning 422), contradicting the "frontend can open chat ahead of time" intent.

**Once bound, snapshot_id is immutable for the session.** Lazy bind happens only on the transition from `None` → active snapshot. Subsequent messages always use the already-bound snapshot.

### D8: Prompt structure — context in user message, instructions in system

**Decision:** the system message contains behavioral instructions; the retrieval context and user question are placed in the user message.

**Why:**
- System prompt defines model behavior (instructions) — standard practice.
- Retrieval context is data, not instructions. Standard RAG pattern places context in the user message.
- Simplifies future persona integration (S4-01): persona goes into system, context stays in user.

### D9: Prompt assembly as pure functions, not a service class

**Decision:** `services/prompt.py` contains stateless functions (`build_chat_prompt`), not a class with injected dependencies.

**Why:** prompt assembly is a pure data transformation — input in, output out. No dependencies, no side effects, no state. Easy to test with simple assertions. When persona (S4-01) and promotions (S4-05) add complexity, the function gains parameters. If complexity warrants a class — refactor then (YAGNI now).

## API Contract

### `POST /api/chat/sessions`

Creates a new chat session.

**Request body:**
```json
{
  "channel": "web"
}
```
- `channel` — optional, defaults to `"web"`.

**Response (201 Created):**
```json
{
  "id": "uuid",
  "snapshot_id": "uuid | null",
  "channel": "web",
  "status": "active",
  "message_count": 0,
  "created_at": "2026-03-19T12:00:00Z"
}
```

**Notes:**
- `agent_id` uses `DEFAULT_AGENT_ID` — established project pattern.
- `snapshot_id` is the active snapshot at creation time, or `null` if none exists.
- No authentication required (Chat API is public).

### `POST /api/chat/messages`

Sends a user message and returns the assistant's response.

**Request body:**
```json
{
  "session_id": "uuid",
  "text": "What is ProxyMind?"
}
```

**Response (200 OK):**
```json
{
  "message_id": "uuid",
  "session_id": "uuid",
  "role": "assistant",
  "content": "Based on my knowledge, ProxyMind is...",
  "status": "complete",
  "model_name": "openai/gpt-4o",
  "retrieved_chunks_count": 3,
  "token_count_prompt": 1250,
  "token_count_completion": 180,
  "created_at": "2026-03-19T12:00:01Z"
}
```

**Error responses:**

| Code | Condition |
|------|-----------|
| 404 | Session not found |
| 422 | No active snapshot available after lazy-bind attempt |
| 422 | Empty or missing text |
| 500 | LLM call failed |

**Notes:**
- User message is saved with status `received` before the LLM call.
- Assistant message is saved with status `complete` on success, `failed` on error.
- `source_ids` (UUID array) is populated with **deduplicated** `source_id` values from retrieved chunks. The column already exists in the `Message` model — no migration needed. This represents unique sources used, consistent with its architectural role in citations and audit.
- `retrieved_chunks_count` is a **runtime-computed field** in the response schema — the actual number of chunks passed to the LLM from the retrieval result. It is NOT derived from `source_ids` because multiple chunks may come from the same source (e.g., 3 chunks from 1 book → `retrieved_chunks_count=3`, `source_ids` has 1 entry). The value is computed in the response schema from the retrieval result, not persisted.
- No `citations`, `content_type_spans`, or `idempotency_key` in S2-04.

### `GET /api/chat/sessions/{session_id}`

Returns session details with message history.

**Response (200 OK):**
```json
{
  "id": "uuid",
  "status": "active",
  "channel": "web",
  "snapshot_id": "uuid",
  "message_count": 4,
  "created_at": "2026-03-19T12:00:00Z",
  "messages": [
    {
      "id": "uuid",
      "role": "user",
      "content": "What is ProxyMind?",
      "status": "received",
      "created_at": "..."
    },
    {
      "id": "uuid",
      "role": "assistant",
      "content": "Based on my knowledge...",
      "status": "complete",
      "model_name": "openai/gpt-4o",
      "created_at": "..."
    }
  ]
}
```

## Service Architecture

### New files

```
backend/app/services/
├── retrieval.py        # RetrievalService — query embedding + Qdrant search
├── llm.py              # LLMService — LiteLLM wrapper
├── chat.py             # ChatService — orchestrator
└── prompt.py           # Prompt assembly (pure functions)

backend/app/api/
├── chat.py             # Chat API router (3 endpoints)
└── chat_schemas.py     # Pydantic request/response models
```

Existing files are modified minimally: `QdrantService` gets a new `search()` method; `SnapshotService` gets a new `get_active_snapshot()` method. `embedding.py` remains unchanged.

### RetrievalService (`services/retrieval.py`)

Responsible for finding relevant chunks given a user query.

**Dependencies:** `EmbeddingService`, `QdrantService`

**Primary method:**
```
search(query: str, snapshot_id: UUID, top_n: int = 5) -> list[RetrievedChunk]
```

**Flow:**
1. Call `EmbeddingService.embed_texts([query], task_type=RETRIEVAL_QUERY)` — get query vector.
2. Call `QdrantService.search(vector, snapshot_id, limit=top_n)` — get points with payload.
3. Return `list[RetrievedChunk]`.

**New method on QdrantService — `search()`:**
- Dense vector search with filter on `snapshot_id` + `agent_id` + `knowledge_base_id` (tenant-ready).
- Returns points with payload: `text_content`, `source_id`, `anchor_metadata`.
- `score_threshold` parameter: passed from `min_dense_similarity` in Settings. When `None` — no filtering. When set — Qdrant filters points below the threshold before returning (see D6).
- `limit` parameter maps to `retrieval_top_n` from Settings.

**`RetrievedChunk` dataclass:**
```
chunk_id: UUID
source_id: UUID
text_content: str
score: float
anchor_metadata: dict
```

### LLMService (`services/llm.py`)

Thin wrapper over LiteLLM. Single point of LLM invocation in the project.

**Dependencies:** `Settings` (model, api_key, api_base)

**Primary method:**
```
complete(messages: list[dict], temperature: float = 0.7) -> LLMResponse
```

**Internals:**
1. Call `litellm.acompletion(model=..., messages=..., api_key=..., api_base=...)`.
2. Wrap result in `LLMResponse`.
3. On LiteLLM error — log via structlog, raise `LLMError`.

**`LLMResponse` dataclass:**
```
content: str
model_name: str
token_count_prompt: int
token_count_completion: int
```

**Design notes:**
- No retry in LLMService — LiteLLM has built-in retry/fallback. Double retry creates unpredictable latency. If LiteLLM fails — fail fast.
- No streaming — S2-04 is JSON-only. A `stream()` method will be added in S4-02.
- `temperature` is a parameter, not config — different use cases (chat vs query rewriting in S4-04) need different temperatures.

### Prompt Assembly (`services/prompt.py`)

Pure functions (not a service class). Builds messages list in OpenAI chat API format (accepted by LiteLLM).

**Primary function:**
```
build_chat_prompt(
    user_query: str,
    retrieved_chunks: list[RetrievedChunk],
) -> list[dict]
```

**Output structure:**
```python
[
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": formatted_query_with_context}
]
```

**Minimal system prompt (S2-04):**
```
You are a knowledgeable assistant. Answer the user's question based ONLY
on the provided context. If the context does not contain enough information
to answer, say so honestly. Do not make up information.
```

**Context formatting in user message:**
```
Context from knowledge base:

---
[Chunk 1] (source: {source_id})
{text_content}

---
[Chunk 2] (source: {source_id})
{text_content}

---

Question: {user_query}
```

### ChatService (`services/chat.py`)

Thin orchestrator coordinating the chat flow. ~60-80 lines.

**Dependencies:** `AsyncSession`, `SnapshotService`, `RetrievalService`, `LLMService`

**`create_session(channel="web") -> Session`:**
1. Get active snapshot via `SnapshotService`.
2. If no active snapshot — create session with `snapshot_id=None`.
3. Save session, return.

**`answer(session_id: UUID, text: str) -> AssistantMessage`:**
1. Load session → 404 if not found.
2. If `session.snapshot_id` is `None` → **lazy bind**: query `SnapshotService.get_active_snapshot()`. If found, set `session.snapshot_id` and persist. If still `None` → 422.
3. Save user message (role=user, status=received).
4. `RetrievalService.search(text, session.snapshot_id)`.
5. If `len(chunks) < min_retrieved_chunks` → save assistant message with refusal, return.
6. `prompt_builder.build_chat_prompt(text, chunks)`.
7. `LLMService.complete(messages)` → on `LLMError`: save assistant message (status=failed), re-raise.
8. Save assistant message (role=assistant, status=complete, content, model_name, token counts, source_ids=deduplicated source UUIDs from chunks). Pass chunk count to response schema for `retrieved_chunks_count`.
9. Update `session.message_count`.
10. Return assistant message.

**`get_session(session_id: UUID) -> SessionWithMessages`:**
- Load session + messages ordered by `created_at` → 404 if not found.

## Configuration

### New settings in `backend/app/core/config.py`

```python
# LLM
llm_model: str = "openai/gpt-4o"
llm_api_key: str | None = None
llm_api_base: str | None = None
llm_temperature: float = 0.7

# Retrieval
retrieval_top_n: int = 5
min_retrieved_chunks: int = 1
min_dense_similarity: float | None = None  # disabled until calibrated via evals (S8-02)
```

### `.env.example` additions

```bash
# LLM Provider (via LiteLLM)
LLM_MODEL=openai/gpt-4o
LLM_API_KEY=
LLM_API_BASE=
```

`llm_temperature` is an internal default in Settings (rarely changed per deployment). Overridable via env var `LLM_TEMPERATURE` if needed, but not in `.env.example` to avoid clutter.

### Dependency injection additions

```
get_llm_service(request) -> LLMService         # from app.state (initialized in lifespan)
get_retrieval_service(request) -> RetrievalService  # from app.state (initialized in lifespan)
get_chat_service(session, snapshot_svc, retrieval_svc, llm_svc) -> ChatService  # per-request (needs DB session)
```

`LLMService` and `RetrievalService` are initialized in lifespan and stored in `app.state` — stateless, no reason to recreate per request. `ChatService` is per-request because it depends on `AsyncSession` (DB transaction scope).

## Error Handling

### Custom exceptions

```
SessionNotFoundError
NoActiveSnapshotError
LLMError
RetrievalError
```

### Error matrix

| Situation | Where caught | Behavior |
|-----------|-------------|----------|
| Session not found | `ChatService` | Raise `SessionNotFoundError` → router returns 404 |
| No active snapshot | `ChatService.answer` | Raise `NoActiveSnapshotError` → router returns 422 |
| Empty text | Pydantic schema | Automatic validation error → 422 |
| 0 chunks retrieved | `ChatService.answer` | Save assistant message with refusal text (status=complete), return normally |
| LLM call fails | `LLMService` → `ChatService` | `LLMService` raises `LLMError`; `ChatService` saves assistant message (status=failed), re-raises → router returns 500 |
| Qdrant unreachable | `QdrantService.search` | Propagate → `ChatService` saves failed message → 500 |
| Embedding fails | `EmbeddingService` | Propagate → same as above |

**Principle:** fail loud, save state. After the user message is saved, any error results in an assistant message with status=failed. This provides observability without the full audit log (S7-03).

## Testing Strategy

### Unit tests (`tests/unit/`)

| Test file | What | Mocks |
|-----------|------|-------|
| `test_prompt_builder.py` | `build_chat_prompt` returns correct message structure; context is formatted correctly; empty chunks list | None — pure functions |
| `test_llm_service.py` | `complete` returns `LLMResponse`; LiteLLM error raises `LLMError` | `litellm.acompletion` |
| `test_retrieval_service.py` | `search` calls embedding + qdrant; returns `RetrievedChunk` list; empty result | `EmbeddingService`, `QdrantService` |
| `test_chat_service.py` | Full flow: session creation, answer with chunks, answer without chunks (refusal), answer without snapshot (422), LLM error handling, **lazy bind** (session with snapshot_id=None successfully binds when active snapshot appears), lazy bind still 422 when no active snapshot exists | `RetrievalService`, `LLMService`, `SnapshotService`, DB session |
| `test_retrieval_service.py` (additional) | **min_dense_similarity filtering**: chunks below threshold are excluded before returning; with threshold=None all chunks pass; threshold filters weak chunks causing min_retrieved_chunks refusal | `EmbeddingService`, `QdrantService` |

### Integration tests (`tests/integration/`)

| Test file | What | Infrastructure |
|-----------|------|----------------|
| `test_chat_api.py` | E2E via HTTP: create session → send message → get history; 404/422 error cases; session without snapshot; **lazy bind E2E** (create session before publish → publish snapshot → send message succeeds) | TestClient + testcontainers (PG) + mocked LLM + mocked Qdrant |

### Mock strategy

| Component | CI behavior |
|-----------|-------------|
| LiteLLM | Always mocked — no external provider calls in CI |
| QdrantService.search | Mocked — returns pre-built chunks (Qdrant testcontainer is excessive for chat tests; Qdrant indexing is tested in knowledge circuit) |
| EmbeddingService | Mocked — no Gemini API calls in CI |
| PostgreSQL | Real — via testcontainers (consistent with existing tests) |
| Pydantic validation | Real |

## Files to Create

| File | Purpose |
|------|---------|
| `backend/app/services/retrieval.py` | RetrievalService |
| `backend/app/services/llm.py` | LLMService |
| `backend/app/services/chat.py` | ChatService orchestrator |
| `backend/app/services/prompt.py` | Prompt assembly functions |
| `backend/app/api/chat.py` | Chat API router |
| `backend/app/api/chat_schemas.py` | Pydantic request/response schemas |
| `backend/tests/unit/test_prompt_builder.py` | Unit tests for prompt assembly |
| `backend/tests/unit/test_llm_service.py` | Unit tests for LLM service |
| `backend/tests/unit/test_retrieval_service.py` | Unit tests for retrieval |
| `backend/tests/unit/test_chat_service.py` | Unit tests for chat orchestrator |
| `backend/tests/integration/test_chat_api.py` | Integration tests for chat API |

## Files to Modify

| File | Change |
|------|--------|
| `backend/app/services/qdrant.py` | Add `search()` method with optional `score_threshold` |
| `backend/app/services/snapshot.py` | Add `get_active_snapshot()` method for default agent |
| `backend/app/core/config.py` | Add LLM and retrieval settings (including `min_dense_similarity`) |
| `backend/app/api/dependencies.py` | Add DI functions for new services |
| `backend/app/main.py` | Register chat router; initialize LLMService and RetrievalService in lifespan |
| `backend/.env.example` | Add LLM_MODEL, LLM_API_KEY, LLM_API_BASE |

## Known Limitations & Trade-offs

### Public GET history (UUID-as-secret)

`GET /api/chat/sessions/{session_id}` is public — anyone with the UUID can read the conversation. For S2-04 (curl testing, no frontend, no external channels), this is an acceptable trade-off. UUID v4 is unguessable in practice, and the endpoint is designed for same-client flow (the client that created the session retrieves its own history).

This is NOT a secure API for third-party channels. Visitor identity binding (S11-01) will address this properly by associating sessions with authenticated visitors.

### Quality guard without calibrated threshold

With `min_dense_similarity=None` (default), the system may return answers based on weakly relevant context. The LLM system prompt instructs it to refuse when context is insufficient, but this is a soft guard. Full quality control requires calibrated `min_dense_similarity` from evals (S8-02).
