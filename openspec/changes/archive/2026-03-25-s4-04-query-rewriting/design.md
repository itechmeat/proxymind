# S4-04: Query Rewriting — Design

## Context

S4-04 belongs to Phase 4: Dialog Expansion. Prerequisites are in place: SSE streaming with idempotency (S4-02), persona loading (S4-01), and citation builder (S4-03) are complete. The retrieval pipeline already performs hybrid search (dense + BM25 sparse, RRF fusion) scoped by `snapshot_id`.

What is missing: in multi-turn conversations, queries like "tell me more" or "what about that?" are meaningless for retrieval without context. The user's intent depends on prior messages, but the retrieval pipeline receives only the current query. Query rewriting closes this gap — it reformulates follow-up queries into self-contained search queries using conversation history before retrieval.

**Affected circuit:** Dialogue circuit. The change touches the chat service (new step before retrieval), LLM service (non-streaming rewrite call), message persistence (new column), and configuration. No changes to the knowledge or operational circuits.

## Goals

- Reformulate follow-up queries into self-contained search queries using conversation history, improving hybrid retrieval in multi-turn conversations
- Fail-open on any error (timeout, LLM failure, empty response) — retrieval proceeds with the original query
- Skip rewriting when conversation history is empty (first message in session) — no wasted latency or tokens
- Persist the rewritten query in the database for eval traceability (retrieval metrics must be measured against the actual query sent to Qdrant)
- Use the original query in the main LLM prompt — the rewritten query is an internal retrieval optimization, not a user-facing transformation
- Support optional dedicated LLM model for rewriting (cheaper/faster than the main model)

## Non-Goals

- Rewrite prompt tuning — initial prompt is functional; refinement is an eval concern (S8)
- Multiple rewrite strategies — single strategy is sufficient for v1
- Caching rewritten queries — premature optimization; rewrite latency (~300ms) is acceptable
- Streaming rewrite — response is a single short query; streaming adds complexity for no benefit
- Updating the default `llm_model` — the current default in config is outdated but that is a separate config change outside S4-04 scope

## Decisions

### D1: Service placement — new `QueryRewriteService`

**Choice:** New `QueryRewriteService` in `backend/app/services/query_rewrite.py`.

**Rationale:** Follows the existing single-responsibility pattern (`RetrievalService`, `CitationService`, `LLMService`). Testable in isolation with mocked LLM. Injectable via dependency injection. Reusable by future consumers (A2A endpoint in S10-01).

**Alternatives rejected:**
- Inline in `ChatService` — violates SRP, harder to test and reuse
- Part of `RetrievalService` — conflates query transformation with search execution

### D2: LLM model for rewrite — optional `rewrite_llm_model`, fallback to `llm_model`

**Choice:** Optional `rewrite_llm_model` setting. When `None`, falls back to the main `llm_model`. When set, a dedicated `LLMService` instance is created with its own model/key/base.

**Rationale:** Works out-of-the-box without extra config. The owner can optimize later with a cheaper/faster model (e.g., `gemini-2.0-flash`). The spec says "a cheap/fast model can be used" — the option exists but is not forced.

**Alternatives rejected:**
- Require a separate model always — forces unnecessary config for simple setups
- Hardcode a specific rewrite model — violates the provider-agnostic design

### D3: Rewrite temperature — `0.1`

**Choice:** `rewrite_temperature = 0.1`, configurable.

**Rationale:** Reformulation should be deterministic. Low temperature reduces variance in the rewritten query. Configurable for tuning.

**Alternatives rejected:**
- Temperature `0.0` — some providers treat zero specially; `0.1` is effectively deterministic without edge cases
- Higher temperature — introduces unnecessary variance in reformulation

### D4: Timeout mechanism — `asyncio.wait_for`

**Choice:** `asyncio.wait_for(coro, timeout=rewrite_timeout_ms/1000)` with default timeout of 3000ms.

**Rationale:** Standard library, idiomatic Python async. Covers all failure modes: network issues, slow LLM, hangs. On `TimeoutError`, log a warning and use the original query.

**Alternatives rejected:**
- `httpx` timeout only — does not cover LLM client-side processing time
- No timeout — a hung rewrite call blocks the entire chat response indefinitely

### D5: Fail-open scope — any exception falls back to original query

