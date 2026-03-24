# S4-03: Citation Builder — Design Spec

## Story

> LLM returns `[source:N]`, backend substitutes URL (online) or text citation (offline). Anchor metadata from Qdrant payload. SSE event type=citations.

## Approach

**Post-stream citation extraction.** After the LLM finishes streaming, a stateless `CitationService` parses citation markers from the accumulated content, maps them to source metadata, and emits a single `citations` SSE event before `done`.

**Why this approach:**

- Simple regex parse on complete text — no stateful stream parsing
- Clean separation: LLM generates markers, backend resolves them
- Follows the existing async-generator SSE pipeline from S4-02
- Original LLM output stored as-is (for audit and evals)
- Structured citations stored separately in JSONB (for frontend rendering)

**Rejected alternatives:**

- **Inline stream parsing:** Markers can split across tokens (`[sou` + `rce:1]`), requiring a stateful parser. Complexity for negligible UX gain — citations render as a collapsed block under the message anyway.
- **LLM generates full URLs:** Violates citation protocol (spec.md). LLMs hallucinate URLs. Backend-only URL resolution eliminates this class of errors.
- **Replace markers in stored content:** Loses the raw LLM output boundary, complicates audit/evals, and frontend still needs structured citation data.

## Design Decisions

| #   | Decision                            | Choice                                                                | Rationale                                                                                                                                                                                                                                                                   |
| --- | ----------------------------------- | --------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Citation marker format              | `[source:N]` (N = ordinal 1-based index)                              | Unambiguous regex `\[source:(\d+)\]`. No collision with Markdown links `[text](url)` or numbered lists `[1]`. Short ordinal indices reduce token waste vs UUIDs and eliminate LLM transcription errors.                                                                     |
| D2  | Source numbering in prompt          | `[source:1]`, `[source:2]`... (same format as citation markers)       | Chunk headers use the exact same `[source:N]` format as citation instructions. This ensures the LLM sees a direct correlation between context labels and the markers it should produce.                                                                                     |
| D3  | Citations SSE timing                | Single event after stream completion, before `done`                   | All markers known, one batch event. Perplexity-style collapsed sources block doesn't benefit from progressive rendering. Avoids async source lookup during stream.                                                                                                          |
| D4  | Content storage                     | Original LLM output with markers preserved                            | Raw content enables: audit trail of what LLM actually generated, eval pipeline on unmodified output, idempotent replay. Frontend uses `citations` array for rendering.                                                                                                      |
| D5  | Citation data storage               | `Message.citations` JSONB (already exists, currently NULL)            | No migration needed. Structured array alongside raw content.                                                                                                                                                                                                                |
| D6  | Source metadata loading             | Batch PG query by unique source_ids after retrieval                   | One `SELECT id, title, public_url, source_type FROM sources WHERE id = ANY($1)`. Avoids Qdrant payload denormalization (which would require reindex on Source update). Query runs once before prompt assembly, result reused by both prompt builder and citation builder.   |
| D7  | Offline citation format             | Template: `"{title}", {chapter}, {section}, p. {page}" at {timecode}` | Assembles from available anchor fields, omits missing ones. Chapter/section values are stored as-is from Docling (e.g., "Chapter 5", "Introduction") — no prefix added to avoid duplication.                                                                                |
| D8  | Invalid marker handling             | Silently ignore                                                       | Out-of-range index → skip. Source deleted between retrieval and citation → skip. Zero citations → empty array, event still emitted.                                                                                                                                         |
| D9  | Deduplication                       | By source_id, keep first occurrence                                   | Multiple chunks from the same source → one citation entry. Anchor metadata from the first-referenced chunk (most relevant to the statement).                                                                                                                                |
| D10 | Max citations                       | `max_citations_per_response` setting (default 5)                      | From rag.md defaults. Applied after deduplication, truncates by order of appearance.                                                                                                                                                                                        |
| D11 | Score in prompt                     | Removed                                                               | LLM should not see retrieval confidence scores — they can bias response generation (over-relying on high-score chunks, ignoring low-score but relevant ones).                                                                                                               |
| D12 | `text_citation` field               | Always present (both online and offline)                              | The story says "URL (online) or text citation (offline)." We intentionally provide `text_citation` for all sources — it serves as accessible fallback text, tooltip content, and screen reader label even when `url` is present. `url` is nullable; `text_citation` is not. |
| D13 | `max_citations_per_response` config | Add to Settings class                                                 | Currently defined only in rag.md defaults. Must be added to `backend/app/core/config.py` Settings with default 5.                                                                                                                                                           |
| D14 | Prompt wording for max citations    | Omit numeric limit from LLM instructions                              | Telling the LLM "use at most 5 citations" can cause it to aim for 5. Instead, instruct "cite only the most relevant sources." The backend enforces the numeric limit.                                                                                                       |

