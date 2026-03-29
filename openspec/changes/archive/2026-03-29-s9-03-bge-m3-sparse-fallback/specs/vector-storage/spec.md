## MODIFIED Requirements

### Requirement: Qdrant collection with named dense and BM25 sparse vectors

The `ensure_collection()` method SHALL create a Qdrant collection named per the `qdrant_collection` setting (default `"proxymind_chunks"`). The collection SHALL continue using a named dense vector `"dense"` and a named sparse vector slot `"bm25"` as the active sparse retrieval slot. The dense vector SHALL have `size` equal to `settings.embedding_dimensions` and `distance` set to Cosine.

When the active sparse backend is `bm25`, the sparse slot SHALL be configured with `SparseVectorParams(modifier=Modifier.IDF)` and the existing BM25 lifecycle rules SHALL continue to apply. When the active sparse backend is `bge_m3`, the collection SHALL still expose the same sparse retrieval slot name, but the active sparse backend metadata (`backend`, `model_name`, `contract_version`) SHALL become part of the index contract and SHALL be validated before the collection is reused.

`ensure_collection()` SHALL inspect existing indexed payload metadata page-by-page until the collection is exhausted or a mismatch is found. If the inspected points show a contract different from the requested sparse backend, if the fields are missing such that compatibility cannot be proven, or if inspected points contain inconsistent values across `sparse_backend`, `sparse_model`, and `sparse_contract_version`, the method SHALL raise `CollectionSchemaMismatchError` with a message that reindexing is required.

If the active sparse backend metadata is incompatible with the existing indexed state, the service SHALL fail explicitly with `CollectionSchemaMismatchError` and SHALL require reindexing. The system SHALL NOT silently reuse a collection built under a different sparse backend contract.

#### Scenario: BM25 backend creates collection with dense and BM25 sparse configuration

- **WHEN** `ensure_collection()` is called with `sparse_backend=bm25` and no collection exists
- **THEN** a collection SHALL be created with vectors config containing `"dense"`
- **AND** the collection SHALL include sparse vectors config containing `"bm25"` with `SparseVectorParams(modifier=Modifier.IDF)`

#### Scenario: Existing BM25-compatible collection is reused idempotently

- **WHEN** `ensure_collection()` is called with `sparse_backend=bm25`
- **AND** the collection already exists with matching dense dimensions and valid BM25 sparse configuration
- **THEN** the method SHALL return without recreating the collection

#### Scenario: Sparse backend contract mismatch requires explicit reindex

- **WHEN** `ensure_collection()` is called with `sparse_backend=bge_m3`
- **AND** the existing collection or indexed payload metadata indicates the active index contract was created for `bm25`
- **THEN** the method SHALL raise `CollectionSchemaMismatchError`
- **AND** the error SHALL state that sparse backend compatibility could not be proven and reindexing is required

#### Scenario: Dense dimension mismatch remains a hard error

- **WHEN** the collection exists with a `"dense"` vector size that differs from `settings.embedding_dimensions`
- **THEN** `ensure_collection()` SHALL raise `CollectionSchemaMismatchError`
- **AND** the method SHALL NOT silently recreate the collection for this mismatch

---

### Requirement: Point upsert with named vector and payload

The `upsert_chunks()` method SHALL accept a list of point data and upsert them to Qdrant. Each point SHALL have: `id` (chunk UUID from PostgreSQL, string format), a vector dict containing `"dense"` (float vector) and the active sparse representation in the `"bm25"` sparse slot, and a payload containing `snapshot_id`, `source_id`, `chunk_id`, `document_version_id`, `agent_id`, `knowledge_base_id`, `text_content`, `chunk_index`, `token_count`, `anchor_page`, `anchor_chapter`, `anchor_section`, `anchor_timecode`, `source_type`, `language`, `status`, `enriched_summary`, `enriched_keywords`, `enriched_questions`, `enriched_text`, `enrichment_model`, `enrichment_pipeline_version`, `parent_id`, `parent_text_content`, `parent_token_count`, `parent_anchor_page`, `parent_anchor_chapter`, `parent_anchor_section`, `parent_anchor_timecode`, `sparse_backend`, `sparse_model`, and `sparse_contract_version`.