**Choice:** Not only timeout. LLM errors, empty responses, parse failures — all fall back to the original query gracefully.

**Rationale:** Query rewriting MUST NOT be a point of failure on the chat hot path. The original query is always a valid (if suboptimal) input for retrieval.

**Alternatives rejected:**
- Fail-closed (raise error) — a rewrite failure would block the entire chat response
- Retry on failure — adds latency to the hot path for uncertain benefit

### D6: Skip condition — empty history (first message)

**Choice:** Skip rewrite when conversation history is empty. Return the original query immediately without calling the LLM.

**Rationale:** No history means no context to reformulate against. First messages are typically self-contained. Saves ~300-500ms latency and tokens on every new session.

**Alternatives rejected:**
- Always call the rewriter — wastes latency and tokens on a no-op for first messages
- Skip based on query heuristics (e.g., length) — fragile, language-dependent, unnecessary complexity

### D7: Token budget counting — character-based estimate (`CHARS_PER_TOKEN = 3`)

**Choice:** Estimate tokens as `len(content) / 3` (1 token per 3 characters). Default budget of 2048 tokens with 200 tokens reserved for the system prompt and current query.

**Rationale:** This is rough trimming of history, not billing-precise counting. The estimate is intentionally conservative: CJK characters are often 1-2 chars per token, so a 3-char estimate overestimates token count and keeps the prompt safely within budget. No external dependency (no tiktoken). Provider-independent. Accuracy within +/-20% is acceptable for this use case.

**Alternatives rejected:**
- `tiktoken` — adds a dependency, is model-specific (OpenAI tokenizer), and precision is unnecessary for rough history trimming
- No budget — risks sending excessive history to the rewrite LLM, increasing cost and latency

### D8: History content — full user + assistant message pairs

**Choice:** Include both user and assistant messages in the rewrite prompt, trimmed from oldest first to fit the token budget.

**Rationale:** Assistant responses carry essential context. "Tell me more" is meaningless without knowing what the assistant said. The token budget (2048) naturally limits inclusion — old messages are trimmed first. Additionally capped by `rewrite_history_messages` (default: 10) — whichever limit is hit first.

**Alternatives rejected:**
- User messages only — loses the context that the user is referring to
- Full history without trimming — unbounded prompt size, excessive cost

### D9: Rewritten query storage — new nullable `rewritten_query TEXT` column on `messages`

**Choice:** Alembic migration adds a nullable `rewritten_query` column to the `messages` table.

**Rationale:** Enables eval traceability: retrieval metrics (Precision@K, MRR) must be measured against the actual query sent to Qdrant. Populated only for user messages when the rewrite produces a query different from the original (`is_rewritten=True`). `NULL` when: first message in session, rewrite disabled, rewrite failed/timed out, or rewriter returned the same query. No index needed — queried only for debugging and eval pipelines.

**Alternatives rejected:**
- Separate table — over-engineering for a single nullable column
- Log-only (no persistence) — logs are not queryable for eval pipelines
- Store in Redis — ephemeral, not suitable for eval traceability

### D10: Rewritten query NOT in main prompt — original query used instead

**Choice:** The main LLM prompt uses the original user query, not the rewritten one. The rewritten query is used exclusively for hybrid search in Qdrant.

**Rationale:** The rewritten query is optimized for search — it may sound unnatural or lose nuance. The user asked the question in their words; the LLM should respond to that phrasing. Rewriting is an internal retrieval optimization, not a user-facing transformation.

**Alternatives rejected:**
- Use rewritten query in main prompt — the LLM responds to a reformulated question the user never asked, which feels unnatural
- Use both (original + rewritten) — confuses the LLM with two versions of the same question

### D11: Global toggle — `rewrite_enabled` setting (default `True`)

**Choice:** `rewrite_enabled` boolean setting. When `False`, rewriting is skipped entirely. Simple boolean check before calling the service.

**Rationale:** Allows disabling rewrite for debugging, cost control, or A/B eval comparison. Default is `True` because rewriting improves retrieval quality in multi-turn conversations.

**Alternatives rejected:**
- No toggle — no way to disable for debugging or cost control
- Per-session toggle — over-engineering for v1

### D12: Rewrite prompt language — preserve original query language

