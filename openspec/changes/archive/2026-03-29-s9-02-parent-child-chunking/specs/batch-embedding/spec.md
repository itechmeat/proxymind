## ADDED Requirements

### Requirement: Parent-aware payload parity between immediate and batch embedding

For story S9-02, Gemini Batch embedding SHALL preserve the same parent-aware child payload contract as immediate embedding. Batch submission SHALL continue to embed child-based text, and batch completion SHALL rebuild the Qdrant child payload using the persisted parent metadata from PostgreSQL.

#### Definitions

- **Qualifying long-form document:** a Path B or Path C source whose parsed child chunks meet both configured hierarchy thresholds after initial flat chunking: total parsed token count greater than or equal to `PARENT_CHILD_MIN_DOCUMENT_TOKENS` and child chunk count greater than or equal to `PARENT_CHILD_MIN_FLAT_CHUNKS`. Current defaults are `1500` tokens and `6` child chunks. Structural anchors improve grouping but are not required.
- **Non-qualifying flat source:** any source that stays below either hierarchy threshold or does not enter the Path B / Path C hierarchy flow. Its batch payload keeps the fixed parent-aware field set, but every parent field is null.

#### Parent-aware payload contract

The parent-aware child payload contract uses the same flat Qdrant child payload fields in both immediate and Gemini Batch flows. For qualifying long-form documents, the rebuilt child payload SHALL contain:

- `parent_id: string | null` (`UUID` serialized as string)
- `parent_text_content: string | null`
- `parent_token_count: integer | null`
- `parent_anchor_page: integer | null`
- `parent_anchor_chapter: string | null`
- `parent_anchor_section: string | null`
- `parent_anchor_timecode: string | null`

The minimal PostgreSQL schema mapping for these fields is:

- `chunks.parent_id -> chunk_parents.id`
- `chunk_parents.text_content -> parent_text_content`
- `chunk_parents.token_count -> parent_token_count`
- `chunk_parents.anchor_page -> parent_anchor_page`
- `chunk_parents.anchor_chapter -> parent_anchor_chapter`
- `chunk_parents.anchor_section -> parent_anchor_section`
- `chunk_parents.anchor_timecode -> parent_anchor_timecode`

Example qualifying child payload in Qdrant:

```json
{
  "chunk_id": "0195c0b1-6f6d-7bd9-9d5d-7b95d0205c55",
  "text_content": "Matched child excerpt",
  "parent_id": "0195c0b1-71b2-7c24-b5a9-4f20d5dc57a5",
  "parent_text_content": "Full parent section text",
  "parent_token_count": 1180,
  "parent_anchor_page": 24,
  "parent_anchor_chapter": "Chapter 3",
  "parent_anchor_section": "Retrieval",
  "parent_anchor_timecode": null
}
```

Example non-qualifying flat child payload in Qdrant:

```json
{
  "chunk_id": "0195c0b1-6f6d-7bd9-9d5d-7b95d0205c55",
  "text_content": "Flat child excerpt",
  "parent_id": null,
  "parent_text_content": null,
  "parent_token_count": null,
  "parent_anchor_page": null,
  "parent_anchor_chapter": null,
  "parent_anchor_section": null,
  "parent_anchor_timecode": null
}
```

#### Scenario: Batch submission keeps child-based embedding input

- **WHEN** a qualifying long-form document is routed through Gemini Batch embedding
- **THEN** the submitted embedding text SHALL remain the child-based embedding input used by the immediate path
- **AND** parent text SHALL NOT replace the child embedding input

#### Scenario: Batch completion rebuilds parent-aware child payload

- **WHEN** Gemini Batch embedding completes for qualifying long-form child chunks
- **THEN** batch result application SHALL rebuild Qdrant child points with the same parent metadata fields used by immediate embedding

#### Scenario: Batch completion handles missing parent metadata

- **WHEN** Gemini Batch completion needs to rebuild a qualifying child payload and the referenced parent metadata cannot be loaded from PostgreSQL
- **THEN** batch completion SHALL fail closed instead of writing a partial parent-aware child payload
- **AND** the `BatchJob` SHALL transition from `PROCESSING` to `FAILED`
- **AND** the linked ingestion `BackgroundTask` SHALL transition from `PROCESSING` to `FAILED`
- **AND** the failure metadata SHALL record the error message and completion timestamp

#### Scenario: Batch completion handles Qdrant update failures

- **WHEN** Gemini Batch completion rebuilds qualifying child payloads and the Qdrant upsert fails
- **THEN** batch completion SHALL perform best-effort cleanup for any child points attempted in that failing upsert
- **AND** the `BatchJob` SHALL transition from `PROCESSING` to `FAILED`
- **AND** the linked ingestion `BackgroundTask` SHALL transition from `PROCESSING` to `FAILED`
- **AND** no automatic retry or backoff SHALL be introduced by this change
- **AND** the failure SHALL be recorded in the batch/job error metadata for later operator diagnosis

#### Scenario: Immediate and batch payload contracts stay aligned

- **WHEN** the same qualifying long-form source is indexed once through immediate embedding and once through Gemini Batch embedding
- **THEN** both execution modes SHALL produce the same parent-aware child payload shape in Qdrant

#### Scenario: Flat chunks keep the same fixed payload shape in batch mode

- **WHEN** a non-qualifying flat source is indexed through Gemini Batch embedding
- **THEN** the resulting child payload SHALL use the same fixed parent-aware field set as the immediate path
- **AND** all parent metadata fields SHALL be null
