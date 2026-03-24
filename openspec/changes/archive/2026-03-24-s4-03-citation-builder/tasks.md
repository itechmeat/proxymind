## 1. Configuration

- [x] 1.1 Add `max_citations_per_response` setting to `backend/app/core/config.py` (default 5, ge=1) with unit tests in `backend/tests/unit/test_config.py`

## 2. CitationService

- [x] 2.1 Create `backend/tests/unit/test_citation_service.py` — unit tests for marker extraction, deduplication, max truncation, text citation formatting, invalid index handling, missing source handling, to_dict structure
- [x] 2.2 Create `backend/app/services/citation.py` — SourceInfo dataclass, Citation dataclass with to_dict(), CitationService.extract() static method, \_build_text_citation() helper, regex `\[source:(\d+)\]`

## 3. Prompt Builder

- [x] 3.1 Update `backend/tests/unit/test_prompt_builder.py` — tests for citation instructions presence/absence, new chunk format with title/anchor, score not exposed, backward compat when source_map=None
- [x] 3.2 Update `backend/app/services/prompt.py` — add source_map parameter (default None), CITATION_INSTRUCTIONS block in system prompt, \_format_chunk_header() with title/anchor from source_map, legacy format fallback when source_map is None

## 4. Stream Event Type and SSE Serialization

- [x] 4.1 Add `ChatStreamCitations` dataclass to `backend/app/services/chat.py` alongside existing event types, update `ChatStreamEvent` union type
- [x] 4.2 Add `ChatStreamCitations` serialization branch in `format_event()` in `backend/app/api/chat.py` — use `return _format_sse("citations", ...)`, import ChatStreamCitations

## 5. Chat Service Wiring

- [x] 5.1 Update `_chunk` helper in `backend/tests/unit/test_chat_streaming.py` to accept anchor keyword args (anchor_page, anchor_chapter, anchor_section, anchor_timecode)
- [x] 5.2 Update `_make_service` helper in `backend/tests/unit/test_chat_streaming.py` to accept and pass through `max_citations_per_response` parameter
- [x] 5.3 Add test `test_stream_answer_emits_citations_event` to `backend/tests/unit/test_chat_streaming.py` — verify citations event emitted with correct data, verify event order (meta → tokens → citations → done)
- [x] 5.4 Add `_load_source_map()` method to ChatService in `backend/app/services/chat.py` — batch query sources by IDs, filter deleted_at IS NULL, return dict[UUID, SourceInfo]
- [x] 5.5 Add `max_citations_per_response` parameter to ChatService constructor in `backend/app/services/chat.py`
- [x] 5.6 Wire citations into `stream_answer()` in `backend/app/services/chat.py` — call \_load_source_map after retrieval, pass source_map to build_chat_prompt, extract citations after LLM stream, persist to message.citations, yield ChatStreamCitations before done
- [x] 5.7 Update `backend/app/api/dependencies.py` — pass `max_citations_per_response` from settings to ChatService
- [x] 5.8 Update `backend/tests/conftest.py` — add `max_citations_per_response=5` to chat_app fixture settings SimpleNamespace

## 6. Idempotent Replay

- [x] 6.1 Add test `test_idempotent_replay_includes_citations_event` to `backend/tests/unit/test_chat_streaming.py`
- [x] 6.2 Update `_replay_complete()` in `backend/app/services/chat.py` — reconstruct Citation objects from Message.citations JSONB and yield ChatStreamCitations between content and done

## 7. API Schemas

- [x] 7.1 Add `AnchorResponse` and `CitationResponse` Pydantic schemas to `backend/app/api/chat_schemas.py`
- [x] 7.2 Add `citations: list[CitationResponse] | None = None` field to `MessageInHistory` and `MessageResponse` in `backend/app/api/chat_schemas.py`

## 8. Documentation

- [x] 8.1 Update citation protocol in `docs/spec.md` — change `[source_id:42]` to `[source:N]` ordinal format
- [x] 8.2 Update citation protocol in `docs/rag.md` — change `[source_id:N]` to `[source:N]` ordinal format

## 9. Integration Testing

- [x] 9.1 Add `test_sse_stream_includes_citations_event` to `backend/tests/integration/test_chat_sse.py` — full SSE flow: create session, send message, verify citations event present between tokens and done, verify structure
- [x] 9.2 Add `test_session_history_includes_citations` to `backend/tests/integration/test_chat_sse.py` — send message with citations, then GET /api/chat/sessions/:id, verify assistant message has `citations` as non-empty list with correct CitationResponse structure
- [x] 9.3 Add `test_session_history_citations_null_vs_empty` to `backend/tests/integration/test_chat_sse.py` — verify user message has `citations: null`, COMPLETE assistant with no markers has `citations: []`
- [ ] 9.4 Run full test suite (`cd backend && python -m pytest tests/ -v --timeout=60`) and verify all tests pass

## 10. Verification

- [x] 10.1 Re-read `docs/development.md` and self-review all changes against it
- [x] 10.2 Verify no package versions below minimums in `docs/spec.md`
