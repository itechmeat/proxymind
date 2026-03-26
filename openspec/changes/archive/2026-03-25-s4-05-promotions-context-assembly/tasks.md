## 1. Token Counter Module

- [x] 1.1 Create `backend/app/services/token_counter.py` with `estimate_tokens(text) -> int` using `CHARS_PER_TOKEN = 3`
- [x] 1.2 Create `backend/tests/unit/test_token_counter.py` — tests for empty string, short string, unicode, determinism
- [x] 1.3 Migrate `CHARS_PER_TOKEN` import in `backend/app/services/query_rewrite.py` from local constant to `token_counter` module
- [x] 1.4 Run full test suite to verify no regressions

## 2. Promotions Service

- [x] 2.1 Update `config/PROMOTIONS.md` with the structured format (## sections, Priority, Valid from/to, Context, body)
- [x] 2.2 Create `backend/app/services/promotions.py` — `Promotion` dataclass, `PromotionsService` class with `parse()`, `get_active()`, `from_file()` methods
- [x] 2.3 Create `backend/tests/unit/test_promotions.py` — parsing, date filtering, priority sorting, top-N selection, fail-safe on missing/empty file, invalid priority/date handling, empty body handling

## 3. Configuration

- [x] 3.1 Add `retrieval_context_budget`, `max_promotions_per_response`, `promotions_file_path` settings to `backend/app/core/config.py` (using REPO_ROOT pattern for path)
- [x] 3.2 Run tests to verify no regressions from new default settings

## 4. Context Assembler

- [x] 4.1 Create `backend/app/services/context_assembler.py` — `PromptLayer`, `AssembledPrompt` dataclasses, `ContextAssembler` class with layer methods and `assemble()`
- [x] 4.2 Rename `_format_chunk_header` to `format_chunk_header` in `backend/app/services/prompt.py`
- [x] 4.3 Create `backend/tests/unit/test_context_assembler.py` — layer ordering, XML tags, conditional promotions/citations, budget trimming (partial fit, min=0, min=1 override), empty persona, token estimates

## 5. Content Type Spans

- [x] 5.1 Create `backend/app/services/content_type.py` — `ContentTypeSpan` dataclass, `compute_content_type_spans()` function with sentence splitting, citation/promo/inference classification, span merging
- [x] 5.2 Create `backend/tests/unit/test_content_type.py` — citation→fact, promo keywords→promo, plain→inference, fact-over-promo priority, adjacent merging, empty text, full coverage, single keyword below threshold

## 6. Wire Into Chat Pipeline

- [x] 6.1 Initialize `PromotionsService` in `backend/app/main.py` lifespan and store in `app.state`
- [x] 6.2 Add `get_promotions_service()` and `get_context_assembler()` to `backend/app/api/dependencies.py`; update `get_chat_service()` to inject `context_assembler` instead of `persona_context`
- [x] 6.3 Update `ChatService.__init__` in `backend/app/services/chat.py` — replace `persona_context` param with `context_assembler`; add `_persona_context` property; replace `build_chat_prompt()` calls with `context_assembler.assemble()` in both `answer()` and `stream_answer()`
- [x] 6.4 Add `compute_content_type_spans()` call after citation extraction in both `answer()` and `stream_answer()`; persist to `assistant_message.content_type_spans`
- [x] 6.5 Remove `build_chat_prompt()` and `CITATION_INSTRUCTIONS` from `backend/app/services/prompt.py`; keep `format_chunk_header()` and `NO_CONTEXT_REFUSAL`
- [x] 6.6 Update `backend/tests/unit/test_prompt_builder.py` — remove 11 `build_chat_prompt` tests, keep 3 chunk header + refusal tests, fix import
- [x] 6.7 Update `backend/tests/unit/test_chat_service.py` — replace `persona_context` fixture with `context_assembler` in `_make_service()` helper
- [x] 6.8 Update `backend/tests/unit/test_chat_streaming.py` — same as 6.7 plus replace `build_chat_prompt` monkeypatch with assembler-aware approach
- [x] 6.9 Update `backend/tests/unit/test_app_main.py` — add assertion for `app.state.promotions_service` initialization
- [x] 6.10 Update `backend/tests/conftest.py` and `backend/tests/integration/test_chat_sse.py` — add `app.state.promotions_service` setup

## 7. Integration Verification

- [x] 7.1 Run full unit test suite (`pytest tests/unit/ -v`)
- [x] 7.2 Run linter (`ruff check app/ tests/`)
- [x] 7.3 Verify PROMOTIONS.md example parses correctly via Python one-liner