**Choice:** The rewrite prompt instructs the LLM: "Preserve the language of the original query."

**Rationale:** ProxyMind is multilingual by policy. The rewritten query must match the language of the user's input for correct BM25 stemming and embedding task type. A Russian query rewritten into English would fail BM25 keyword matching against Russian-indexed content.

**Alternatives rejected:**
- Always rewrite to English — breaks BM25 and embedding for non-English content
- Detect language and switch — unnecessary complexity when the LLM can simply preserve the input language

## Data Flow

### Chat flow (with rewriting)

```
POST /api/chat/messages { session_id, text, idempotency_key? }
    |
    v
Load session + ensure snapshot binding
    |
    v
Check idempotency (optional)
    |
    v
Persist user message (status: RECEIVED)
    |
    v
Load conversation history (session.messages, excluding current)
    |
    v
+-- rewrite_enabled=false OR history empty? --- YES --> search_query = text
|                                                       rewritten_query = NULL
|   NO
|   |
|   v
|   Trim history to rewrite_token_budget (last N messages fitting budget)
|   |
|   v
|   asyncio.wait_for(LLM.complete(rewrite_prompt), timeout)
|   |
|   +-- success --> search_query = rewritten_query
|   |               Update message: rewritten_query = search_query
|   |               log.info("query_rewrite.success", ...)
|   |
|   +-- timeout --> search_query = text
|   |               log.warning("query_rewrite.timeout", ...)
|   |
|   +-- error   --> search_query = text
|                   log.warning("query_rewrite.error", ...)
+---------------------------+
                            v
Retrieval: hybrid_search(search_query, snapshot_id)
    |
    v
Build prompt (persona + chunks + ORIGINAL text)
    |
    v
LLM stream --> SSE tokens --> citations --> done
    |
    v
Persist assistant message (status: COMPLETE)
```

### Rewrite prompt template

```
System:
  You are a query rewriting assistant. Given a conversation history and
  the user's latest message, reformulate the latest message into a
  self-contained search query that captures the full intent.

  Rules:
  - Output ONLY the rewritten query, nothing else
  - If the message is already self-contained, return it as-is
  - Preserve the language of the original query
  - Do not answer the question, only reformulate it
  - Include relevant context from the conversation history

User:
  Conversation history:
  User: What books has Sergey written about AI?
  Assistant: Sergey has written three books about AI: "Neural Networks
  for Beginners" (2023), "Deep Learning in Practice" (2024), and
  "AI Ethics" (2025).

  Current message: Tell me more about the second one

Expected output:
  Tell me more about Sergey's book "Deep Learning in Practice" (2024)
```

### Token budget trimming algorithm

History is trimmed to fit `rewrite_token_budget` (default: 2048 tokens):

1. Start from the most recent message and work backwards.
2. Estimate tokens per message: `len(message.content) / CHARS_PER_TOKEN` where `CHARS_PER_TOKEN = 3` (conservative for multilingual safety — CJK characters are often 1-2 chars/token).
3. Accumulate messages until adding the next one would exceed the budget (reserving ~200 tokens for system prompt + current query).
4. Return messages in chronological order (oldest first).

Additionally capped by `rewrite_history_messages` (default: 10) — whichever limit is hit first.

## Configuration

New settings in `backend/app/core/config.py`:

| Parameter | Type | Default | Env var | Description |
|-----------|------|---------|---------|-------------|
| `rewrite_enabled` | `bool` | `True` | `REWRITE_ENABLED` | Global toggle for query rewriting |
| `rewrite_llm_model` | `str \| None` | `None` | `REWRITE_LLM_MODEL` | LLM model for rewriting. `None` falls back to `llm_model` |
| `rewrite_llm_api_key` | `str \| None` | `None` | `REWRITE_LLM_API_KEY` | API key for rewrite model. `None` falls back to `llm_api_key` |
| `rewrite_llm_api_base` | `str \| None` | `None` | `REWRITE_LLM_API_BASE` | Base URL for rewrite model. `None` falls back to `llm_api_base` |
| `rewrite_temperature` | `float` | `0.1` | `REWRITE_TEMPERATURE` | Low temperature for deterministic reformulation |
| `rewrite_timeout_ms` | `int` | `3000` | `REWRITE_TIMEOUT_MS` | Timeout in ms. On exceed, fail-open to original query |
| `rewrite_token_budget` | `int` | `2048` | `REWRITE_TOKEN_BUDGET` | Max token budget for history + query in rewrite prompt |
| `rewrite_history_messages` | `int` | `10` | `REWRITE_HISTORY_MESSAGES` | Max messages to include in rewrite context |

