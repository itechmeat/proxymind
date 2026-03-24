## Purpose

Delta spec for S4-03 Citation Builder: extends session history to include citations in message responses, defines citation/anchor response schemas, and adds source metadata batch loading to the chat flow.

## MODIFIED Requirements

### Requirement: Session history via GET /api/chat/sessions/:id

The system SHALL provide a `GET /api/chat/sessions/{session_id}` endpoint that returns the session with its ordered message history. Messages SHALL be ordered by `created_at` ascending. The response SHALL include `id`, `status`, `channel`, `snapshot_id`, `message_count`, `created_at`, and a `messages` array. Each message in the array SHALL be represented by the `MessageInHistory` schema and SHALL include `id`, `role`, `content`, `status`, `model_name` (for assistant messages), `created_at`, and a `citations` field (`list[CitationResponse] | None`).

`CitationResponse` SHALL contain the following fields:
- `index` — integer, the citation's position number in the response text
- `source_id` — UUID, the knowledge source this citation references
- `source_title` — string, the human-readable title of the source document
- `source_type` — string, the type of the source (e.g., `"pdf"`, `"webpage"`, `"markdown"`)
- `url` — nullable string, the public URL of the source (null when no public URL exists)
- `anchor` — `AnchorResponse`, the location within the source
- `text_citation` — string, human-readable bibliographic reference (e.g., `"Clean Architecture", Chapter 5, p. 42`). Always present regardless of whether `url` is set. Assembled from source title and anchor metadata by the citation service.

`AnchorResponse` SHALL contain the following fields:
- `page` — nullable integer, the page number within the source document
- `chapter` — nullable string, the chapter title or identifier
- `section` — nullable string, the section title or identifier
- `timecode` — nullable string, the timecode for audio/video sources

For user messages, the `citations` field SHALL be `null` (citations are not applicable). For assistant messages with COMPLETE status, the `citations` field SHALL be an empty list `[]` when no citations were produced (never `null`). For assistant messages with FAILED or PARTIAL status, the `citations` field SHALL be `null` (citations were not computed). If the session does not exist, the endpoint SHALL return 404.

#### Scenario: Get session with messages including citations

- **WHEN** `GET /api/chat/sessions/{session_id}` is called for a session that has 2 messages (1 user, 1 assistant with 2 citations)
- **THEN** the response SHALL be 200
- **AND** `messages` SHALL contain 2 entries ordered by `created_at` ascending
- **AND** the user message SHALL have `citations` as `null`
- **AND** the assistant message SHALL have `citations` as a list of 2 `CitationResponse` objects
- **AND** each `CitationResponse` SHALL include `index`, `source_id`, `source_title`, `source_type`, `url`, `anchor`, and `text_citation`

#### Scenario: COMPLETE assistant message without citations returns empty list

- **WHEN** `GET /api/chat/sessions/{session_id}` is called for a session with a COMPLETE assistant message that produced no citations
- **THEN** the assistant message SHALL have `citations` as `[]` (empty list, not `null`)

#### Scenario: User message citations is null

- **WHEN** `GET /api/chat/sessions/{session_id}` is called for a session with a user message
- **THEN** the user message SHALL have `citations` as `null`

#### Scenario: CitationResponse anchor structure

- **WHEN** an assistant message has a citation referencing page 42, section "Introduction"
- **THEN** the `CitationResponse.anchor` SHALL be an `AnchorResponse` with `page=42`, `section="Introduction"`, and `chapter` and `timecode` as `null`

#### Scenario: Get session with no messages

- **WHEN** `GET /api/chat/sessions/{session_id}` is called for a session with no messages
- **THEN** the response SHALL be 200 with `messages` as an empty array and `message_count` of 0

#### Scenario: Get non-existent session returns 404

- **WHEN** `GET /api/chat/sessions/{session_id}` is called with a UUID that does not match any session
- **THEN** the response SHALL be 404 with detail "Session not found"

---

## ADDED Requirements

### Requirement: Source metadata batch loading in chat flow

After retrieval and before prompt assembly, the chat service SHALL batch-load source metadata from PostgreSQL for all unique `source_id` values present in the retrieved chunks. The batch query SHALL load `title`, `public_url`, and `source_type` for each source in a single database query. The resulting source map (`dict[UUID, SourceInfo]`) SHALL be passed to both the prompt builder (for context enrichment) and the citation service (for building citation objects with source titles and URLs).

`SourceInfo` SHALL contain the following fields:
- `id` — UUID, the source identifier
- `title` — string, the human-readable title of the source document
- `public_url` — nullable string, the public URL of the source (null when no public URL exists)
- `source_type` — string, the type of the source (e.g., `"pdf"`, `"markdown"`, `"audio"`)

Sources that are soft-deleted (`deleted_at IS NOT NULL`) SHALL be excluded from the source map. If a retrieved chunk references a `source_id` that is missing from the source map (deleted or otherwise absent), the citation service SHALL silently skip that source — no fallback entry, no error.

#### Scenario: Batch load source metadata for retrieved chunks

- **WHEN** retrieval returns 5 chunks from 3 unique source documents
- **THEN** the chat service SHALL execute a single batch query to load metadata for those 3 source IDs
- **AND** the resulting source map SHALL contain entries for all 3 sources

#### Scenario: Source map passed to citation service

- **WHEN** the source map is constructed after retrieval
- **THEN** the chat service SHALL pass the source map to the citation service alongside the LLM response and retrieved chunks

#### Scenario: Source map passed to prompt builder

- **WHEN** the source map is constructed after retrieval
- **THEN** the chat service SHALL pass the source map to the prompt builder for context enrichment

#### Scenario: Missing source silently skipped

- **WHEN** a retrieved chunk references a `source_id` that no longer exists in the database (soft-deleted or absent)
- **THEN** the source map SHALL NOT contain an entry for that `source_id`
- **AND** the citation service SHALL silently skip that source (no citation produced for it)
- **AND** the chat flow SHALL NOT raise an error

#### Scenario: No retrieval skips batch loading

- **WHEN** retrieval returns 0 chunks (triggering a refusal)
- **THEN** the source metadata batch loading step SHALL be skipped
- **AND** an empty source map SHALL be used
