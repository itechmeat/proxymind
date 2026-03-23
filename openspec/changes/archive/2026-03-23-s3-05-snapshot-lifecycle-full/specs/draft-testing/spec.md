## ADDED Requirements

### Requirement: Draft test endpoint for retrieval-only search

The system SHALL provide `POST /api/admin/snapshots/{snapshot_id}/test` that performs retrieval-only search (no LLM pass) scoped to a DRAFT snapshot. The endpoint SHALL accept optional `agent_id` and `knowledge_base_id` query parameters using the endpoint's default scope values when omitted. These query parameters scope the draft snapshot lookup and the Qdrant search request; if the requested snapshot does not exist in the resolved scope, the response SHALL be 404. The request body SHALL be JSON with the following fields:

- `query` (string, required): the search query, trimmed of leading/trailing whitespace, MUST be non-empty after trimming
- `top_n` (integer, optional): number of results to return, range 1-100, default 5
- `mode` (string, optional): search mode, one of `"hybrid"`, `"dense"`, `"sparse"`, default `"hybrid"`

#### Scenario: Hybrid search against a draft returns ranked chunks

- **WHEN** `POST /api/admin/snapshots/{snapshot_id}/test` is called with `{"query": "machine learning", "mode": "hybrid"}` on a DRAFT snapshot with INDEXED chunks
- **THEN** the response SHALL contain results from hybrid search scoped to the draft's snapshot_id
- **AND** results SHALL be ordered by score descending

#### Scenario: Dense-only search returns dense results

- **WHEN** `POST /api/admin/snapshots/{snapshot_id}/test` is called with `{"query": "neural networks", "mode": "dense"}`
- **THEN** the response SHALL contain results from dense vector search only

#### Scenario: Sparse-only search returns BM25 results

- **WHEN** `POST /api/admin/snapshots/{snapshot_id}/test` is called with `{"query": "backpropagation", "mode": "sparse"}`
- **THEN** the response SHALL contain results from BM25 keyword search only
- **AND** no embedding generation SHALL occur

#### Scenario: Query is trimmed and validated

- **WHEN** the request body contains `{"query": "   "}`
- **THEN** the response SHALL be 422 indicating the query must be non-empty

#### Scenario: top_n limits the number of results

- **WHEN** the request body contains `{"query": "test", "top_n": 3}` and the draft has 10 indexed chunks
- **THEN** the response SHALL contain at most 3 results

#### Scenario: Invalid top_n returns 422

- **WHEN** the request body contains `{"query": "test", "top_n": 0}` or `{"query": "test", "top_n": 101}`
- **THEN** the response SHALL be 422 with validation detail indicating `top_n` must be within the configured `1..100` range

#### Scenario: Invalid mode returns 422

- **WHEN** the request body contains `{"query": "test", "mode": "invalid"}`
- **THEN** the response SHALL be 422 with validation detail indicating `mode` must be one of `"hybrid"`, `"dense"`, or `"sparse"`

---

### Requirement: Draft test calls QdrantService directly

The draft test handler SHALL call `QdrantService` search methods directly based on the requested mode, bypassing `RetrievalService`. This is because `RetrievalService.search()` always performs hybrid search and looks up the active snapshot — neither is appropriate for draft testing.

- **hybrid**: generate query embedding via `EmbeddingService`, call `QdrantService.hybrid_search(snapshot_id=draft_id)`
- **dense**: generate query embedding via `EmbeddingService`, call `QdrantService.dense_search(snapshot_id=draft_id)`
- **sparse**: call `QdrantService.keyword_search(snapshot_id=draft_id, query=query)`, no embedding generation

#### Scenario: Hybrid mode uses both embedding and QdrantService.hybrid_search

- **WHEN** mode is `"hybrid"`
- **THEN** the handler SHALL call `EmbeddingService.embed_texts()` with the query
- **AND** call `QdrantService.hybrid_search()` with the draft's `snapshot_id`

#### Scenario: Sparse mode skips embedding generation

