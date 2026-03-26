## Story

**S4-05: Promotions + context assembly** (Phase 4: Dialog Expansion)

**Verification criteria:** promo with expired date not in prompt; all layers present in correct order; when budget exceeded retrieval is trimmed; `content_type_spans` persisted in messages and returned via `GET /api/chat/sessions/:id` (existing `content_types` field in the response schema).

**Stable behavior requiring test coverage:** prompt layer ordering, PROMOTIONS.md parsing and date filtering, retrieval context budget trimming, content type span classification.

## Why

The current prompt builder (`build_chat_prompt`) is a flat function that concatenates persona and retrieval context without structure, token budget management, or promotions support. As the dialogue circuit grows (S4-05 promotions, S4-06 conversation memory), this monolithic approach becomes unmaintainable and untestable. The twin needs to inject promotional content from `config/PROMOTIONS.md` with expiry filtering and priority rules, manage retrieval token budgets, and mark response fragments by content type (fact/inference/promo) for the frontend.

## What Changes

- Add `PromotionsService` that parses `config/PROMOTIONS.md`, filters expired entries, sorts by priority, and selects top-N for injection.
- Replace `build_chat_prompt()` with a `ContextAssembler` class that orchestrates all prompt layers in XML tags: system safety, identity, soul, behavior, promotions, citation instructions, content guidelines, retrieval context, user query.
- Add token budget management for retrieval context (`retrieval_context_budget` setting, default 4096 tokens). Whole chunks are dropped from the tail when budget is exceeded; `min_retrieved_chunks` is a hard override.
- Extract shared `token_counter` module from `query_rewrite.py` for reuse.
- Add heuristic `compute_content_type_spans()` that classifies response sentences as fact (has `[source:N]`), promo (matches promotion keywords), or inference (default). Results stored in `message.content_type_spans` (existing JSONB column).
- Reserve a conversation memory slot (`TODO(S4-06)`) in the assembler layer list.
- Update `ChatService` DI: replace direct `persona_context` injection with `context_assembler`.

## Capabilities

### New Capabilities
- `promotions-parser`: Parsing, date filtering, priority sorting, and selection of promotions from `config/PROMOTIONS.md`
- `context-assembly`: Layered prompt orchestration with XML tags, token budget management, and retrieval trimming
- `content-type-markup`: Heuristic post-processing to classify response fragments as fact/inference/promo

### Modified Capabilities
- `chat-dialogue`: ChatService uses `ContextAssembler` instead of `build_chat_prompt()`; adds content type span computation after LLM response

## Impact

- **Backend services:** New files `promotions.py`, `context_assembler.py`, `token_counter.py`, `content_type.py`. Modified `chat.py`, `prompt.py`, `config.py`, `main.py`, `dependencies.py`.
- **Tests:** New test files for all 4 new modules. Migration of existing tests in `test_chat_service.py`, `test_chat_streaming.py`, `test_prompt_builder.py`, `test_app_main.py`, `conftest.py`, `test_chat_sse.py` to use `ContextAssembler` DI.
- **Config:** 3 new settings (`retrieval_context_budget`, `max_promotions_per_response`, `promotions_file_path`).
- **No DB migrations.** Uses existing `content_type_spans` JSONB column on `messages` table.
- **No new API endpoints.** Prompt assembly is internal. `content_type_spans` are stored in the existing `content_type_spans` JSONB column and returned via the existing `GET /api/chat/sessions/:id` endpoint's `content_types` field (already defined in `docs/spec.md`).