## Data Flow

```
Retrieval
    │
    ▼
RetrievedChunk[] ──────────────────────────────────┐
    │                                               │
    ├─ unique source_ids                            │
    ▼                                               │
PG batch load ─► source_map{UUID→SourceInfo}        │
    │                                               │
    ▼                                               │
Prompt Builder (chunks + source_map + persona)      │
    │                                               │
    ▼                                               │
LLM stream ─► content_buffer                        │
    │                                               │
    ▼                                               │
CitationService.extract(content, chunks, source_map)│
    │                                          ◄────┘
    ▼
Citation[] ─┬─► SSE "citations" event
            ├─► Message.citations (JSONB)
            └─► SSE "done" event
```

## SSE Protocol

### Updated Event Sequence

```
event: meta
data: {"message_id":"...","session_id":"...","snapshot_id":"..."}

event: token
data: {"content":"According to"}

event: token
data: {"content":" the research [source:1], ..."}

... more tokens ...

event: citations
data: {"citations":[{"index":1,"source_id":"550e8400-...","source_title":"Clean Architecture","source_type":"pdf","url":null,"anchor":{"page":42,"chapter":"Chapter 5","section":null,"timecode":null},"text_citation":"\"Clean Architecture\", Chapter 5, p. 42"}]}

event: done
data: {"token_count_prompt":1234,"token_count_completion":256,"model_name":"...","retrieved_chunks_count":3}
```

### Edge Cases

| Scenario                                                      | Behavior                                                     |
| ------------------------------------------------------------- | ------------------------------------------------------------ |
| No markers in LLM output                                      | `citations` event with empty array                           |
| Marker with invalid index (e.g., `[source:99]` with 5 chunks) | Marker ignored, not included in citations                    |
| Source deleted between retrieval and citation building        | Citation for that source skipped                             |
| `partial` / `failed` message                                  | No citation extraction, no `citations` event                 |
| Refusal (insufficient context)                                | No citation extraction, no `citations` event                 |
| Idempotent replay (COMPLETE message)                          | `citations` event replayed from `Message.citations` DB field |
| Multiple chunks from same source                              | One citation entry, anchor from first-referenced chunk       |

## Components

### 1. CitationService (`backend/app/services/citation.py`)

New file. Stateless service, no DB access.

**Responsibilities:**

- Parse `[source:N]` markers from content via regex
- Map ordinal indices to RetrievedChunk entries
- Build Citation objects with source metadata and anchor info
- Generate text_citation strings for offline sources
- Enforce `max_citations` limit

**Interface:**

```
extract(
    content: str,
    chunks: list[RetrievedChunk],
    source_map: dict[UUID, SourceInfo],
    max_citations: int,
) -> list[Citation]
```

**Citation dataclass fields:**

- `index: int` — ordinal (1-based) as referenced in content
- `source_id: UUID`
- `source_title: str`
- `source_type: str`
- `url: str | None` — public_url from Source, null for offline
- `anchor: dict` — `{page, chapter, section, timecode}` (nullable fields)
- `text_citation: str` — always present, human-readable

**SourceInfo dataclass:**

- `id: UUID`
- `title: str`
- `public_url: str | None`
- `source_type: str`

### 2. Prompt Builder Changes (`backend/app/services/prompt.py`)

**Updated signature:**

```
build_chat_prompt(
    query: str,
    chunks: list[RetrievedChunk],
    persona: PersonaContext,
    source_map: dict[UUID, SourceInfo] | None = None,
) -> list[dict[str, str]]
```

`source_map` defaults to `None` for backward compatibility with the existing non-streaming `answer()` method (used by tests and future internal calls like query rewriting in S4-04). When `None`, chunks render in the legacy format without titles/anchors, and citation instructions are omitted.

