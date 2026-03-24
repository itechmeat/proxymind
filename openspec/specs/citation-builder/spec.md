## Purpose

Citation marker extraction from LLM output, source metadata resolution (URL/text), text citation formatting, prompt citation instructions, and citation object structure. Introduced by S4-03.

---

### Requirement: Citation marker format

The LLM SHALL reference sources using `[source:N]` markers where N is a 1-based ordinal index corresponding to the chunk position in the prompt context. The marker format SHALL match the regex `\[source:(\d+)\]`.

#### Scenario: LLM output contains valid citation markers

- **WHEN** the LLM generates text containing `[source:1]` and `[source:3]`
- **THEN** each marker SHALL match the regex `\[source:(\d+)\]`
- **AND** the extracted indices SHALL be `1` and `3`

#### Scenario: Markers do not collide with Markdown links

- **WHEN** the LLM output contains `[some text](http://example.com)` alongside `[source:1]`
- **THEN** only `[source:1]` SHALL be recognized as a citation marker
- **AND** the Markdown link SHALL NOT be parsed as a citation

---

### Requirement: Prompt citation instructions

When retrieved chunks are provided with a non-null `source_map`, the system prompt SHALL include a citation instructions block telling the LLM to use `[source:N]` markers. The citation instructions SHALL NOT include a numeric citation limit (the backend enforces the limit). When no chunks are provided or `source_map` is `None`, citation instructions SHALL be omitted from the system prompt.

#### Scenario: Citation instructions present with chunks and source_map

- **WHEN** `build_chat_prompt()` is called with a non-empty `chunks` list and a non-null `source_map`
- **THEN** the system prompt SHALL contain a citation instructions block that instructs the LLM to use `[source:N]` markers
- **AND** the instructions SHALL NOT contain any numeric citation limit (e.g., "at most 5")

#### Scenario: Citation instructions omitted without chunks

- **WHEN** `build_chat_prompt()` is called with an empty `chunks` list
- **THEN** the system prompt SHALL NOT contain citation instructions

#### Scenario: Citation instructions omitted without source_map

- **WHEN** `build_chat_prompt()` is called with a non-empty `chunks` list but `source_map` is `None`
- **THEN** the system prompt SHALL NOT contain citation instructions

---

### Requirement: Prompt chunk format

Retrieved chunks SHALL be formatted in the prompt as `[Source N] (title: "{title}", chapter: "{chapter}", page: {page})` using anchor fields from `source_map`. Anchor fields (title, chapter, page, section, timecode) SHALL be included only when non-null. Retrieval confidence score SHALL NOT be exposed to the LLM in the prompt.

#### Scenario: Chunk with title, chapter, and page

- **WHEN** a chunk at index 1 has source title "Clean Architecture", anchor chapter "Chapter 5", and anchor page 42
- **THEN** the prompt SHALL format it as `[source:1] (title: "Clean Architecture", chapter: "Chapter 5", page: 42)` followed by the chunk text content

#### Scenario: Chunk with only title (no anchor metadata)

- **WHEN** a chunk at index 2 has source title "README" and all anchor fields (chapter, page, section, timecode) are null
- **THEN** the prompt SHALL format it as `[source:2] (title: "README")` followed by the chunk text content

#### Scenario: Retrieval score not exposed to LLM

- **WHEN** chunks are formatted for the prompt
- **THEN** the retrieval confidence score SHALL NOT appear anywhere in the formatted chunk text or metadata

---

### Requirement: Citation extraction

After the LLM stream completes, `CitationService` SHALL parse all `[source:N]` markers from the accumulated content. Invalid indices (N < 1 or N > total chunk count) SHALL be silently ignored. Sources referenced by valid indices but not found in `source_map` (e.g., deleted between retrieval and citation building) SHALL be skipped without error.

#### Scenario: Valid markers extracted

- **WHEN** the LLM output is `"According to the research [source:1], this is confirmed by [source:3]."`
- **AND** 4 chunks were provided with indices 1 through 4
- **AND** sources for chunks 1 and 3 exist in `source_map`
- **THEN** `CitationService.extract()` SHALL return 2 citation objects for indices 1 and 3

#### Scenario: Invalid index silently ignored

- **WHEN** the LLM output contains `[source:99]` but only 5 chunks were provided
- **THEN** the marker `[source:99]` SHALL be silently ignored
- **AND** no error SHALL be raised

#### Scenario: Zero index silently ignored

- **WHEN** the LLM output contains `[source:0]`
- **THEN** the marker SHALL be silently ignored (indices are 1-based)

#### Scenario: Source not in source_map skipped

