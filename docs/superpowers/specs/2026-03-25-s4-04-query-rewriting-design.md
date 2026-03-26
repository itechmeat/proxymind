# S4-04: Query Rewriting — Design Spec

## Story

> LLM-based reformulation with history context. Fail-open on timeout. Token budget.

## Approach

**Dedicated rewrite call before retrieval.** A new `QueryRewriteService` makes a non-streaming LLM call to reformulate the user's query using conversation history. The rewritten query is used exclusively for hybrid search in Qdrant. The original query is preserved for the main LLM prompt and user-facing display.

**Why this approach:**

- Rewriting MUST happen before retrieval — queries like "tell me more" are meaningless for vector/BM25 search without context
- Separate LLM call isolates rewrite latency and failures from the main generation pipeline
- Fail-open is natural: `try/except` around one call, fallback to original query
- Rewritten query is persisted in the database for eval traceability (S8-01/S8-02)
- Matches the architecture described in `docs/rag.md` § Query rewriting and `docs/architecture.md` § Chat flow

**Rejected alternatives:**

- **Embed rewriting into the main LLM system prompt:** Retrieval still happens on the original (poor) query. The core problem — bad retrieval input — remains unsolved. The LLM may reformulate internally, but the search results are already fetched.
- **Always call rewriter (including first message):** First message has no history — rewriter would return the same query. Wastes ~300–500ms latency and tokens on every new session for a no-op.

## Design Decisions

| #   | Decision                       | Choice                                                                 | Rationale                                                                                                                                                                                                                  |
| --- | ------------------------------ | ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Service placement              | New `QueryRewriteService` in `backend/app/services/query_rewrite.py`   | Follows existing SRP pattern (`RetrievalService`, `CitationService`, `LLMService`). Testable in isolation. Injectable via DI. Reusable by future consumers (A2A endpoint, S10-01).                                          |
| D2  | LLM model for rewrite          | Optional `rewrite_llm_model`, fallback to `llm_model`                  | Works out-of-the-box without extra config. Owner can optimize later with a cheaper/faster model (e.g., `gemini-2.0-flash`). Spec says "a cheap/fast model can be used" — the option exists but is not forced.               |
| D3  | Rewrite temperature            | `rewrite_temperature = 0.1`                                            | Reformulation should be deterministic. Low temperature reduces variance. Configurable for tuning.                                                                                                                           |
| D4  | Timeout mechanism              | `asyncio.wait_for(coro, timeout=rewrite_timeout_ms/1000)`              | Standard library, idiomatic Python async. Covers all failure modes (network, slow LLM, hang). On `TimeoutError` → log warning, use original query.                                                                         |
| D5  | Fail-open scope                | Any exception → fallback to original query                             | Not only timeout. LLM errors, empty responses, parse failures — all fall back gracefully. Query rewriting MUST NOT be a point of failure on the chat hot path.                                                              |
| D6  | Skip condition                 | Skip rewrite when conversation history is empty (first message)        | No history → no context to reformulate against. Saves latency and tokens. Single `if` check, trivial logic.                                                                                                                |
| D7  | Token budget counting          | Character-based estimate: 1 token ≈ 3 characters (conservative)       | Rough trimming of history, not billing-precise counting. ±20% is acceptable. No external dependency (tiktoken). Provider-independent. Conservative 3 chars/token handles CJK/multilingual safely.                            |
| D8  | History content                | Full user + assistant message pairs                                    | Assistant responses carry essential context. "Tell me more" is meaningless without knowing what the assistant said. Token budget (2048) naturally limits inclusion — old messages are trimmed first.                          |
| D9  | Rewritten query storage        | New nullable `rewritten_query TEXT` column on `messages` table         | Enables eval traceability: retrieval metrics (Precision@K, MRR) must be measured against the actual query sent to Qdrant. Alembic migration adds one nullable column. Populated only for user messages when rewrite occurs. |
| D10 | Rewritten query in main prompt | Original user query used in main LLM prompt, NOT rewritten             | Rewritten query is optimized for search, may sound unnatural. User asked the question in their words — LLM should respond to that. Rewrite is an internal retrieval optimization, not a user-facing transformation.         |
| D11 | Global toggle                  | `rewrite_enabled` setting (default `True`)                             | Allows disabling rewrite for debugging, cost control, or A/B eval comparison. Simple boolean check before calling the service.                                                                                              |
| D12 | Rewrite prompt language        | Prompt instructs LLM to preserve the language of the original query    | ProxyMind is multilingual by policy. The rewritten query must match the language of the user's input for correct BM25 stemming and embedding task type.                                                                    |