**Citation instructions block** (added to system prompt when chunks are non-empty):

```
## Citation Instructions
When your answer is based on the knowledge context below, cite sources
using [source:N] where N is the source number.
- Place citations inline, immediately after the relevant statement.
- Do not generate URLs or links. Only use source numbers provided.
- Cite only the most relevant sources for knowledge-based facts.
- Do not cite inferences or small talk.
```

**Chunk format change:**

```
[source:1] (title: "Clean Architecture", chapter: "Chapter 5", page: 42)
<chunk text content>
```

Anchor fields included only when non-null. Title from `source_map`.

### 3. Source Repository Extension

New method on the existing source repository or a lightweight query helper:

```
async def get_sources_by_ids(ids: list[UUID]) -> dict[UUID, SourceInfo]
```

Single query: `SELECT id, title, public_url, source_type FROM sources WHERE id = ANY($1) AND deleted_at IS NULL`

Note: Source uses `SoftDeleteMixin` with `deleted_at` timestamp, not a status field for deletion filtering.

### 4. Chat Service Changes (`backend/app/services/chat.py`)

**`stream_answer()` modifications:**

After retrieval, before prompt assembly:

1. Batch load source metadata: `source_map = await source_repo.get_sources_by_ids(source_ids)`
2. Pass `source_map` to `build_chat_prompt()`

After LLM stream completion (before `done` event):

1. `content = "".join(content_buffer)`
2. `citations = citation_service.extract(content, chunks, source_map, max_citations)`
3. `assistant_message.citations = [c.to_dict() for c in citations]`
4. Yield `ChatStreamCitations(citations=citations)`
5. Commit and yield `ChatStreamDone(...)` as before

**Idempotent replay:** When replaying a COMPLETE message, reconstruct `ChatStreamCitations` from `Message.citations` field and include in replay stream.

### 5. Stream Event Type (`backend/app/services/chat.py`) + SSE Serialization (`backend/app/api/chat.py`)

**Important architectural boundary:** All stream event dataclasses (`ChatStreamMeta`, `ChatStreamToken`, `ChatStreamDone`, `ChatStreamError`) are defined in `backend/app/services/chat.py` (the service layer). The API layer (`backend/app/api/chat.py`) only serializes them to SSE wire format. The new `ChatStreamCitations` follows the same pattern.

New dataclass in `backend/app/services/chat.py` (alongside existing stream events):

```python
@dataclass(slots=True, frozen=True)
class ChatStreamCitations:
    citations: list[Citation]
```

Add to `ChatStreamEvent` union type in `backend/app/services/chat.py`.

In `backend/app/api/chat.py`, add a serialization branch in `format_event()` that converts `ChatStreamCitations` to SSE `citations` event with JSON payload `{"citations": [<Citation.to_dict()>...]}`.

Also update `_replay_complete()` method in `backend/app/services/chat.py` to yield `ChatStreamCitations` from `Message.citations` DB field (currently replay only yields `meta`, `token`, `done`).

### 6. Chat Schemas (`backend/app/api/chat_schemas.py`)

Add `citations` field to both `MessageResponse` and `MessageInHistory` schemas (the latter is used by `GET /api/chat/sessions/:id` via `SessionWithMessagesResponse`):

```
citations: list[CitationResponse] | None
```

`CitationResponse` Pydantic schema mirrors the Citation dataclass fields.

## Rendering Contract: Raw Markers

`[source:N]` markers appear in three places. Each has a defined rendering responsibility:

| Surface                                        | Who sees raw markers?                            | Who renders them? | Behavior                                                                                                                                                                                                                                                         |
| ---------------------------------------------- | ------------------------------------------------ | ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Live SSE stream** (`token` events)           | Frontend receives tokens containing `[source:N]` | Frontend (S5-02)  | Frontend strips or replaces markers inline using the `citations` array received in the subsequent `citations` event. During streaming (before `citations` arrives), markers may briefly appear as raw text — this is acceptable and matches Perplexity behavior. |
| **History API** (`GET /sessions/:id`)          | `Message.content` contains raw markers           | Frontend (S5-02)  | Frontend uses `MessageInHistory.citations` array to find-and-replace `[source:N]` with rendered citation components.                                                                                                                                             |
| **Idempotent replay** (SSE replay of COMPLETE) | Same as live stream                              | Frontend (S5-02)  | Same as live stream — `citations` event follows the replayed content.                                                                                                                                                                                            |

