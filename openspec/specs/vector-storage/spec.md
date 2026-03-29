## ADDED Requirements: S9-02 Parent Metadata

### Requirement: QdrantService for collection management, point upsert, and dense search

The system SHALL provide a `QdrantService` at `app/services/qdrant.py` that wraps the async Qdrant client. The service SHALL receive the `AsyncQdrantClient` instance and collection configuration via constructor injection. The service SHALL provide three methods: `ensure_collection()` for idempotent collection creation, `upsert_chunks()` for point upsert, and `dense_search()` for dense vector retrieval with payload filtering.

#### Scenario: QdrantService is instantiable with injected client

- **WHEN** a `QdrantService` is created with an `AsyncQdrantClient` and settings
- **THEN** the instance SHALL be ready to call `ensure_collection()`, `upsert_chunks()`, and `dense_search()`

#### Scenario: Dense search returns matching chunks filtered by snapshot

- **WHEN** `dense_search()` is called with a query vector, snapshot_id, agent_id, knowledge_base_id, and limit=5
- **THEN** the method SHALL query Qdrant using the `"dense"` named vector
- **AND** the payload filter SHALL include conditions for `snapshot_id`, `agent_id`, and `knowledge_base_id`
- **AND** the method SHALL return up to 5 `RetrievedChunk` results ordered by similarity score descending

#### Scenario: Search with score_threshold filters low-scoring results

- **WHEN** `dense_search()` is called with `score_threshold=0.5`
- **THEN** only points with cosine similarity >= 0.5 SHALL be returned
- **AND** points with similarity below 0.5 SHALL be excluded by Qdrant before returning

#### Scenario: Search with score_threshold=None returns all top-N results

- **WHEN** `dense_search()` is called with `score_threshold=None`
- **THEN** all top-N results SHALL be returned regardless of their similarity score

#### Scenario: Search returns empty list when no chunks match

- **WHEN** `dense_search()` is called with a snapshot_id that has no indexed chunks in Qdrant
- **THEN** the method SHALL return an empty list

#### Scenario: Search result contains correct payload fields

- **WHEN** `dense_search()` returns results
- **THEN** each `RetrievedChunk` SHALL contain `chunk_id`, `source_id`, `text_content`, `score`, and `anchor_metadata`
- **AND** `anchor_metadata` SHALL include `anchor_page`, `anchor_chapter`, `anchor_section`, and `anchor_timecode` fields from the point payload

---

### Requirement: Qdrant collection with named dense and BM25 sparse vectors

The `ensure_collection()` method SHALL create a Qdrant collection named per the `qdrant_collection` setting (default `"proxymind_chunks"`). The collection SHALL use a **named** vector configuration with a dense vector named `"dense"` and a sparse vector named `"bm25"`. The `"dense"` vector SHALL have `size` equal to `settings.embedding_dimensions` (default 3072) and `distance` set to Cosine. The `"bm25"` sparse vector SHALL be configured with `SparseVectorParams(modifier=Modifier.IDF)`. The collection creation call SHALL include both `vectors_config` and `sparse_vectors_config`.

#### Scenario: Collection created with both dense and BM25 sparse vectors

- **WHEN** `ensure_collection()` is called and no collection exists
- **THEN** a collection SHALL be created with vectors config `{ "dense": { size: 3072, distance: Cosine } }`
- **AND** the collection SHALL include sparse vectors config `{ "bm25": SparseVectorParams(modifier=Modifier.IDF) }`

#### Scenario: Collection creation is idempotent

- **WHEN** `ensure_collection()` is called and the collection already exists with matching dense and sparse configuration
- **THEN** the method SHALL return without error and without recreating the collection

---

### Requirement: Payload indexes on filtered fields

The `ensure_collection()` method SHALL create payload indexes on the following fields: `snapshot_id` (keyword), `agent_id` (keyword), `knowledge_base_id` (keyword), `source_id` (keyword), `status` (keyword), `source_type` (keyword), `language` (keyword). These indexes are required for efficient payload filtering during retrieval (S2-04) and future BM25 language scoping (S3-02). Index creation SHALL be idempotent.

#### Scenario: All required payload indexes are created

- **WHEN** `ensure_collection()` completes
- **THEN** payload indexes SHALL exist on `snapshot_id`, `agent_id`, `knowledge_base_id`, `source_id`, `status`, `source_type`, and `language`

#### Scenario: Index creation is idempotent

