## Story

**S4-04: Query rewriting** (Phase 4: Dialog Expansion)

- **Outcome:** multi-turn dialog yields relevant retrieval
- **Verification:** "tell me more" -> reformulated -> better retrieval; timeout -> fallback to original
- **Stable behavior requiring tests:** QueryRewriteService rewrite logic, fail-open on timeout and LLM errors, skip when history is empty, skip when disabled, token budget trimming, history message cap, rewritten_query persistence in DB, chat flow integration (rewrite before retrieval, original query in LLM prompt)

## Why

Follow-up queries like "tell me more" or "what about the second one" are meaningless for vector and BM25 search without conversation context. Retrieval happens before the main LLM call, so the LLM cannot compensate for a poor search query -- the chunks are already fetched. A dedicated rewrite step reformulates the user's query into a self-contained search query using conversation history, producing relevant retrieval results for multi-turn dialog. The rewritten query is persisted for eval traceability (S8-01/S8-02).

## What Changes

- Add `QueryRewriteService` -- new service that calls `LLMService.complete()` with a rewrite prompt containing trimmed conversation history and the current query, returning a self-contained search query. Fails open on any error (timeout, LLM failure, empty response) by falling back to the original query. Skips rewrite entirely when history is empty (first message) or when disabled via config.
- Add 8 rewrite configuration settings -- global toggle, optional dedicated LLM model/key/base, temperature, timeout, token budget, and history message cap.
- Add `rewritten_query` column to `messages` table -- nullable TEXT, populated only for user messages when the rewrite produces a query different from the original (`is_rewritten=True`). `NULL` when: first message, rewrite disabled, rewrite failed/timed out, or rewriter returned the same query. Alembic migration 008.
- Update `ChatService` -- insert rewrite step between user message persistence and retrieval in both `stream_answer()` and `answer()`. The rewritten query is used for hybrid search; the original query is preserved for the main LLM prompt and user-facing display.
- Wire `QueryRewriteService` into DI -- initialize in `main.py` lifespan (with optional dedicated `LLMService` when `rewrite_llm_model` is set), inject via `dependencies.py`.

## Capabilities

### New Capabilities

- `query-rewriting`: LLM-based query reformulation with conversation history context, fail-open timeout, token budget trimming, history message cap, configurable model/temperature, rewritten query persistence for eval traceability

### Modified Capabilities

- `chat-dialogue`: Insert rewrite step before retrieval in chat flow. `ChatService` accepts `QueryRewriteService` dependency. Rewritten query used for search, original query used for LLM prompt. `Message` model gains `rewritten_query` column.

## Impact

- **New service:** `services/query_rewrite.py` (QueryRewriteService)
- **New migration:** `008_add_rewritten_query_to_messages.py`
- **Config:** `config.py` (8 new settings)
- **Chat pipeline:** `chat.py` (rewrite step), `dependencies.py` (wiring), `main.py` (initialization)
- **DB model:** `db/models/dialogue.py` (new column)
- **Test fixtures:** `conftest.py` (rewrite settings + mock service)
- **Existing tests:** `test_chat_service.py`, `test_chat_streaming.py` (pass new dependency)
- **No new dependencies.** No API schema changes. No frontend impact.