**Backend does not strip markers.** Raw LLM output is stored and transmitted as-is. This preserves the audit trail, enables eval pipelines on unmodified output, and keeps the backend stateless with respect to rendering. All marker→citation rendering is a frontend concern delivered in S5-02.

**Until S5-02 is implemented:** Users interacting directly with the API (curl, tests) will see raw `[source:N]` markers in the text. The `citations` SSE event and `Message.citations` field provide the structured data needed to resolve them.

## Text Citation Format

Template assembly from available fields:

```
base:      "{title}"
+ chapter: ", {anchor_chapter}"            (if non-null, raw value from Docling e.g. "Chapter 5")
+ section: ", {anchor_section}"            (if non-null)
+ page:    ", p. {anchor_page}"            (if non-null)
+ timecode:", at {anchor_timecode}"        (if non-null)
```

Examples:

- `"Clean Architecture", Chapter 5, p. 42` — PDF with page and chapter
- `"Podcast Episode 12" at 01:23:45` — audio with timecode
- `"Design Patterns", Observer` — DOCX with section heading
- `"README"` — source with no anchor metadata

Timecode values are stored and displayed as-is from source metadata (typically "HH:MM:SS" from Docling audio/video processing). CitationService does not validate or reformat timecodes.

## Testing Strategy

### CI (deterministic, no external providers)

**Unit tests for CitationService:**

- Happy path: content with markers → correct Citation list
- Multiple markers to same source → deduplication
- Invalid index → ignored
- No markers → empty list
- Max citations truncation
- Text citation formatting for various anchor combinations
- Source not in source_map → skipped

**Unit tests for prompt builder:**

- Citation instructions present when chunks non-empty
- Citation instructions absent when chunks empty
- Chunk format includes title and anchor from source_map
- Score not exposed to LLM

**Integration tests:**

- Full stream flow: mock LLM returns text with markers → verify `citations` SSE event content
- Citations persisted in `Message.citations` → verify via `GET /api/chat/sessions/:id`
- Idempotent replay includes citations event
- Refusal/failure paths → no citations event

### No migration required

`Message.citations` JSONB column already exists (created in S1-02, currently NULL).

## Configuration

| Parameter                    | Source                                  | Default | Description                                                              |
| ---------------------------- | --------------------------------------- | ------- | ------------------------------------------------------------------------ |
| `max_citations_per_response` | Settings (`backend/app/core/config.py`) | 5       | Max citations per response after dedup. Must be added to Settings class. |

## Files Changed

| File                                          | Change                                                                                                                                                                                            |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/app/services/citation.py`            | **New.** CitationService + Citation + SourceInfo dataclasses                                                                                                                                      |
| `backend/app/services/prompt.py`              | Add citation instructions, change chunk format, accept source_map                                                                                                                                 |
| `backend/app/services/chat.py`                | Add `ChatStreamCitations` dataclass + union type, `_load_source_map()` method, wire citation service into `stream_answer()`, emit citations event, persist citations, update `_replay_complete()` |
| `backend/app/api/chat.py`                     | Add `ChatStreamCitations` serialization branch in `format_event()`                                                                                                                                |
| `backend/app/api/chat_schemas.py`             | Add `CitationResponse` schema, add `citations` to both `MessageResponse` and `MessageInHistory`                                                                                                   |
| `backend/app/core/config.py`                  | Add `max_citations_per_response: int = 5` to Settings                                                                                                                                             |
| `docs/spec.md`                                | Update citation protocol: `[source_id:42]` → `[source:N]` ordinal format                                                                                                                          |
| `docs/rag.md`                                 | Update citation protocol: `[source_id:N]` → `[source:N]` ordinal format                                                                                                                           |
| `backend/tests/unit/test_citation_service.py` | **New.** Unit tests for citation extraction                                                                                                                                                       |
| `backend/tests/unit/test_prompt_builder.py`   | Update for new prompt format (existing file)                                                                                                                                                      |
| `backend/tests/unit/test_chat_streaming.py`   | Add citation-related streaming tests (existing file)                                                                                                                                              |
| `backend/tests/integration/test_chat_sse.py`  | Add integration test for SSE citations event (existing file)                                                                                                                                      |