For multi-scope filtering, the current product model uses `agent_id` and `knowledge_base_id` as the required scope identifiers. S9-03 does not introduce separate `tenant_id` or `project_id` payload fields, so search/filter logic MUST continue to scope by `agent_id` and `knowledge_base_id`.

The sparse vector input SHALL use the point `bm25_text` property. That property SHALL resolve to `enriched_text` when available and fall back to `text_content` otherwise.

- For `bm25`, the sparse slot SHALL contain a `Document(model="Qdrant/bm25", text=point.bm25_text, options=Bm25Config(language=self.bm25_language))`.
- For `bge_m3`, the sparse slot SHALL contain the sparse indices/values returned by the external sparse provider for `point.bm25_text`.

The `text_content` payload field SHALL continue to store the original chunk text used for answer context and citations. The payload SHALL always record which sparse backend created the indexed sparse artifacts.

#### Scenario: BM25 backend upserts points with BM25 Document in sparse slot

- **WHEN** `upsert_chunks()` is called with `sparse_backend=bm25`
- **THEN** each point SHALL contain `"dense"` and `"bm25"` in the vector dict
- **AND** the `"bm25"` value SHALL be a Qdrant `Document` built from `point.bm25_text`
- **AND** the payload SHALL include `sparse_backend="bm25"`, `sparse_model="Qdrant/bm25"`, and a non-empty `sparse_contract_version`

#### Scenario: BGE-M3 backend upserts points with external sparse payload in sparse slot

- **WHEN** `upsert_chunks()` is called with `sparse_backend=bge_m3`
- **THEN** each point SHALL contain `"dense"` and `"bm25"` in the vector dict
- **AND** the `"bm25"` value SHALL be built from the external sparse provider output for `point.bm25_text`
- **AND** the payload SHALL include `sparse_backend="bge_m3"`, `sparse_model`, and a non-empty `sparse_contract_version`

#### Scenario: Sparse input uses enriched_text when available

- **WHEN** a chunk has `enriched_text` populated
- **THEN** the active sparse provider SHALL receive `enriched_text` as the sparse input text
- **AND** the dense embedding input SHALL remain aligned with that same enriched text source

#### Scenario: Sparse input falls back to original text when unenriched

- **WHEN** a chunk has no `enriched_text`
- **THEN** the active sparse provider SHALL receive `text_content` as the sparse input text
- **AND** behavior SHALL remain identical to the pre-enrichment text-selection fallback

---

## ADDED Requirements

### Requirement: Sparse backend metadata is auditable in indexed payloads

Every indexed child point SHALL record the sparse backend metadata that produced its sparse representation. This metadata SHALL be carried in the point payload as `sparse_backend`, `sparse_model`, and `sparse_contract_version`.

These fields SHALL be used for diagnostics, operational inspection, and provider-contract validation. They SHALL NOT be treated as user-facing content. Their absence on an existing index SHALL be treated as an inability to prove compatibility for provider-switched reuse.

#### Scenario: Indexed payload records sparse backend metadata

- **WHEN** a chunk is upserted to Qdrant
- **THEN** its payload SHALL include `sparse_backend`, `sparse_model`, and `sparse_contract_version`

#### Scenario: Missing sparse backend metadata blocks provider-switched reuse

- **WHEN** the active sparse backend is changed
- **AND** the existing indexed state lacks sufficient sparse metadata to prove compatibility
- **THEN** the service SHALL fail explicitly and require reindexing

---

## Test Coverage

### CI tests (deterministic, mocked external services)

The following stable behavior MUST be covered by CI tests before archive:

- QdrantService unit tests for provider-aware collection validation
- QdrantService unit tests for provider-aware point upsert and sparse metadata payload fields
- QdrantService unit tests verifying explicit failure on sparse backend contract mismatch
- QdrantService unit tests verifying enriched-text sparse input selection still works
- Integration tests proving BM25-backed collection behavior remains stable
- Integration tests proving a provider switch requires an explicit reindex rather than silent reuse
