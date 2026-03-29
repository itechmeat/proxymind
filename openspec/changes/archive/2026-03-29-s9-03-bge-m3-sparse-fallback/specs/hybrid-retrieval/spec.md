## MODIFIED Requirements

### Requirement: hybrid_search method on QdrantService

The `QdrantService` SHALL provide an `async hybrid_search()` method that performs dual-vector retrieval using Qdrant's native RRF fusion in a single round-trip. The method SHALL accept `text` (str), `vector` (list[float]), `snapshot_id` (UUID), `agent_id` (UUID), `knowledge_base_id` (UUID), `limit` (int), and `score_threshold` (float | None). The active sparse backend is resolved from the `QdrantService` instance and injected `SparseProvider`, not from a per-call `sparse_backend` parameter in S9-03.

The dense prefetch leg SHALL continue querying the `"dense"` named vector. The sparse prefetch leg SHALL query the active sparse retrieval slot using the active sparse provider:

- BM25 SHALL build the sparse query via `Document(model="Qdrant/bm25", text=..., options=Bm25Config(language=self.bm25_language))`
- BGE-M3 SHALL build the sparse query from the external sparse provider output for the same query text

The external sparse provider SHALL be a pluggable `SparseProvider` implementation supplied through dependency injection. Its sparse output SHALL be a Qdrant-compatible sparse vector structure, equivalent to `{indices: number[], values: number[]}`. Empty, malformed, or failed provider responses SHALL be treated as explicit operational errors; the system SHALL NOT silently fall back to BM25 or dense-only retrieval.

The final query SHALL continue using `RrfQuery(rrf=Rrf(k=RRF_K))`, the same scope filter, and the same result mapping to `RetrievedChunk`. The application-level retrieval contract SHALL remain dense + sparse + hybrid; callers SHALL NOT need provider-specific branching.

#### Scenario: Hybrid search with BM25 backend uses BM25 sparse query construction

- **WHEN** `hybrid_search()` is called while the service is configured with `sparse_backend=bm25`
- **THEN** the sparse prefetch leg SHALL use a BM25 `Document` built from the query text
- **AND** the final retrieval SHALL still fuse dense and sparse results with RRF

#### Scenario: Hybrid search with BGE-M3 backend uses external sparse query construction

- **WHEN** `hybrid_search()` is called while the service is configured with `sparse_backend=bge_m3`
- **THEN** the sparse prefetch leg SHALL use the sparse indices/values returned by the external sparse provider for the query text
- **AND** the final retrieval SHALL still fuse dense and sparse results with RRF

#### Scenario: Dense score_threshold remains dense-leg-only

- **WHEN** `hybrid_search()` is called with `score_threshold=0.5`
- **THEN** the dense prefetch leg SHALL apply `score_threshold=0.5`
- **AND** the sparse prefetch leg SHALL NOT apply that threshold

#### Scenario: Retrieval semantics stay child-first regardless of sparse backend

- **WHEN** `hybrid_search()` returns results from either sparse backend
- **THEN** ranking SHALL continue to be based on child chunks only
- **AND** parent metadata SHALL remain supporting context rather than a ranked retrieval unit

---

### Requirement: RetrievalService uses hybrid search

The `RetrievalService.search()` method SHALL continue to call `qdrant_service.hybrid_search()` and SHALL continue passing both the raw query text and the Gemini dense query embedding. The method signature of `RetrievalService.search()` SHALL remain unchanged.

Any sparse backend selection SHALL remain internal to the Qdrant service layer and startup wiring. The retrieval service SHALL NOT branch on `bm25` vs `bge_m3`.

#### Scenario: RetrievalService remains provider-agnostic

- **WHEN** `RetrievalService.search()` is called
- **THEN** it SHALL generate a Gemini dense query embedding
- **AND** it SHALL call `qdrant_service.hybrid_search()` with `text=query` and `vector=embedding`
- **AND** it SHALL NOT branch on the active sparse backend itself

#### Scenario: RetrievalService public contract is unchanged

- **WHEN** `RetrievalService.search()` is called by upstream dialogue code
- **THEN** no calling-code changes SHALL be required to support `bge_m3`

---

## Test Coverage

### CI tests (deterministic, mocked external services)

The following stable behavior MUST be covered by CI tests before archive:

- `hybrid_search()` unit tests for BM25-backed sparse query construction
- `hybrid_search()` unit tests for BGE-M3-backed sparse query construction
- `RetrievalService.search()` unit tests proving provider-agnostic behavior is preserved
- Integration coverage proving hybrid retrieval result shape stays stable while the sparse leg changes
