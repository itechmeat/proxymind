## Purpose

Keyword-search diagnostics capability for the active sparse retrieval slot in the Qdrant vector storage layer. Provides a provider-aware `keyword_search` method on `QdrantService`, an Admin API endpoint for diagnostics and evals, active sparse backend metadata in responses, and configurable BM25 language (Snowball stemmer) for the BM25 provider.

## Requirements

### Requirement: keyword_search method

The `QdrantService` SHALL provide a `keyword_search()` method that queries the active sparse retrieval slot. The method SHALL accept `text` (str), `snapshot_id` (UUID), `agent_id` (UUID), `knowledge_base_id` (UUID), and `limit` (int, default 10). The active sparse backend is resolved from the `QdrantService` instance attribute `sparse_backend`, which is wired at startup from installation configuration rather than passed as a per-call argument. The method SHALL apply a payload filter on `snapshot_id`, `agent_id`, and `knowledge_base_id` to scope results. The method SHALL return `list[RetrievedChunk]` with the same structure as the dense `search()` method. The method SHALL retry on transient connection errors using the same retry strategy as other QdrantService methods (3 attempts, exponential backoff).

For `bm25`, the query SHALL use `models.Document` with `model="Qdrant/bm25"` and `options=Bm25Config(language=self.bm25_language)`. For `bge_m3`, the query SHALL use the sparse indices/values returned by an injected external `SparseProvider` implementation.

#### Scenario: Keyword search returns matching chunks

- **WHEN** `keyword_search()` is called with text "infrastructure", a valid snapshot_id, agent_id, knowledge_base_id, and limit=5
- **THEN** the method SHALL query Qdrant using the `"bm25"` named sparse vector with a `Document(text="infrastructure", model="Qdrant/bm25", options=Bm25Config(language=self.bm25_language))`
- **AND** the payload filter SHALL include conditions for `snapshot_id`, `agent_id`, and `knowledge_base_id`
- **AND** the method SHALL return up to 5 `RetrievedChunk` results ordered by BM25 score descending

#### Scenario: Keyword search uses external sparse provider when BGE-M3 is active

- **WHEN** `keyword_search()` is called while the service is configured with `sparse_backend=bge_m3`
- **THEN** the method SHALL use the external sparse provider output for the query text instead of a BM25 `Document`
- **AND** results SHALL remain scoped by `snapshot_id`, `agent_id`, and `knowledge_base_id`

#### Scenario: Keyword search returns empty list when no chunks match

- **WHEN** `keyword_search()` is called with text that matches no indexed chunks
- **THEN** the method SHALL return an empty list

#### Scenario: Keyword search retries on transient errors

- **WHEN** the Qdrant query fails with a connection error on the first attempt and succeeds on the second
- **THEN** the method SHALL succeed without raising an exception

#### Scenario: Keyword search fails after max retries

- **WHEN** the Qdrant query fails with a connection error on all 3 attempts
- **THEN** the method SHALL raise an exception after exhausting retries

#### Scenario: Keyword search result contains correct payload fields

- **WHEN** `keyword_search()` returns results
- **THEN** each `RetrievedChunk` SHALL contain `chunk_id`, `source_id`, `text_content`, `score`, and `anchor_metadata`

---

### Requirement: Admin keyword search endpoint

The system SHALL provide a `POST /api/admin/search/keyword` endpoint for sparse-leg diagnostics. The request body SHALL accept `query` (required, min_length=1), `snapshot_id` (optional, defaults to active snapshot), `agent_id` (optional, defaults to `DEFAULT_AGENT_ID`), `knowledge_base_id` (optional, defaults to `DEFAULT_KNOWLEDGE_BASE_ID`), and `limit` (optional, default 10). The request body SHALL NOT accept client-set `sparse_backend` or `sparse_model` fields in S9-03. The response SHALL include `results` (list of objects with `chunk_id`, `source_id`, `text_content`, `score`, and a nested `anchor` object containing `page`, `chapter`, `section`, `timecode`), `query` (original query string), `language` (active sparse-language signal, `null` under `bge_m3`), `bm25_language` (install-level BM25 language), `sparse_backend`, `sparse_model`, and `total` (number of results). `sparse_backend` and `sparse_model` are derived from the startup-wired `QdrantService`, not from request parameters or per-snapshot overrides. If `snapshot_id` is not provided and no active snapshot exists, the endpoint SHALL return 422. Admin auth is deferred to S7-01.

