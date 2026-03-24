## Story

**S4-03: Citation builder** (Phase 4: Dialog Expansion)

- **Outcome:** responses contain verified source references
- **Verification:** response with citation → correct URL; offline source → "Book, chapter N, p. M"
- **Stable behavior requiring tests:** CitationService extraction logic, prompt builder citation instructions, SSE citations event emission, idempotent replay with citations, session history with citations

## Why

Chat responses reference knowledge chunks but provide no verifiable source attribution. Users cannot trace statements back to original documents. The citation builder closes this gap by having the LLM mark sources with `[source:N]` ordinal markers, which the backend resolves to structured citations with real URLs or text references. This is a prerequisite for the frontend citations display (S5-02) and commercial link integration (S6-01).

## What Changes

- Add `CitationService` — stateless service that parses `[source:N]` markers from LLM output, maps ordinal indices to retrieved chunks, and builds structured citation objects with source metadata and anchor details
- Update prompt builder — add citation instructions to system prompt, change chunk format from raw UUIDs to `[Source N]` with human-readable title/anchor metadata, remove score from LLM-visible context
- Wire citations into streaming pipeline — batch-load source metadata from PG after retrieval, extract citations after LLM stream completes, emit SSE `citations` event before `done`, persist to `Message.citations` JSONB
- Update idempotent replay — include `citations` event when replaying COMPLETE messages from DB
- Add `CitationResponse` schema to chat API — expose citations in session history endpoint
- Add `max_citations_per_response` config setting (default 5)
- Update `docs/spec.md` and `docs/rag.md` — citation protocol now uses `[source:N]` ordinal format

## Capabilities

### New Capabilities
- `citation-builder`: Citation marker extraction, source metadata resolution (URL/text), text citation formatting, SSE citations event, prompt citation instructions

### Modified Capabilities
- `sse-streaming`: Add `citations` event emission (currently reserved but not emitted), update replay to include citations, add `ChatStreamCitations` event type to union
- `chat-dialogue`: Add `citations` field to `MessageInHistory` and `MessageResponse` schemas, batch-load source metadata in chat flow

## Impact

- **Backend services:** `citation.py` (new), `prompt.py`, `chat.py`, `llm.py` (no change)
- **API layer:** `api/chat.py` (SSE serialization), `chat_schemas.py` (new schema)
- **Config:** `config.py` (new setting), `dependencies.py` (pass-through)
- **Test fixtures:** `conftest.py` (add `max_citations_per_response` to `chat_app` settings)
- **Docs:** `spec.md`, `rag.md` (citation protocol update)
- **No new dependencies.** No database migration (uses existing `Message.citations` JSONB column).