- **WHEN** `ensure_collection()` is called twice
- **THEN** the second call SHALL succeed without error and without duplicating indexes

---

### Requirement: Dimension mismatch detection

The `ensure_collection()` method SHALL compare the existing collection's `"dense"` vector size with `settings.embedding_dimensions` when the collection already exists. If the sizes differ, the method SHALL raise a `CollectionSchemaMismatchError` with a message stating the existing size, the required size, and that reindexing is required (delete the collection and re-run ingestion). The worker SHALL fail fast on this error; it SHALL NOT silently write vectors with wrong dimensions.

#### Scenario: Dimension mismatch raises error

- **WHEN** the collection exists with `dense` vector size 3072 and `settings.embedding_dimensions` is 1024
- **THEN** `ensure_collection()` SHALL raise `CollectionSchemaMismatchError`
- **AND** the error message SHALL contain both dimension values and mention reindexing

#### Scenario: Matching dimensions pass silently

- **WHEN** the collection exists with `dense` vector size 3072 and `settings.embedding_dimensions` is 3072
- **THEN** `ensure_collection()` SHALL return without error

---

### Requirement: Point upsert with named vector and payload

The `upsert_chunks()` method SHALL accept a list of point data and upsert them to Qdrant. Each point SHALL have: `id` (chunk UUID from PostgreSQL, string format), vector dict containing `"dense"` (float vector) and `"bm25"` (`models.Document(text=point.bm25_text, model="Qdrant/bm25", options=Bm25Config(language=self.bm25_language))`), and a payload containing: `snapshot_id`, `source_id`, `chunk_id`, `document_version_id`, `agent_id`, `knowledge_base_id`, `text_content`, `chunk_index`, `token_count`, `anchor_page`, `anchor_chapter`, `anchor_section`, `anchor_timecode`, `source_type`, `language`, `status`, `enriched_summary`, `enriched_keywords`, `enriched_questions`, `enriched_text`, `enrichment_model`, `enrichment_pipeline_version`.

**[Modified by S9-01]** The BM25 sparse vector input SHALL use the `bm25_text` property of each point instead of `text_content`. The `bm25_text` property SHALL resolve to `enriched_text` when available (non-None), falling back to `text_content` otherwise. This ensures enriched keywords and questions improve lexical search without requiring changes to the retrieval pipeline. The `text_content` payload field SHALL continue to hold the original chunk text (without enrichment artifacts) for use in LLM context during answer generation and for citation display.

#### Scenario: Points upserted with both dense and BM25 vectors

- **WHEN** `upsert_chunks()` is called with a list of points
- **THEN** each point SHALL have a vector dict with key `"dense"` containing the float vector
- **AND** each point SHALL have a vector dict with key `"bm25"` containing a `Document` with `model="Qdrant/bm25"`, `text=point.bm25_text`, and `options=Bm25Config(language=self.bm25_language)`
- **AND** each point payload SHALL contain all specified fields including the 6 enrichment fields

#### Scenario: BM25 Document uses enriched_text when available

- **WHEN** a chunk has been enriched and `enriched_text` is non-None
- **THEN** the `"bm25"` Document text SHALL be `enriched_text` (the concatenation of original text with summary, keywords, and questions)
- **AND** the `"dense"` embedding SHALL also have been generated from `enriched_text`
- **AND** `text_content` in the payload SHALL remain the original unenriched chunk text

#### Scenario: BM25 Document falls back to text_content when unenriched

- **WHEN** a chunk has not been enriched (enrichment disabled or enrichment failed) and `enriched_text` is None
- **THEN** the `"bm25"` Document text SHALL be `text_content`
- **AND** behavior SHALL be identical to the pre-enrichment pipeline

#### Scenario: text_content dual-write to payload

- **WHEN** a chunk is upserted to Qdrant
- **THEN** the payload SHALL include `text_content` with the original chunk text (not enriched text)
- **AND** the same `text_content` SHALL exist in the PostgreSQL Chunk record (source of truth for audit and reindex; Qdrant copy avoids PG round-trip during chat retrieval)
- **AND** the write ordering SHALL be PostgreSQL Tx 1 (persist `Chunk` rows as PENDING) -> Qdrant upsert -> PostgreSQL Tx 2 (finalize rows as INDEXED)
- **AND** if PostgreSQL Tx 1 succeeds but the Qdrant upsert fails, the task SHALL fail and the persisted PostgreSQL records SHALL be marked FAILED in a recovery transaction
- **AND** if the Qdrant upsert succeeds but PostgreSQL Tx 2 fails, the worker SHALL attempt a compensating delete of the just-upserted Qdrant points by point ID (the chunk UUID used as the Qdrant point ID); if that delete also fails, the task SHALL still fail and operator reconciliation is required

