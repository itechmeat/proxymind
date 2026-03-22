## ADDED Requirements

### Requirement: QdrantService for collection management, point upsert, and dense search

The system SHALL provide a `QdrantService` at `app/services/qdrant.py` that wraps the async Qdrant client. The service SHALL receive the `AsyncQdrantClient` instance and collection configuration via constructor injection. The service SHALL provide three methods: `ensure_collection()` for idempotent collection creation, `upsert_chunks()` for point upsert, and `search()` for dense vector retrieval with payload filtering.

#### Scenario: QdrantService is instantiable with injected client

- **WHEN** a `QdrantService` is created with an `AsyncQdrantClient` and settings
- **THEN** the instance SHALL be ready to call `ensure_collection()`, `upsert_chunks()`, and `search()`

#### Scenario: Dense search returns matching chunks filtered by snapshot

- **WHEN** `search()` is called with a query vector, snapshot_id, agent_id, knowledge_base_id, and limit=5
- **THEN** the method SHALL query Qdrant using the `"dense"` named vector
- **AND** the payload filter SHALL include conditions for `snapshot_id`, `agent_id`, and `knowledge_base_id`
- **AND** the method SHALL return up to 5 `RetrievedChunk` results ordered by similarity score descending

#### Scenario: Search with score_threshold filters low-scoring results

- **WHEN** `search()` is called with `score_threshold=0.5`
- **THEN** only points with cosine similarity >= 0.5 SHALL be returned
- **AND** points with similarity below 0.5 SHALL be excluded by Qdrant before returning

#### Scenario: Search with score_threshold=None returns all top-N results

- **WHEN** `search()` is called with `score_threshold=None`
- **THEN** all top-N results SHALL be returned regardless of their similarity score

#### Scenario: Search returns empty list when no chunks match

- **WHEN** `search()` is called with a snapshot_id that has no indexed chunks in Qdrant
- **THEN** the method SHALL return an empty list

#### Scenario: Search result contains correct payload fields

- **WHEN** `search()` returns results
- **THEN** each `RetrievedChunk` SHALL contain `chunk_id`, `source_id`, `text_content`, `score`, and `anchor_metadata`
- **AND** `anchor_metadata` SHALL include `anchor_page`, `anchor_chapter`, `anchor_section`, and `anchor_timecode` fields from the point payload

---

### Requirement: Qdrant collection with named dense vector

The `ensure_collection()` method SHALL create a Qdrant collection named per the `qdrant_collection` setting (default `"proxymind_chunks"`). The collection SHALL use a **named** vector configuration with a single vector named `"dense"`. The `"dense"` vector SHALL have `size` equal to `settings.embedding_dimensions` (default 3072) and `distance` set to Cosine. Named vectors are required for forward-compatibility: S3-02 adds a `"sparse"` named vector via `update_collection` without recreating the collection.

#### Scenario: Collection created with named dense vector

- **WHEN** `ensure_collection()` is called and no collection exists
- **THEN** a collection SHALL be created with vectors config `{ "dense": { size: 3072, distance: Cosine } }`

#### Scenario: Collection creation is idempotent

- **WHEN** `ensure_collection()` is called and the collection already exists with matching configuration
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

The `upsert_chunks()` method SHALL accept a list of point data and upsert them to Qdrant. Each point SHALL have: `id` (chunk UUID from PostgreSQL, string format), vector `{ "dense": [float x N] }` where N equals `embedding_dimensions`, and a payload containing: `snapshot_id`, `source_id`, `chunk_id`, `document_version_id`, `agent_id`, `knowledge_base_id`, `text_content`, `chunk_index`, `token_count`, `anchor_page`, `anchor_chapter`, `anchor_section`, `anchor_timecode`, `source_type`, `language`, `status`.

#### Scenario: Points upserted with correct structure

- **WHEN** `upsert_chunks()` is called with a list of 3 points
- **THEN** 3 points SHALL be upserted to the Qdrant collection
- **AND** each point SHALL have a named vector `"dense"` (not an unnamed vector)
- **AND** each point payload SHALL contain all specified fields

#### Scenario: text_content dual-write to payload

- **WHEN** a chunk is upserted to Qdrant
- **THEN** the payload SHALL include `text_content` with the full chunk text
- **AND** the same `text_content` SHALL exist in the PostgreSQL Chunk record (source of truth for audit and reindex; Qdrant copy avoids PG round-trip during chat retrieval)
- **AND** the write ordering SHALL be PostgreSQL Tx 1 (persist `Chunk` rows as PENDING) -> Qdrant upsert -> PostgreSQL Tx 2 (finalize rows as INDEXED)
- **AND** if PostgreSQL Tx 1 succeeds but the Qdrant upsert fails, the task SHALL fail and the persisted PostgreSQL records SHALL be marked FAILED in a recovery transaction
- **AND** if the Qdrant upsert succeeds but PostgreSQL Tx 2 fails, the worker SHALL attempt a compensating delete of the just-upserted Qdrant points by `chunk_id`; if that delete also fails, the task SHALL still fail and operator reconciliation is required

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

### Requirement: Forward-compatible schema for sparse vectors

The collection schema SHALL use named vectors (`"dense"`) rather than an unnamed default vector. This is a hard requirement for S3-02 compatibility: Qdrant `update_collection` can add `sparse_vectors_config` alongside existing named vectors, but cannot add sparse vectors alongside an unnamed vector without collection recreation and full reindex. The `ensure_collection()` method SHALL NOT create any sparse vector configuration in S2-02; that is deferred to S3-02.

#### Scenario: Collection uses named vectors, not unnamed

- **WHEN** the collection is created by `ensure_collection()`
- **THEN** the collection SHALL have a vectors config with key `"dense"` (named)
- **AND** it SHALL NOT have an unnamed default vector

---

## Test Coverage

### CI tests (deterministic, mocked external services)

The following stable behavior MUST be covered by CI tests before archive:

- **QdrantService unit tests**: mock `AsyncQdrantClient`. Verify collection creation parameters (named vector "dense", correct size, Cosine distance), payload index creation for all 7 fields (snapshot_id, agent_id, knowledge_base_id, source_id, status, source_type, language), idempotent `ensure_collection`, point upsert structure (named vector, payload shape), retry on connection errors.
- **QdrantService.search unit tests**: mock `AsyncQdrantClient`. Verify search constructs correct named vector query (`"dense"`). Verify payload filter includes all three fields (snapshot_id, agent_id, knowledge_base_id). Verify score_threshold is passed to Qdrant when set. Verify score_threshold=None omits score filtering. Verify results are mapped to `RetrievedChunk` with correct fields. Verify empty result returns empty list.
- **Dimension mismatch unit test**: mock an existing collection with size 3072, change settings to 1024, verify `CollectionSchemaMismatchError` is raised with correct message.
- **Failure recovery test**: simulate a failure after successful Qdrant upsert but before PostgreSQL finalization commit, verify the worker attempts to delete the just-written Qdrant points and marks PostgreSQL records FAILED.
- **Qdrant round-trip integration test**: with a real Qdrant container (testcontainer), create collection with named `dense` vector, upsert 2-3 points with realistic payload (snapshot_id, agent_id, text_content, anchors), search by vector with `snapshot_id` filter, and verify expected chunks are returned with correct payload and score ordering. Uses fake (random) vectors to avoid Gemini dependency.

### Evals (non-CI)

- Real vector search quality with actual Gemini embeddings is evaluated manually, not in CI.