- **WHEN** the LLM output contains `[source:2]` and chunk 2 references a source_id that is not present in `source_map` (e.g., source was deleted)
- **THEN** that citation SHALL be skipped
- **AND** no error SHALL be raised

#### Scenario: No markers in LLM output

- **WHEN** the LLM output contains no `[source:N]` markers
- **THEN** `CitationService.extract()` SHALL return an empty list

---

### Requirement: Citation deduplication

Multiple chunks from the same source SHALL produce one citation entry after deduplication. Anchor metadata for the deduplicated citation SHALL be taken from the first-referenced chunk (the chunk whose `[source:N]` marker appears earliest in the content).

#### Scenario: Two chunks from same source deduplicated

- **WHEN** the LLM output contains `[source:1]` and `[source:3]`
- **AND** chunks 1 and 3 both belong to the same source (same `source_id`)
- **THEN** `CitationService.extract()` SHALL return one citation entry for that source
- **AND** the anchor metadata SHALL be taken from chunk 1 (first-referenced)

#### Scenario: Chunks from different sources not deduplicated

- **WHEN** the LLM output contains `[source:1]` and `[source:2]`
- **AND** chunks 1 and 2 belong to different sources
- **THEN** `CitationService.extract()` SHALL return two distinct citation entries

---

### Requirement: Max citations limit

Citations SHALL be truncated to `max_citations_per_response` (default 5, configurable) after deduplication. Truncation order SHALL preserve citations by their order of first appearance in the content.

#### Scenario: Citations truncated to max limit

- **WHEN** the LLM output references 8 unique sources (after deduplication)
- **AND** `max_citations_per_response` is 5
- **THEN** `CitationService.extract()` SHALL return exactly 5 citations
- **AND** the 5 returned citations SHALL be the first 5 by order of first appearance in the content

#### Scenario: Citations below max limit not truncated

- **WHEN** the LLM output references 3 unique sources (after deduplication)
- **AND** `max_citations_per_response` is 5
- **THEN** `CitationService.extract()` SHALL return all 3 citations

---

### Requirement: Text citation format

Every citation SHALL include a `text_citation` string regardless of whether a URL is available. The `text_citation` SHALL be assembled from available anchor fields using the following template:

- Base: `"{title}"`
- If `chapter` is non-null: append `, {chapter}` (raw value — Docling stores the full heading, e.g., "Chapter 5" or "Introduction")
- If `section` is non-null and `chapter` is absent: append `, {section}`
- If `page` is non-null: append `, p. {page}`
- If `timecode` is non-null: append ` at {timecode}`

Fields with null values SHALL be omitted from the text citation.

#### Scenario: PDF with chapter and page

- **WHEN** a citation has title "Clean Architecture", chapter "Chapter 5", page 42, section null, timecode null
- **THEN** `text_citation` SHALL be `"Clean Architecture", Chapter 5, p. 42`

#### Scenario: Audio with timecode

- **WHEN** a citation has title "Podcast Episode 12", chapter null, section null, page null, timecode "01:23:45"
- **THEN** `text_citation` SHALL be `"Podcast Episode 12" at 01:23:45`

#### Scenario: Document with section but no chapter

- **WHEN** a citation has title "Design Patterns", chapter null, section "Observer", page null, timecode null
- **THEN** `text_citation` SHALL be `"Design Patterns", Observer`

#### Scenario: Source with no anchor metadata

- **WHEN** a citation has title "README", and all anchor fields (chapter, page, section, timecode) are null
- **THEN** `text_citation` SHALL be `"README"`

#### Scenario: Source with both chapter and section

- **WHEN** a citation has title "Book Title", chapter "3", section "Intro", page 10, timecode null
- **THEN** `text_citation` SHALL be `"Book Title", 3, p. 10`
- **AND** the section SHALL be omitted because chapter is present

---

### Requirement: Citation object structure

Each citation object returned by `CitationService` SHALL contain the following fields:

- `index` — int, 1-based ordinal as referenced in the LLM content
- `source_id` — UUID of the source document
- `source_title` — str, title of the source document
- `source_type` — str, type of the source (e.g., "pdf", "docx", "audio")
- `url` — str or null, public URL of the source (null for offline sources)
- `anchor` — dict with keys `page` (int|null), `chapter` (str|null), `section` (str|null), `timecode` (str|null)
- `text_citation` — str, human-readable text citation (always present)

#### Scenario: Citation object with URL

- **WHEN** a citation is built for a source with title "Python Docs", source_type "html", public_url "https://docs.python.org", and anchor page 5
- **THEN** the citation object SHALL have `source_title` = "Python Docs", `source_type` = "html", `url` = "https://docs.python.org", `anchor` = `{"page": 5, "chapter": null, "section": null, "timecode": null}`, and a non-empty `text_citation`