---

### Requirement: Tenacity retry on Qdrant upsert

The `upsert_chunks()` method SHALL be wrapped with tenacity retry for connection errors. The retry strategy SHALL use a maximum of 3 attempts with exponential backoff.

#### Scenario: Transient connection error is retried

- **WHEN** the Qdrant upsert fails with a connection error on the first attempt and succeeds on the second
- **THEN** the upsert SHALL succeed without raising an exception

#### Scenario: Persistent failure after max retries raises exception

- **WHEN** the Qdrant upsert fails with a connection error on all 3 attempts
- **THEN** the method SHALL raise an exception after exhausting retries

---

### Requirement: Forward-compatible schema with sparse vectors

The collection schema SHALL use named vectors (`"dense"` and `"bm25"`) rather than an unnamed default vector. As of S3-02, the `"bm25"` sparse vector is part of the collection schema created by `ensure_collection()`. Both vectors are included in a single collection creation call.

#### Scenario: Collection uses named vectors with sparse vector included

- **WHEN** the collection is created by `ensure_collection()`
- **THEN** the collection SHALL have a vectors config with key `"dense"` (named)
- **AND** the collection SHALL have a sparse vectors config with key `"bm25"`
- **AND** it SHALL NOT have an unnamed default vector

---

### Requirement: ensure_collection auto-recreates on missing or invalid BM25 sparse vector config

When `ensure_collection()` detects that an existing collection lacks the required `"bm25"` sparse vector configuration, it SHALL log a WARNING message stating that the collection is missing the required BM25 sparse vector configuration and will be recreated, and that all existing vectors will be lost requiring re-ingestion. The method SHALL then perform a race-safe delete and recreate of the collection with both `"dense"` and `"bm25"` vectors. The required configuration includes presence of the `"bm25"` sparse vector and `SparseVectorParams(modifier=Modifier.IDF)`. Race safety SHALL be achieved by catching 404 on delete of a non-existent collection and 409 on create of an already-existing collection, retrying validation in both cases. The validation loop SHALL be bounded to a maximum of 3 attempts before raising `CollectionSchemaMismatchError`. Dense dimension mismatch SHALL remain a hard error raising `CollectionSchemaMismatchError` (unchanged).

#### Scenario: Missing BM25 sparse vector triggers recreation

- **WHEN** `ensure_collection()` is called and the collection exists with `"dense"` vector but no `"bm25"` sparse vector
- **THEN** the method SHALL log a WARNING about collection recreation
- **AND** the method SHALL delete and recreate the collection with both `"dense"` and `"bm25"` vectors

#### Scenario: Incorrect BM25 modifier triggers recreation

- **WHEN** `ensure_collection()` is called and the collection exists with `"bm25"` sparse vector configured without `Modifier.IDF`
- **THEN** the method SHALL log a WARNING about collection recreation
- **AND** the method SHALL delete and recreate the collection with `SparseVectorParams(modifier=Modifier.IDF)`

#### Scenario: Dense dimension mismatch remains a hard error

- **WHEN** the collection exists with `"dense"` vector size 3072 and `settings.embedding_dimensions` is 1024
- **THEN** `ensure_collection()` SHALL raise `CollectionSchemaMismatchError`
- **AND** the method SHALL NOT attempt to auto-recreate the collection

#### Scenario: Race-safe recreation handles concurrent startup

- **WHEN** two processes (API and worker) call `ensure_collection()` simultaneously and both detect invalid BM25 sparse vector configuration
- **THEN** one process SHALL succeed in delete + recreate
- **AND** the other process SHALL handle the 404 (delete of already-deleted collection) or 409 (create of already-created collection) gracefully without raising an unhandled exception

#### Scenario: Race-safe recreation stops after bounded retries

- **WHEN** `ensure_collection()` cannot converge to a collection containing the `"bm25"` sparse vector within 3 validation attempts
- **THEN** the method SHALL raise `CollectionSchemaMismatchError`

---

### Requirement: bm25_language is logged during startup collection checks

When the application starts and `ensure_collection()` runs as part of startup initialization, the configured `bm25_language` SHALL be logged for operator visibility.

#### Scenario: bm25_language is logged during ensure_collection startup path