## Database Migration

Alembic migration: add one nullable column to `messages` table.

```sql
ALTER TABLE messages ADD COLUMN rewritten_query TEXT;
```

- Populated only for user messages (`role = 'user'`) when the rewrite produces a different query (`is_rewritten=True`)
- `NULL` when: first message in session, rewrite disabled, rewrite failed/timed out, or rewriter returned the same query
- No index needed — queried only for debugging and eval pipelines

## Observability

Structlog events:

| Event | Level | Fields | When |
|-------|-------|--------|------|
| `query_rewrite.skip` | `debug` | `reason` ("empty_history" \| "disabled"), `session_id` | Rewrite skipped |
| `query_rewrite.success` | `info` | `history_messages`, `is_rewritten`, `latency_ms`, `session_id` | Rewrite succeeded |
| `query_rewrite.timeout` | `warn` | `timeout_ms`, `session_id` | LLM call exceeded timeout |
| `query_rewrite.error` | `warn` | `error`, `session_id` | LLM call raised an exception |

**Privacy note:** Log events intentionally omit raw query text (both original and rewritten). The existing `ChatService` logs metadata only — `session_id`, `snapshot_id`, counts — never user message content. `QueryRewriteService` follows the same pattern. The rewritten query is persisted in `messages.rewritten_query` for debugging and eval; logs do not duplicate PII.

## File Map

### New files

| File | Purpose |
|------|---------|
| `backend/app/services/query_rewrite.py` | `QueryRewriteService` with `rewrite()` method |
| `backend/migrations/versions/008_add_rewritten_query_to_messages.py` | Alembic migration |
| `backend/tests/unit/test_query_rewrite.py` | Unit tests for rewrite service |

### Modified files

| File | Change |
|------|--------|
| `backend/app/core/config.py` | Add 8 rewrite settings |
| `backend/app/services/chat.py` | Insert rewrite step before retrieval in `stream_answer()` and `answer()` |
| `backend/app/api/dependencies.py` | Wire `QueryRewriteService` into `get_chat_service()` |
| `backend/app/db/models/dialogue.py` | Add `rewritten_query` column to `Message` |
| `backend/app/main.py` | Initialize `QueryRewriteService` in lifespan; create dedicated `LLMService` when `rewrite_llm_model` is set |
| `backend/tests/conftest.py` | Add rewrite settings to `chat_app` fixture, add `mock_rewrite_service` fixture |
| `backend/tests/unit/test_chat_service.py` | Pass `query_rewrite_service` to `ChatService` in `_make_service` helper |
| `backend/tests/unit/test_chat_streaming.py` | Pass `query_rewrite_service` to `ChatService` in `_make_service` helper |
| `backend/tests/integration/test_chat_sse.py` | Integration tests: rewrite persistence and retrieval with rewritten query |

## Risks and Trade-offs

**Additional LLM call adds latency.** The rewrite call adds ~300-500ms to the chat response for multi-turn messages. This is acceptable because: it only fires when history exists (not on first messages), it runs before retrieval (not in the streaming hot path), and it dramatically improves retrieval quality for follow-up queries. The timeout (3000ms) caps worst-case latency.

**Character-based token estimation is imprecise.** The `CHARS_PER_TOKEN = 3` estimate can be off by +/-20%. This is acceptable for rough history trimming — the goal is to stay within a reasonable budget, not to count tokens precisely. The conservative estimate (3 chars) means the prompt may be slightly under-budget, which is preferable to exceeding it.

**Rewrite quality depends on the LLM.** The rewriter may occasionally produce suboptimal reformulations. This is mitigated by: fail-open on any error, the original query as fallback for empty/bad responses, and the eval pipeline (S8) for measuring and improving rewrite quality over time.

**New column adds migration.** The `rewritten_query` column is nullable and has no index, so the migration is lightweight (instant `ALTER TABLE ADD COLUMN` on PostgreSQL). No performance impact on existing queries.