- **WHEN** mode is `"sparse"`
- **THEN** the handler SHALL NOT call `EmbeddingService`
- **AND** SHALL call `QdrantService.keyword_search()` with the trimmed query text

---

### Requirement: Draft test validation guards

The draft test endpoint SHALL enforce the following validation:

- The snapshot MUST be in DRAFT status. If not, the response SHALL be 422 with detail indicating the snapshot must be a draft.
- The draft MUST have at least one chunk with status INDEXED. If zero indexed chunks exist, the response SHALL be 422 with detail indicating the draft has no indexed chunks.
- The snapshot MUST exist. If not found, the response SHALL be 404.

#### Scenario: Test on non-draft snapshot returns 422

- **WHEN** `POST /api/admin/snapshots/{snapshot_id}/test` is called on a PUBLISHED snapshot
- **THEN** the response SHALL be 422 with detail indicating the snapshot must be a draft

#### Scenario: Test on draft with no indexed chunks returns 422

- **WHEN** `POST /api/admin/snapshots/{snapshot_id}/test` is called on a DRAFT snapshot that has zero chunks with status INDEXED
- **THEN** the response SHALL be 422 with detail indicating the draft has no indexed chunks to search

#### Scenario: Test on non-existent snapshot returns 404

- **WHEN** `POST /api/admin/snapshots/{snapshot_id}/test` is called with a UUID that does not match any snapshot
- **THEN** the response SHALL be 404 with detail "Snapshot not found"

---

### Requirement: Draft test response schema

The draft test response SHALL be a JSON object with the following fields:

- `snapshot_id` (UUID): the draft snapshot ID
- `snapshot_name` (string): the draft snapshot name
- `query` (string): the trimmed query actually used for search
- `mode` (string): the search mode used
- `results` (array): list of result objects
- `total_chunks_in_draft` (integer): total number of INDEXED chunks in the draft

Each result object SHALL contain:

- `chunk_id` (UUID)
- `source_id` (UUID)
- `source_title` (string): enriched from PostgreSQL source record
- `text_content` (string): truncated to the first 500 Unicode characters (not bytes)
- `score` (float): retrieval score
- `anchor` (object): `{ page, chapter, section, timecode }` with nullable fields

#### Scenario: Response includes all required fields

- **WHEN** the draft test returns results
- **THEN** the response SHALL contain `snapshot_id`, `snapshot_name`, `query`, `mode`, `results`, and `total_chunks_in_draft`
- **AND** each result SHALL contain `chunk_id`, `source_id`, `source_title`, `text_content`, `score`, and `anchor`

#### Scenario: text_content is truncated to 500 Unicode characters

- **WHEN** a chunk has 1200 Unicode characters of text content
- **THEN** the `text_content` field in the response SHALL contain exactly the first 500 characters
- **AND** truncation SHALL be by character count, not byte count, to handle CJK and other multi-byte content correctly

#### Scenario: total_chunks_in_draft reflects indexed chunk count

- **WHEN** a draft snapshot has 42 chunks with status INDEXED and 3 with status PENDING
- **THEN** `total_chunks_in_draft` SHALL be 42

---

## Test Coverage

### CI tests (deterministic)

The following stable behavior MUST be covered by CI tests before archive:

- **Hybrid mode**: create draft with indexed chunks, test query in hybrid mode, verify results returned with scores.
- **Dense mode**: test query in dense-only mode, verify results from dense search.
- **Sparse mode**: test query in sparse-only mode, verify results from BM25 search, no embedding call made.
- **Error: not draft**: test on PUBLISHED snapshot -> 422.
- **Error: no indexed chunks**: test on draft with zero indexed chunks -> 422.
- **Error: not found**: test on non-existent UUID -> 404.
- **Validation: top_n**: out-of-range `top_n` -> 422.
- **Validation: mode**: unsupported `mode` -> 422.
- **text_content truncation**: verify long text is truncated to 500 characters.
- **Query normalization**: verify the response contains the trimmed query value actually used for search.
- **API endpoint tests**: verify HTTP status codes and response schema for all draft test cases.