- **WHEN** startup triggers `ensure_collection()`
- **THEN** the configured `bm25_language` SHALL have been logged for operator visibility

---

### Requirement: Score semantics are method-specific

After the introduction of hybrid search, `RetrievedChunk.score` returned by `hybrid_search()` SHALL represent an RRF rank score rather than a cosine similarity value. The field SHALL remain available to downstream consumers as retrieval metadata, but its interpretation is method-specific. The field name `score` SHALL NOT be renamed.
The `score` field returned by `dense_search()` SHALL continue to represent cosine similarity. The `score` field returned by `keyword_search()` SHALL continue to represent BM25 relevance. The semantic difference is method-specific and documented, not encoded in the type. Downstream consumers SHALL treat `RetrievedChunk.score` as method-specific metadata and SHALL NOT compare values across retrieval methods unless they already know the producing method.

#### Scenario: hybrid_search score is RRF rank score

- **WHEN** `hybrid_search()` returns results
- **THEN** each `RetrievedChunk.score` SHALL contain the RRF rank score from Qdrant fusion
- **AND** the score SHALL NOT be interpreted as cosine similarity

#### Scenario: dense_search score remains cosine similarity

- **WHEN** `dense_search()` returns results
- **THEN** each `RetrievedChunk.score` SHALL contain the cosine similarity value (unchanged from previous behavior)

#### Scenario: score is opaque metadata to downstream consumers

- **WHEN** `RetrievedChunk.score` is consumed outside `QdrantService`
- **THEN** callers SHALL treat it as method-specific metadata
- **AND** callers SHALL NOT assume that hybrid, dense, and keyword scores share the same scale or interpretation

---

## Test Coverage

### CI tests (deterministic, mocked external services)

The following stable behavior MUST be covered by CI tests before archive:

- **QdrantService unit tests**: mock `AsyncQdrantClient`. Verify collection creation parameters (named vector "dense", sparse vector "bm25" with Modifier.IDF, correct size, Cosine distance), payload index creation for all 7 fields (snapshot_id, agent_id, knowledge_base_id, source_id, status, source_type, language), idempotent `ensure_collection`, point upsert structure (named vector with both dense and BM25 Document, payload shape), retry on connection errors.
- **QdrantService.dense_search unit tests**: mock `AsyncQdrantClient`. Verify dense_search constructs correct named vector query (`"dense"`). Verify payload filter includes all three fields (snapshot_id, agent_id, knowledge_base_id). Verify score_threshold is passed to Qdrant when set. Verify score_threshold=None omits score filtering. Verify results are mapped to `RetrievedChunk` with correct fields. Verify empty result returns empty list.
- **Dimension mismatch unit test**: mock an existing collection with size 3072, change settings to 1024, verify `CollectionSchemaMismatchError` is raised with correct message.
- **BM25 sparse vector schema unit tests**: mock existing collection without `"bm25"` sparse vector or with wrong modifier; verify WARNING log and race-safe delete + recreate sequence. Verify 404 on delete and 409 on create are handled gracefully.
- **bm25_language logging unit test**: verify configured language is logged during `ensure_collection()`.
- **Failure recovery test**: simulate a failure after successful Qdrant upsert but before PostgreSQL finalization commit, verify the worker attempts to delete the just-written Qdrant points and marks PostgreSQL records FAILED.
- **Qdrant round-trip integration test**: with a real Qdrant container (testcontainer), create collection with named `dense` and `bm25` vectors, upsert points with realistic payload, search by vector with `snapshot_id` filter, and verify expected chunks are returned. Uses fake (random) vectors to avoid Gemini dependency.
- **Collection recreation integration test**: create a dense-only collection, call `ensure_collection`, verify it is recreated with both vectors.

### Evals (non-CI)

- Real vector search quality with actual Gemini embeddings is evaluated manually, not in CI.

---

### Requirement: Enrichment payload fields in Qdrant

**[Added by S9-01]** The Qdrant point payload SHALL include 6 enrichment fields in addition to the existing payload fields. These fields store LLM-generated enrichment metadata and audit information for each chunk. All enrichment fields SHALL be nullable — they are None when enrichment is disabled, when the chunk's enrichment call failed, or when the chunk was indexed via Path A (which skips enrichment).

The enrichment payload fields SHALL be:

