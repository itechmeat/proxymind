## MODIFIED Requirements

### Requirement: Qdrant collection with named dense vector

The `ensure_collection()` method SHALL create a Qdrant collection with both a named dense vector `"dense"` and a named sparse vector `"bm25"`. The dense vector SHALL have `size` equal to `settings.embedding_dimensions` (default 3072) and `distance` set to Cosine. The sparse vector SHALL be configured with `SparseVectorParams(modifier=Modifier.IDF)`. The collection creation call SHALL include `sparse_vectors_config={"bm25": SparseVectorParams(modifier=Modifier.IDF)}` alongside the existing `vectors_config`.

#### Scenario: Collection created with both dense and BM25 sparse vectors

- **WHEN** `ensure_collection()` is called and no collection exists
- **THEN** a collection SHALL be created with vectors config `{ "dense": { size: 3072, distance: Cosine } }`
- **AND** the collection SHALL include sparse vectors config `{ "bm25": SparseVectorParams(modifier=Modifier.IDF) }`

#### Scenario: Collection creation is idempotent

- **WHEN** `ensure_collection()` is called and the collection already exists with matching dense and sparse configuration
- **THEN** the method SHALL return without error and without recreating the collection

---

### Requirement: Point upsert with named vector and payload

The `_upsert_points()` method SHALL upsert points with a vector dict containing both `"dense"` (float vector) and `"bm25"` (`models.Document(text=point.text_content, model="Qdrant/bm25", options=Bm25Config(language=self.bm25_language))`). The payload structure SHALL remain unchanged. Qdrant SHALL tokenize the BM25 Document text server-side using the specified Snowball stemmer.

#### Scenario: Points upserted with both dense and BM25 vectors

- **WHEN** `_upsert_points()` is called with a list of points
- **THEN** each point SHALL have a vector dict with key `"dense"` containing the float vector
- **AND** each point SHALL have a vector dict with key `"bm25"` containing a `Document` with `model="Qdrant/bm25"`, `text=point.text_content`, and `options=Bm25Config(language=self.bm25_language)`

#### Scenario: BM25 Document uses the same text_content as dense embedding

- **WHEN** a chunk is upserted
- **THEN** the `"bm25"` Document text SHALL be identical to the `text_content` used for dense embedding generation

---

### Requirement: Forward-compatible schema for sparse vectors

The collection schema uses named vectors (`"dense"`) for forward-compatibility. As of S3-02, the `"bm25"` sparse vector is now part of the collection schema created by `ensure_collection()`. The sparse vector configuration is included at collection creation time alongside the dense vector. The `ensure_collection()` method SHALL create both vectors in a single collection creation call.

#### Scenario: Collection uses named vectors with sparse vector included

- **WHEN** the collection is created by `ensure_collection()`
- **THEN** the collection SHALL have a vectors config with key `"dense"` (named)
- **AND** the collection SHALL have a sparse vectors config with key `"bm25"`
- **AND** it SHALL NOT have an unnamed default vector

---

## ADDED Requirements

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

## Test Coverage

### CI tests (deterministic, mocked external services)

- **Collection creation with sparse vector** (`backend/tests/unit/services/test_qdrant.py`): verify `ensure_collection` creates collection with `sparse_vectors_config` containing `"bm25"` with `Modifier.IDF`.
- **Sparse vector schema mismatch triggers recreation** (`backend/tests/unit/services/test_qdrant.py`): mock existing collection without `"bm25"` sparse vector or with wrong modifier; verify WARNING log and delete + recreate sequence.
- **Dense dimension mismatch still raises error** (`backend/tests/unit/services/test_qdrant.py`): verify `CollectionSchemaMismatchError` is raised on dimension mismatch (unchanged behavior).
- **Upsert includes BM25 Document** (`backend/tests/unit/services/test_qdrant.py`): verify `_upsert_points` vector dict includes both `"dense"` vector and `"bm25"` `Document` with correct `model`, `text`, and `options.language`.
- **bm25_language logged during startup collection checks** (`backend/tests/unit/services/test_qdrant.py`): verify log output includes configured language.

### Integration tests (real Qdrant)

- **Collection recreation roundtrip** (`backend/tests/integration/test_qdrant_roundtrip.py`): create collection without sparse vector, call `ensure_collection`, verify collection is recreated with both vectors.
