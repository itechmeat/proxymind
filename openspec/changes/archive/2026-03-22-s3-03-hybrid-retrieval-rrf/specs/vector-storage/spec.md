## MODIFIED Requirements

### Requirement: QdrantService method rename and scope filter refactoring

The existing `search()` method SHALL be renamed to `dense_search()`. The method signature and behavior SHALL remain unchanged. The inline scope filter construction inside `dense_search()` SHALL be refactored to use the existing `_build_scope_filter()` helper for consistency with `keyword_search()` and the new `hybrid_search()`. This rename is an internal same-change migration inside the repository, not a staged compatibility layer with a deprecated wrapper.

This establishes symmetric naming across all search methods: `dense_search()`, `keyword_search()`, `hybrid_search()`.

#### Scenario: dense_search is callable with same interface as former search

- **WHEN** `dense_search()` is called with `vector`, `snapshot_id`, `agent_id`, `knowledge_base_id`, `limit`, and `score_threshold`
- **THEN** behavior SHALL be identical to the former `search()` method
- **AND** the payload filter SHALL be constructed via `_build_scope_filter()` (not inline)

#### Scenario: dense_search filters by scope using shared helper

- **WHEN** `dense_search()` is called with `snapshot_id`, `agent_id`, and `knowledge_base_id`
- **THEN** the scope filter SHALL be built by `_build_scope_filter(snapshot_id, agent_id, knowledge_base_id)`
- **AND** the filter SHALL be identical to what `keyword_search()` and `hybrid_search()` produce for the same arguments

#### Scenario: Existing callers of search() are updated to dense_search()

- **WHEN** any code previously called `qdrant_service.search()`
- **THEN** it SHALL be updated to call `qdrant_service.dense_search()` with the same arguments
- **AND** all existing tests referencing `search()` SHALL be updated to reference `dense_search()`

---

### Requirement: Score semantics change

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

## ADDED Requirements

### Requirement: BM25 modifier validation in _has_bm25_sparse_vector

The `_has_bm25_sparse_vector()` method SHALL validate not only the presence of the `"bm25"` sparse vector in the collection configuration but also that its modifier equals `Modifier.IDF`. A collection with a `"bm25"` sparse vector configured with a modifier other than `Modifier.IDF` SHALL be treated as missing the required BM25 configuration and SHALL trigger collection recreation via the existing race-safe delete-and-recreate path in `ensure_collection()`.

#### Scenario: Collection with correct BM25 modifier passes validation

- **WHEN** `_has_bm25_sparse_vector()` is called and the collection has `"bm25"` sparse vector with `Modifier.IDF`
- **THEN** the method SHALL return `True`

#### Scenario: Collection with incorrect BM25 modifier fails validation

- **WHEN** `_has_bm25_sparse_vector()` is called and the collection has `"bm25"` sparse vector with a modifier other than `Modifier.IDF`
- **THEN** the method SHALL return `False`
- **AND** `ensure_collection()` SHALL treat the collection as missing the required BM25 configuration and trigger recreation
