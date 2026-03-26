## 1. Configuration

- [x] 1.1 Add 8 rewrite settings (`rewrite_enabled`, `rewrite_llm_model`, `rewrite_llm_api_key`, `rewrite_llm_api_base`, `rewrite_temperature`, `rewrite_timeout_ms`, `rewrite_token_budget`, `rewrite_history_messages`) to `backend/app/core/config.py` with unit tests in `backend/tests/unit/test_config.py`

## 2. Database Migration

- [x] 2.1 Add `rewritten_query: Mapped[str | None]` column to Message model in `backend/app/db/models/dialogue.py`
- [x] 2.2 Create Alembic migration `backend/migrations/versions/008_add_rewritten_query_to_messages.py` — add nullable `rewritten_query` TEXT column to `messages` table

## 3. QueryRewriteService

- [x] 3.1 Create unit tests in `backend/tests/unit/test_query_rewrite.py` — test rewrite with history, skip empty history, skip disabled, timeout fallback, error fallback, empty response fallback, token budget trimming, history messages cap
- [x] 3.2 Create `backend/app/services/query_rewrite.py` — `RewriteResult` dataclass, `QueryRewriteService` with `rewrite()`, `_trim_history()`, `_build_prompt()`, fail-open on timeout/error/empty response
- [x] 3.3 Verify observability contract in `backend/app/services/query_rewrite.py` — structlog events MUST NOT contain raw query text (`original`/`rewritten`); `query_rewrite.success` MUST include `latency_ms` (measured via `asyncio.get_event_loop().time()`); `query_rewrite.error` MUST include `error` field with exception string. Add unit test assertions on structlog calls to validate privacy and field presence.

## 4. DI Wiring

- [x] 4.1 Add `_create_query_rewrite_service()` factory to `backend/app/main.py` — handles optional dedicated `LLMService` when `rewrite_llm_model` is set
- [x] 4.2 Initialize `query_rewrite_service` in lifespan in `backend/app/main.py`
- [x] 4.3 Add `get_query_rewrite_service()` DI getter in `backend/app/api/dependencies.py`
- [x] 4.4 Update `get_chat_service()` in `backend/app/api/dependencies.py` — pass `query_rewrite_service` to `ChatService`
- [x] 4.5 Update `ChatService.__init__` in `backend/app/services/chat.py` to accept `query_rewrite_service` parameter
- [x] 4.6 Update `_make_service` in `backend/tests/unit/test_chat_service.py` to pass `query_rewrite_service`
- [x] 4.7 Update `_make_service` in `backend/tests/unit/test_chat_streaming.py` to pass `query_rewrite_service`
- [x] 4.8 Add `mock_rewrite_service` fixture and update `chat_app` fixture in `backend/tests/conftest.py`

## 5. Chat Integration

- [x] 5.1 Add `_load_history()` to `ChatService` in `backend/app/services/chat.py` — load RECEIVED + COMPLETE messages only, ordered by `created_at`
- [x] 5.2 Add `_do_rewrite()` to `ChatService` in `backend/app/services/chat.py` — call rewrite service, persist `rewritten_query` on user message
- [x] 5.3 Insert rewrite step into `stream_answer()` in `backend/app/services/chat.py` — call `_do_rewrite()` before retrieval, pass rewritten query to `retrieval_service.search()`
- [x] 5.4 Insert rewrite step into `answer()` in `backend/app/services/chat.py` — call `_do_rewrite()` before retrieval, pass rewritten query to `retrieval_service.search()`

## 6. Integration Tests

- [x] 6.1 Add `rewriting_chat_app` and `rewriting_chat_client` fixtures to `backend/tests/integration/test_chat_sse.py` — real `QueryRewriteService` backed by mock LLM returning predictable rewritten query
- [x] 6.2 Add `test_first_message_no_rewrite` to `backend/tests/integration/test_chat_sse.py` — verify `rewritten_query` is NULL when no history exists
- [x] 6.3 Add `test_second_message_rewrite_persisted` to `backend/tests/integration/test_chat_sse.py` — verify `rewritten_query` is populated in DB for second message
- [x] 6.4 Add `test_retrieval_called_with_rewritten_query` to `backend/tests/integration/test_chat_sse.py` — verify `retrieval_service.search()` receives the rewritten query, not the original
- [x] 6.5 Add `test_llm_prompt_uses_original_query` to `backend/tests/unit/test_chat_streaming.py` — verify `build_chat_prompt()` receives the original user text (not the rewritten query) when rewrite occurs; this is the D10 contract

## 7. Final Review

- [x] 7.1 Self-review all changes against `docs/development.md`
- [x] 7.2 Run full test suite and verify all tests pass
- [x] 7.3 Verify migration applies cleanly on fresh DB (`alembic downgrade base && alembic upgrade head`)