| Field                         | Type                | Description                                                                               |
| ----------------------------- | ------------------- | ----------------------------------------------------------------------------------------- |
| `enriched_summary`            | `str \| None`       | LLM-generated 1-2 sentence summary of the chunk                                           |
| `enriched_keywords`           | `list[str] \| None` | LLM-generated search keywords including synonyms                                          |
| `enriched_questions`          | `list[str] \| None` | LLM-generated natural questions the chunk answers                                         |
| `enriched_text`               | `str \| None`       | Full concatenated text used for embedding (text_content + summary + keywords + questions) |
| `enrichment_model`            | `str \| None`       | Model identifier used for enrichment (e.g. `"gemini-2.5-flash"`)                          |
| `enrichment_pipeline_version` | `str \| None`       | Pipeline version tag (e.g. `"s9-01-enrichment-v1"`)                                       |

The `enriched_` prefix distinguishes generated fields from original document data. No payload indexes SHALL be created on enrichment fields — they are not used for filtering. The `enriched_text` field is stored for reproducibility, recording exactly what was embedded for the dense vector and BM25 sparse vector.

#### Scenario: Enriched chunk payload contains all 6 enrichment fields

- **WHEN** a chunk with successful enrichment is upserted to Qdrant
- **THEN** the payload SHALL contain `enriched_summary` as a non-empty string
- **AND** the payload SHALL contain `enriched_keywords` as a non-empty list of strings
- **AND** the payload SHALL contain `enriched_questions` as a non-empty list of strings
- **AND** the payload SHALL contain `enriched_text` as a non-empty string containing the original `text_content` plus enrichment metadata
- **AND** the payload SHALL contain `enrichment_model` as a non-empty string (e.g. `"gemini-2.5-flash"`)
- **AND** the payload SHALL contain `enrichment_pipeline_version` as a non-empty string

#### Scenario: Unenriched chunk payload has null enrichment fields

- **WHEN** a chunk without enrichment (enrichment disabled, enrichment failed, or Path A) is upserted to Qdrant
- **THEN** `enriched_summary`, `enriched_keywords`, `enriched_questions`, `enriched_text`, `enrichment_model`, and `enrichment_pipeline_version` SHALL all be None in the payload

#### Scenario: No payload indexes on enrichment fields

- **WHEN** `ensure_collection()` creates or validates the collection
- **THEN** no payload indexes SHALL be created on `enriched_summary`, `enriched_keywords`, `enriched_questions`, `enriched_text`, `enrichment_model`, or `enrichment_pipeline_version`
- **AND** the existing payload indexes on `snapshot_id`, `agent_id`, `knowledge_base_id`, `source_id`, `status`, `source_type`, and `language` SHALL remain unchanged

---

## ADDED Requirements

### Requirement: Parent metadata on child Qdrant payloads

For story S9-02, Qdrant SHALL continue indexing child chunks only, but each child point payload SHALL use one fixed parent-aware payload shape. That shape SHALL always include `parent_id`, `parent_text_content`, `parent_token_count`, `parent_anchor_page`, `parent_anchor_chapter`, `parent_anchor_section`, and `parent_anchor_timecode`. For qualifying hierarchical children these fields SHALL contain parent metadata. For flat children these same fields SHALL still be present and SHALL be null.

#### Scenario: Qualifying child point includes parent metadata

- **WHEN** a qualifying long-form child chunk is upserted to Qdrant
- **THEN** the child point payload SHALL include its parent identifier and parent text/anchor metadata

#### Scenario: Flat child point uses null parent fields in the same payload shape

- **WHEN** a non-qualifying flat chunk is upserted to Qdrant
- **THEN** the child point payload SHALL include the full parent-aware field set
- **AND** all parent metadata fields SHALL be null

---

### Requirement: Retrieved child results expose parent metadata

Child-ranked retrieval results SHALL expose the parent metadata stored on the child point payload without changing ranking semantics. `RetrievedChunk` SHALL still represent the matched child fragment, with parent data attached as supporting context.

#### Scenario: Hybrid retrieval returns child plus parent metadata

- **WHEN** hybrid retrieval returns a child chunk from a qualifying long-form document
- **THEN** the retrieval result SHALL contain the matched child text and child anchors
- **AND** it SHALL also contain the parent identifier and parent metadata needed for prompt assembly

#### Scenario: Retrieval ranking remains child-only

- **WHEN** hybrid or dense retrieval is executed for a qualifying long-form document
- **THEN** ranking SHALL continue to be based on child chunk vectors only
- **AND** parent sections SHALL NOT be ranked as independent retrieval points in this story
