## MODIFIED Requirements

### Requirement: keyword_search method

The `QdrantService` SHALL provide a `keyword_search()` method that queries the active sparse retrieval slot for keyword-style diagnostics. The method SHALL accept `text` (str), `snapshot_id` (UUID), `agent_id` (UUID), `knowledge_base_id` (UUID), and `limit` (int, default 10). The active sparse backend is not a method parameter in S9-03; it is resolved from the `QdrantService` instance attribute `sparse_backend`, which is wired at startup from installation configuration. The method SHALL apply the same payload filter on `snapshot_id`, `agent_id`, and `knowledge_base_id` and SHALL return `list[RetrievedChunk]`.

An "external sparse provider" in this requirement means an injected `SparseProvider` implementation that returns a sparse vector structure compatible with Qdrant, specifically `SparseVector(indices: number[], values: number[])`, for the requested query text.

- For `bm25`, the query SHALL use `Document(model="Qdrant/bm25", text=..., options=Bm25Config(language=self.bm25_language))`.
- For `bge_m3`, the query SHALL use the sparse indices/values returned by the external sparse provider for the query text.

The method SHALL keep the same retry behavior for transient Qdrant errors.

#### Scenario: keyword_search with BM25 backend uses BM25 sparse query

- **WHEN** `keyword_search()` is called while the service is configured with `sparse_backend=bm25`
- **THEN** the query SHALL use a BM25 `Document` built from the query text
- **AND** results SHALL be scoped by `snapshot_id`, `agent_id`, and `knowledge_base_id`

#### Scenario: keyword_search with BGE-M3 backend uses external sparse query

- **WHEN** `keyword_search()` is called while the service is configured with `sparse_backend=bge_m3`
- **THEN** the query SHALL use the external sparse provider output for the query text
- **AND** results SHALL be scoped by `snapshot_id`, `agent_id`, and `knowledge_base_id`

#### Scenario: keyword_search remains retryable on transient errors

- **WHEN** the sparse query fails with a transient Qdrant error and then succeeds on retry
- **THEN** the method SHALL succeed without changing its public contract

---

### Requirement: Admin keyword search endpoint

The system SHALL provide a `POST /api/admin/search/keyword` endpoint for sparse-leg diagnostics. The request body SHALL continue accepting `query`, `snapshot_id`, `agent_id`, `knowledge_base_id`, and `limit`. Requests that include client-set `sparse_backend` or `sparse_model` fields SHALL be rejected with a 422 validation error in S9-03.

The response SHALL include:

- `results`
- `query`
- `language`
- `bm25_language`
- `sparse_backend`
- `sparse_model`
- `total`

This endpoint SHALL keep its current routing and snapshot-default behavior, but it SHALL no longer imply that sparse diagnostics are always BM25-backed. The response SHALL explicitly identify which sparse backend produced the diagnostic behavior. `sparse_backend` and `sparse_model` are derived from the active `QdrantService` instance wired at startup, not from request parameters or per-snapshot overrides. `language` is the active sparse-language signal and SHALL be `null` when `bge_m3` is active. `bm25_language` is always the install-level BM25 stemming configuration.

#### Scenario: Keyword diagnostics expose BM25 backend metadata

- **WHEN** the endpoint is called while `sparse_backend=bm25`
- **THEN** the response SHALL include `sparse_backend="bm25"`
- **AND** the response SHALL include the BM25 sparse model identifier
- **AND** the response SHALL include both `language` and `bm25_language`

#### Scenario: Keyword diagnostics expose BGE-M3 backend metadata

- **WHEN** the endpoint is called while `sparse_backend=bge_m3`
- **THEN** the response SHALL include `sparse_backend="bge_m3"`
- **AND** the response SHALL include the configured BGE-M3 sparse model identifier
- **AND** the response SHALL include `language=null` and the install-level `bm25_language`

#### Scenario: Existing snapshot-default behavior remains unchanged

- **WHEN** the endpoint is called without `snapshot_id`
- **THEN** it SHALL continue resolving the active snapshot via SnapshotService
- **AND** if no active snapshot exists, it SHALL continue returning 422

#### Scenario: Client-supplied sparse fields are rejected

- **WHEN** the endpoint request includes `sparse_backend` or `sparse_model`
- **THEN** the endpoint SHALL return 422
- **AND** the response SHALL describe a validation error for the forbidden field

---

## Test Coverage

### CI tests (deterministic, mocked external services)

The following stable behavior MUST be covered by CI tests before archive:

- `keyword_search()` unit tests for BM25-backed sparse diagnostics
- `keyword_search()` unit tests for BGE-M3-backed sparse diagnostics
- admin endpoint tests proving `KeywordSearchResponse` includes `language`, `bm25_language`, `sparse_backend`, and `sparse_model` with the correct resolution logic
- integration tests proving keyword diagnostics remain scoped while exposing active sparse backend metadata