#### Scenario: Citation object without URL

- **WHEN** a citation is built for a source with title "Clean Architecture", source_type "pdf", public_url null, chapter "Chapter 5", and page 42
- **THEN** the citation object SHALL have `url` = null
- **AND** `text_citation` SHALL be `"Clean Architecture", Chapter 5, p. 42`

---

### Requirement: Source metadata loading

The system SHALL batch-load source metadata (title, public_url, source_type) from PostgreSQL by unique `source_id` values extracted from retrieved chunks. The query SHALL include only non-deleted sources (`deleted_at IS NULL`). The result SHALL be a `source_map` dict mapping `UUID` to `SourceInfo`. The batch load SHALL execute once after retrieval, and the resulting `source_map` SHALL be reused by both the prompt builder and the citation service.

#### Scenario: Batch load excludes deleted sources

- **WHEN** retrieved chunks reference source_ids `[A, B, C]`
- **AND** source B has `deleted_at` set (soft-deleted)
- **THEN** `source_map` SHALL contain entries for A and C only
- **AND** source B SHALL NOT appear in `source_map`

#### Scenario: Batch load with no matching sources

- **WHEN** retrieved chunks reference source_ids that all have `deleted_at` set
- **THEN** `source_map` SHALL be an empty dict

#### Scenario: Source map reused by prompt builder and citation service

- **WHEN** `source_map` is loaded after retrieval
- **THEN** the same `source_map` instance SHALL be passed to both `build_chat_prompt()` and `CitationService.extract()`

---

### Requirement: Content storage with raw markers

The raw LLM output with `[source:N]` markers SHALL be stored as-is in `Message.content`. The system SHALL NOT modify, strip, or replace markers in the stored content.

#### Scenario: Raw markers preserved in Message.content

- **WHEN** the LLM generates `"See the study [source:1] for details."`
- **THEN** `Message.content` SHALL be stored as `"See the study [source:1] for details."`
- **AND** the `[source:1]` marker SHALL NOT be replaced or removed

---

### Requirement: Citation persistence

Resolved citations SHALL be stored in the `Message.citations` JSONB field as an array of citation objects. Each citation object in the array SHALL conform to the citation object structure defined in this spec. When no citations are produced (empty array), the field SHALL store an empty JSON array `[]`.

#### Scenario: Citations persisted to JSONB

- **WHEN** the LLM output produces 2 resolved citations
- **THEN** `Message.citations` SHALL contain a JSON array with 2 citation objects
- **AND** each object SHALL include `index`, `source_id`, `source_title`, `source_type`, `url`, `anchor`, and `text_citation`

#### Scenario: No citations persisted as empty array

- **WHEN** the LLM output contains no citation markers
- **THEN** `Message.citations` SHALL be stored as `[]`

---

### Requirement: Rendering contract

The backend SHALL NOT strip `[source:N]` markers from `Message.content` or from SSE `token` event payloads. Marker-to-citation rendering is a frontend concern (S5-02). Raw markers MAY be visible to API consumers until frontend implementation.

#### Scenario: Token events contain raw markers

- **WHEN** the LLM generates a token chunk containing `[source:1]`
- **THEN** the SSE `token` event payload SHALL include `[source:1]` as-is
- **AND** the backend SHALL NOT replace or strip it

#### Scenario: History API returns raw markers in content

- **WHEN** `GET /api/chat/sessions/:id` returns message history
- **THEN** the `content` field of assistant messages SHALL contain raw `[source:N]` markers as stored
- **AND** the `citations` field SHALL contain the structured citation array for frontend rendering

---

### Requirement: Citation configuration

`max_citations_per_response` SHALL be configurable via the `Settings` class in `backend/app/core/config.py`. The default value SHALL be `5`. The minimum allowed value SHALL be `1`. The setting SHALL be configurable via environment variable `MAX_CITATIONS_PER_RESPONSE`.

#### Scenario: Default max_citations_per_response

- **WHEN** no `MAX_CITATIONS_PER_RESPONSE` environment variable is set
- **THEN** `max_citations_per_response` SHALL default to `5`

#### Scenario: Custom max_citations_per_response

- **WHEN** `MAX_CITATIONS_PER_RESPONSE=10` is set in the environment
- **THEN** `max_citations_per_response` SHALL be `10`

#### Scenario: Minimum value enforced

- **WHEN** `max_citations_per_response` is configured
- **THEN** the value SHALL be at least `1`
