## 1. Dependencies and Configuration

- [x] 1.1 Add `httpx-sse` to dev dependencies in `backend/pyproject.toml` and run `uv sync`
- [x] 1.2 Add `sse_heartbeat_interval_seconds` (default 15) and `sse_inter_token_timeout_seconds` (default 30) to `Settings` in `backend/app/core/config.py`; write unit tests for defaults and validation
- [x] 1.3 Add `idempotency_key: str | None = None` to `SendMessageRequest` in `backend/app/api/chat_schemas.py`; verify backward compatibility with existing tests

## 2. Database Migration

- [x] 2.1 Add `parent_message_id` (nullable UUID FK to `messages.id`) to Message model in `backend/app/db/models/dialogue.py`
- [ ] 2.2 Generate and apply Alembic migration; verify existing chat tests still pass

## 3. LLM Streaming

- [x] 3.1 Add `LLMToken` and `LLMStreamEnd` dataclasses and `LLMStreamEvent` type alias to `backend/app/services/llm.py`
- [x] 3.2 Implement `LLMService.stream()` method using `litellm.acompletion(stream=True, stream_options={"include_usage": True})`; yields `LLMToken` for each chunk, `LLMStreamEnd` as terminal event
- [x] 3.3 Write unit tests for `stream()` in `backend/tests/unit/test_llm_streaming.py`: normal flow, empty chunks skipped, provider failure, missing usage stats; verify existing `complete()` tests pass

## 4. ChatService Streaming

- [x] 4.1 Add domain event dataclasses (`ChatStreamMeta`, `ChatStreamToken`, `ChatStreamDone`, `ChatStreamError`) and exception classes (`ConcurrentStreamError`, `IdempotencyConflictError`) to `backend/app/services/chat.py`
- [x] 4.2 Update `_persist_message` to accept `parent_message_id` parameter (nullable, backward compatible)
- [x] 4.3 Implement `_check_idempotency()` — lookup user message by idempotency_key, find paired assistant via `parent_message_id`; return replay generator for COMPLETE, raise for STREAMING, allow re-generation for PARTIAL/FAILED
- [x] 4.4 Implement `_check_no_active_stream()` — reject with `ConcurrentStreamError` if any STREAMING message exists in session
- [x] 4.5 Implement `stream_answer()` async generator — pre-stream validation (session, snapshot, idempotency, concurrency, retrieval), then yield meta/token/done/error events; retrieval errors persist FAILED assistant message then raise
- [x] 4.6 Implement `save_partial_on_disconnect()` (→ PARTIAL) and `save_failed_on_timeout()` (→ FAILED)
- [ ] 4.7 Write unit tests in `backend/tests/unit/test_chat_streaming.py`: normal flow, refusal, LLM error, missing session, no snapshot, idempotency replay, concurrent stream guard; verify existing `answer()` tests pass

## 5. SSE Endpoint

- [x] 5.1 Add `get_sse_settings` dependency to `backend/app/api/dependencies.py`
- [x] 5.2 Rewrite `POST /api/chat/messages` in `backend/app/api/chat.py` — return `StreamingResponse` with SSE formatting; pre-stream validation via `__anext__()` pull; heartbeat via `asyncio.wait_for` loop; inter-token timeout with deadline tracking; disconnect via `asyncio.CancelledError`
- [x] 5.3 Update `mock_llm_service` fixture in `backend/tests/conftest.py` — add `stream` mock alongside `complete`; update `chat_app` fixture with SSE settings

## 6. Integration Tests

- [x] 6.1 Write SSE integration tests in `backend/tests/integration/test_chat_sse.py`: full stream flow (verify `retrieved_chunks_count` in `done` event), message persistence (COMPLETE), pre-stream errors (404, 422, 409), retrieval error (500 with FAILED message persisted), idempotency replay, concurrent stream rejection, disconnect → PARTIAL
- [x] 6.2 Update existing tests in `backend/tests/integration/test_chat_api.py` — migrate `POST /messages` assertions from JSON to SSE parsing (`httpx-sse`); update prompt verification from `complete.call_args` to `stream.call_args`

## 7. Final Verification

- [x] 7.1 Run linter (`ruff check . --fix && ruff format .`) and fix any issues
- [ ] 7.2 Run full test suite (`uv run pytest -v`) and confirm all tests pass
- [x] 7.3 Self-review against `docs/development.md`: no mocks outside tests, no stubs, SOLID/KISS/DRY/YAGNI, files under 300 lines