## Chat Flow (with rewriting)

```
POST /api/chat/messages { session_id, text, idempotency_key? }
    │
    ▼
Load session + ensure snapshot binding
    │
    ▼
Check idempotency (optional)
    │
    ▼
Persist user message (status: RECEIVED)
    │
    ▼
Load conversation history (session.messages, excluding current)
    │
    ▼
┌─ rewrite_enabled=false OR history empty? ─── YES ──► search_query = text
│                                                       rewritten_query = NULL
│   NO
│   │
│   ▼
│   Trim history to rewrite_token_budget (last N messages fitting budget)
│   │
│   ▼
│   asyncio.wait_for(LLM.complete(rewrite_prompt), timeout)
│   │
│   ├── success ──► search_query = rewritten_query
│   │               Update message: rewritten_query = search_query
│   │               log.info("query_rewrite.success", ...)
│   │
│   ├── timeout ──► search_query = text
│   │               log.warning("query_rewrite.timeout", ...)
│   │
│   └── error   ──► search_query = text
│                   log.warning("query_rewrite.error", ...)
└───────────────────────┐
                        ▼
Retrieval: hybrid_search(search_query, snapshot_id)
    │
    ▼
Build prompt (persona + chunks + ORIGINAL text)
    │
    ▼
LLM stream → SSE tokens → citations → done
    │
    ▼
Persist assistant message (status: COMPLETE)
```

## Rewrite Prompt

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

## Token Budget Trimming

History is trimmed to fit `rewrite_token_budget` (default: 2048 tokens):

1. Start from the most recent message and work backwards
2. Estimate tokens per message: `len(message.content) / 3` (conservative for multilingual safety — CJK characters are often 1-2 chars/token)
3. Accumulate messages until adding the next one would exceed the budget (reserving ~200 tokens for system prompt + current query)
4. Return messages in chronological order (oldest first)

Additionally capped by `rewrite_history_messages` (default: 10) — whichever limit is hit first.

## Configuration

New settings in `backend/app/core/config.py`:

| Parameter                        | Type           | Default | Env var                           | Description                                                  |
| -------------------------------- | -------------- | ------- | --------------------------------- | ------------------------------------------------------------ |
| `rewrite_enabled`                | `bool`         | `True`  | `REWRITE_ENABLED`                 | Global toggle for query rewriting                            |
| `rewrite_llm_model`              | `str \| None`  | `None`  | `REWRITE_LLM_MODEL`              | LLM model for rewriting. `None` → fallback to `llm_model`   |
| `rewrite_llm_api_key`            | `str \| None`  | `None`  | `REWRITE_LLM_API_KEY`            | API key for rewrite model. `None` → fallback to `llm_api_key`|
| `rewrite_llm_api_base`           | `str \| None`  | `None`  | `REWRITE_LLM_API_BASE`           | Base URL for rewrite model. `None` → fallback to `llm_api_base`|
| `rewrite_temperature`            | `float`        | `0.1`   | `REWRITE_TEMPERATURE`             | Low temperature for deterministic reformulation              |
| `rewrite_timeout_ms`             | `int`          | `3000`  | `REWRITE_TIMEOUT_MS`              | Timeout in ms. On exceed → fail-open to original query       |
| `rewrite_token_budget`           | `int`          | `2048`  | `REWRITE_TOKEN_BUDGET`            | Max token budget for history + query in rewrite prompt       |
| `rewrite_history_messages`       | `int`          | `10`    | `REWRITE_HISTORY_MESSAGES`        | Max messages to include in rewrite context                   |

## Database Migration

Alembic migration: add one nullable column to `messages` table.

```sql
ALTER TABLE messages ADD COLUMN rewritten_query TEXT;
```

- Populated only for user messages (`role = 'user'`) when rewriting occurs
- `NULL` when: first message in session, rewrite disabled, rewrite failed/timed out
- No index needed — queried only for debugging and eval pipelines

## Observability

**Structlog events:**