#### Scenario: Valid keyword search returns results

- **WHEN** a POST request is sent to `/api/admin/search/keyword` with `{"query": "deployment"}`
- **THEN** the response status SHALL be 200
- **AND** the response body SHALL contain `results` (list), `query` ("deployment"), `language`, `bm25_language`, `sparse_backend`, `sparse_model`, and `total` (count of results)
- **AND** each result SHALL contain a nested `anchor` object with `page`, `chapter`, `section`, and `timecode` fields

#### Scenario: BGE-M3 diagnostics report configured sparse metadata

- **WHEN** the endpoint is called while the service is configured with `sparse_backend=bge_m3`
- **THEN** the response SHALL include `sparse_backend="bge_m3"` and the configured sparse model identifier
- **AND** `language` SHALL be `null`
- **AND** `bm25_language` SHALL still expose the install-level BM25 stemming configuration

#### Scenario: Default snapshot_id uses active snapshot

- **WHEN** a POST request is sent without `snapshot_id` and an active snapshot exists
- **THEN** the endpoint SHALL resolve the active snapshot via SnapshotService and use its ID for the keyword search

#### Scenario: No active snapshot returns 422

- **WHEN** a POST request is sent without `snapshot_id` and no active snapshot exists
- **THEN** the response status SHALL be 422
- **AND** the response body SHALL contain an error message

#### Scenario: Default agent_id and knowledge_base_id use constants

- **WHEN** a POST request is sent without `agent_id` and `knowledge_base_id`
- **THEN** the endpoint SHALL use `DEFAULT_AGENT_ID` and `DEFAULT_KNOWLEDGE_BASE_ID` for the keyword search

#### Scenario: Empty query returns validation error

- **WHEN** a POST request is sent with `{"query": ""}`
- **THEN** the response status SHALL be 422

---

### Requirement: BM25 language configuration

The `bm25_language` setting (already present in `config.py`) SHALL be passed to the `QdrantService` constructor and used in `Bm25Config` at both upsert and query time. The configured language SHALL determine the Snowball stemmer used by Qdrant for BM25 tokenization. Changing `bm25_language` in `.env` after data has been indexed SHALL require manual collection deletion and re-ingestion. The configured `bm25_language` SHALL be logged at QdrantService startup for visibility.

#### Scenario: BM25 language is applied at upsert time

- **WHEN** chunks are upserted via `_upsert_points`
- **THEN** the BM25 `Document` SHALL use `Bm25Config(language=self.bm25_language)` matching the configured language

#### Scenario: BM25 language is applied at query time

- **WHEN** `keyword_search()` is called
- **THEN** the query `Document` SHALL use `Bm25Config(language=self.bm25_language)` matching the configured language

#### Scenario: Stemming works for configured language

- **WHEN** a chunk containing "runs" is upserted with `bm25_language="english"` and a keyword search for "running" is performed
- **THEN** the search SHALL return the chunk as a match (Snowball stemmer reduces both "runs" and "running" to the same stem)

#### Scenario: BM25 language is logged during startup collection checks

- **WHEN** `ensure_collection()` runs during startup
- **THEN** the configured `bm25_language` SHALL be logged as part of collection validation

---

## Test Coverage

### CI tests (deterministic, mocked external services)

- **keyword_search unit tests** (`backend/tests/unit/services/test_qdrant.py`): mock `AsyncQdrantClient`; verify query uses `Document(model="Qdrant/bm25")` with correct language, filter includes `snapshot_id`/`agent_id`/`knowledge_base_id`, limit is passed; verify retry on transient errors; verify empty results return empty list.
- **Admin keyword search endpoint tests** (`backend/tests/unit/test_admin_keyword_search.py`): valid request returns 200 with correct response structure including nested `anchor` object, `language`, `bm25_language`, `sparse_backend`, and `sparse_model`; default `snapshot_id` uses active snapshot; no active snapshot returns 422; default `agent_id`/`knowledge_base_id` use constants; empty query returns 422.

### Integration tests (real Qdrant)

- **Keyword search roundtrip** (`backend/tests/integration/test_qdrant_roundtrip.py`): upsert chunks with `text_content` via BM25 Document, keyword search finds them by keywords; keyword search scoped by `snapshot_id` excludes chunks from other snapshots; stemming roundtrip (upsert "runs", search "running", language=english).