| Event                   | Level   | Fields                                              | When                          |
| ----------------------- | ------- | --------------------------------------------------- | ----------------------------- |
| `query_rewrite.skip`    | `debug` | `reason` ("empty_history" \| "disabled"), `session_id` | Rewrite skipped            |
| `query_rewrite.success` | `info`  | `history_messages`, `is_rewritten`, `latency_ms`, `session_id` | Rewrite succeeded     |
| `query_rewrite.timeout` | `warn`  | `timeout_ms`, `session_id`                          | LLM call exceeded timeout     |
| `query_rewrite.error`   | `warn`  | `error`, `session_id`                               | LLM call raised an exception  |

**Privacy note:** Log events intentionally omit raw query text (`original`, `rewritten`). The existing `ChatService` logs metadata only — `session_id`, `snapshot_id`, counts — never user message content. `QueryRewriteService` follows the same pattern. The rewritten query is persisted in `messages.rewritten_query` for debugging and eval; logs should not duplicate PII.

## New Files

| File                                              | Purpose                                    |
| ------------------------------------------------- | ------------------------------------------ |
| `backend/app/services/query_rewrite.py`           | `QueryRewriteService` with `rewrite()` method |
| `backend/migrations/versions/xxxx_add_rewritten_query.py` | Alembic migration                  |
| `backend/tests/unit/test_query_rewrite.py`        | Unit tests for rewrite service             |
| `backend/tests/integration/test_chat_rewrite.py`  | Integration tests for chat + rewrite flow  |

## Modified Files

| File                                    | Change                                                       |
| --------------------------------------- | ------------------------------------------------------------ |
| `backend/app/core/config.py`           | Add rewrite settings (8 new fields)                          |
| `backend/app/services/chat.py`         | Insert rewrite step before retrieval in `stream_answer()`    |
| `backend/app/api/dependencies.py`      | Wire `QueryRewriteService` into `get_chat_service()`         |
| `backend/app/db/models/dialogue.py`    | Add `rewritten_query` column to `Message`                    |
| `backend/app/main.py`                  | Initialize `QueryRewriteService` in lifespan. When `rewrite_llm_model` is set, create a dedicated `LLMService` instance for rewriting (separate model/key/base); otherwise reuse the main `LLMService` |

## Testing

### Unit tests (`tests/unit/test_query_rewrite.py`)

| Test                                   | Description                                                         |
| -------------------------------------- | ------------------------------------------------------------------- |
| `test_rewrite_with_history`            | LLM called with correct prompt; returns rewritten query             |
| `test_rewrite_skip_empty_history`      | Empty history → returns original, LLM not called                    |
| `test_rewrite_timeout_fallback`        | `TimeoutError` → returns original, `is_rewritten=False`             |
| `test_rewrite_error_fallback`          | LLM exception → returns original, `is_rewritten=False`              |
| `test_rewrite_empty_response_fallback` | LLM returns empty string → returns original, `is_rewritten=False`   |
| `test_token_budget_trimming`           | Long history trimmed to budget; most recent messages kept            |
| `test_history_messages_cap`            | History exceeding `rewrite_history_messages` is capped          |
| `test_rewrite_disabled`                | `rewrite_enabled=False` → returns original, LLM not called          |

### Integration tests (`tests/integration/test_chat_rewrite.py`)

| Test                                   | Description                                                         |
| -------------------------------------- | ------------------------------------------------------------------- |
| `test_chat_rewrite_persisted`          | Send 2+ messages → `rewritten_query` populated in DB for 2nd msg    |
| `test_chat_first_message_no_rewrite`   | First message → `rewritten_query` is NULL in DB                     |

All tests are deterministic (LLM mocked), suitable for CI.

## Non-Goals

- **Rewrite prompt tuning** — initial prompt is functional; refinement is an eval concern (S8)
- **Multiple rewrite strategies** — single strategy is sufficient for v1
- **Caching rewritten queries** — premature optimization; rewrite latency (~300ms) is acceptable
- **Streaming rewrite** — `complete()` is used, not `stream()`. Response is a single short query, streaming adds complexity for no benefit
- **Updating the default `llm_model`** — the current `openai/gpt-4o` default in config is outdated and should be updated to `gemini-3.1-pro-preview`, but that is a separate config change outside S4-04 scope
