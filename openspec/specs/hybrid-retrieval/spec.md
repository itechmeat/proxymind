## Purpose

Hybrid retrieval capability combining dense (Gemini Embedding 2) and sparse (BM25) vector search with Reciprocal Rank Fusion via Qdrant's native RRF. Provides a single `hybrid_search` method on QdrantService and wires it into the retrieval pipeline via RetrievalService.

## Requirements

### Requirement: hybrid_search method on QdrantService

The `QdrantService` SHALL provide an `async hybrid_search()` method that performs dual-vector retrieval using Qdrant's native RRF fusion in a single round-trip. The method SHALL accept `text` (str), `vector` (list[float]), `snapshot_id` (UUID), `agent_id` (UUID), `knowledge_base_id` (UUID), `limit` (int), and `score_threshold` (float | None). The method SHALL construct a Qdrant query with two `Prefetch` legs (dense and sparse), fuse them with `RrfQuery(rrf=Rrf(k=RRF_K))`, apply a scope filter via `_build_scope_filter()`, and return `list[RetrievedChunk]`.

The dense prefetch leg SHALL query the `"dense"` named vector with `filter=scope_filter`, `limit=limit * PREFETCH_MULTIPLIER`, and `score_threshold=score_threshold` (when not None). The sparse prefetch leg SHALL query the `"bm25"` named sparse vector using `_build_bm25_document(text)` with `filter=scope_filter`, `limit=limit * PREFETCH_MULTIPLIER`, and no score threshold. The final query SHALL use `RrfQuery(rrf=Rrf(k=RRF_K))` with `limit=limit` and `query_filter=scope_filter`. Results SHALL be mapped via the existing `_to_retrieved_chunk()` helper.

When `limit` is less than or equal to 0, the method SHALL short-circuit and return an empty list without querying Qdrant.

#### Scenario: Hybrid search returns results combining dense and sparse

- **WHEN** `hybrid_search()` is called with text, vector, snapshot_id, agent_id, knowledge_base_id, and limit=5
- **THEN** the method SHALL construct two Prefetch legs: one for `"dense"` named vector, one for `"bm25"` named sparse vector
- **AND** both Prefetch legs SHALL apply the same scope filter before fusion
- **AND** the final query SHALL use `RrfQuery(rrf=Rrf(k=RRF_K))` with limit=5
- **AND** the method SHALL return up to 5 `RetrievedChunk` results ordered by RRF rank score descending

#### Scenario: Dense score_threshold filters dense leg before fusion

- **WHEN** `hybrid_search()` is called with `score_threshold=0.5`
- **THEN** the dense prefetch leg SHALL include `score_threshold=0.5`
- **AND** only dense results with cosine similarity >= 0.5 SHALL enter the RRF fusion
- **AND** the sparse prefetch leg SHALL NOT have a score threshold

#### Scenario: score_threshold=None omits dense filtering

- **WHEN** `hybrid_search()` is called with `score_threshold=None`
- **THEN** the dense prefetch leg SHALL NOT include a score_threshold parameter
- **AND** all top-N dense results SHALL enter the RRF fusion regardless of their similarity score

#### Scenario: Sparse-only results returned when dense leg is empty after threshold

- **WHEN** `hybrid_search()` is called with a high `score_threshold` that filters out all dense results
- **AND** the sparse leg returns matching chunks via BM25
- **THEN** the method SHALL return the BM25-only hits through RRF
- **AND** the result list SHALL NOT be empty

#### Scenario: Dense-only results returned when sparse leg finds nothing

- **WHEN** `hybrid_search()` is called and the sparse BM25 leg returns no matches
- **AND** the dense leg returns matching chunks
- **THEN** the method SHALL return the dense-only results through RRF
- **AND** the result list SHALL NOT be empty

#### Scenario: Same chunk in both legs appears once in results

- **WHEN** a chunk matches both the dense and sparse prefetch legs
- **THEN** the chunk SHALL appear exactly once in the final result list (deduplication by Qdrant RRF)

#### Scenario: Hybrid search filters by snapshot_id scope

- **WHEN** `hybrid_search()` is called with a specific snapshot_id, agent_id, and knowledge_base_id
- **THEN** the scope filter SHALL include conditions for all three fields via `_build_scope_filter()`
- **AND** only chunks matching the scope SHALL be returned

#### Scenario: Hybrid search retries on transient connection errors

- **WHEN** the Qdrant query fails with a connection error on the first attempt and succeeds on the second
- **THEN** the method SHALL succeed without raising an exception

#### Scenario: Hybrid search fails after max retries

- **WHEN** the Qdrant query fails with a connection error on all 3 attempts
- **THEN** the method SHALL raise an exception after exhausting retries

#### Scenario: Hybrid search with keyword match ranks chunk higher than dense-only

- **WHEN** a chunk contains an exact keyword match for the query text
- **AND** the same chunk also has moderate dense similarity
- **THEN** the chunk SHALL rank higher in hybrid search results than it would in dense-only search (because it scores in both legs)

#### Scenario: Hybrid search result contains correct payload fields

- **WHEN** `hybrid_search()` returns results
- **THEN** each `RetrievedChunk` SHALL contain `chunk_id`, `source_id`, `text_content`, `score`, and `anchor_metadata`
- **AND** `score` SHALL represent an RRF rank score (not cosine similarity)

#### Scenario: Prefetch limit uses multiplier

- **WHEN** `hybrid_search()` is called with `limit=5`
- **THEN** both the dense and sparse prefetch legs SHALL request `limit * PREFETCH_MULTIPLIER` candidates (10 with default multiplier of 2)
- **AND** the final fusion query SHALL request `limit` results (5)

#### Scenario: Zero limit short-circuits to empty list

- **WHEN** `hybrid_search()` is called with `limit<=0`
- **THEN** the method SHALL return an empty list
- **AND** no Qdrant query SHALL be executed

---

### Requirement: RetrievalService uses hybrid search

The `RetrievalService.search()` method SHALL call `qdrant_service.hybrid_search()` instead of the former `search()` method, passing both the raw query text and the dense embedding vector. It SHALL map `top_n` to `hybrid_search(limit=...)`: when `top_n is None`, it SHALL pass the configured retrieval default; otherwise it SHALL pass the explicit `top_n` value. It SHALL map `min_dense_similarity` to `hybrid_search(score_threshold=...)`. The method signature of `RetrievalService.search()` SHALL remain unchanged — `ChatService` is not affected.

#### Scenario: search() passes both text and vector to hybrid_search

- **WHEN** `RetrievalService.search()` is called with a query string
- **THEN** the method SHALL generate a dense embedding via `EmbeddingService`
- **AND** the method SHALL call `qdrant_service.hybrid_search()` with `text=query` and `vector=embedding`

#### Scenario: search() passes min_dense_similarity as score_threshold

- **WHEN** `RetrievalService.search()` is called
- **THEN** the method SHALL pass the configured `min_dense_similarity` value as the `score_threshold` parameter to `hybrid_search()`

#### Scenario: search() maps top_n to hybrid_search limit

- **WHEN** `RetrievalService.search()` is called with `top_n=None`
- **THEN** the method SHALL pass the configured retrieval default as `limit` to `hybrid_search()`
- **AND** `text=query` and `vector=embedding` SHALL still be passed

- **WHEN** `RetrievalService.search()` is called with `top_n=7`
- **THEN** the method SHALL pass `limit=7` to `hybrid_search()`

#### Scenario: RetrievalService signature is unchanged

- **WHEN** `RetrievalService.search()` is called by `ChatService`
- **THEN** the method signature SHALL accept `query` (str), `snapshot_id` (UUID), and `top_n` (int | None)
- **AND** no changes to calling code SHALL be required

---

### Requirement: RRF constants

The module `qdrant.py` SHALL define two module-level constants: `PREFETCH_MULTIPLIER = 2` (candidate pool multiplier for each prefetch leg) and `RRF_K = 60` (standard RRF k parameter). `hybrid_search()` SHALL use `RrfQuery(rrf=Rrf(k=RRF_K))` with the explicit k constant, not `FusionQuery(fusion=Fusion.RRF)`.

#### Scenario: PREFETCH_MULTIPLIER is used in both prefetch legs

- **WHEN** `hybrid_search()` constructs prefetch queries
- **THEN** both the dense and sparse legs SHALL use `limit * PREFETCH_MULTIPLIER` as their prefetch limit

#### Scenario: RRF_K is used in the fusion query

- **WHEN** `hybrid_search()` constructs the fusion query
- **THEN** it SHALL use `RrfQuery(rrf=Rrf(k=RRF_K))` where `RRF_K = 60`
- **AND** it SHALL NOT use `FusionQuery(fusion=Fusion.RRF)`

---

## Test Coverage

### CI tests (deterministic, mocked external services)

- **hybrid_search unit tests** (`backend/tests/unit/services/test_qdrant.py`): mock `AsyncQdrantClient`; verify Prefetch structure contains both dense and sparse legs with correct parameters; verify `RrfQuery(rrf=Rrf(k=60))` is used (not FusionQuery); verify scope filter is applied via `_build_scope_filter()`; verify `score_threshold` is passed to dense prefetch leg when set and omitted when None; verify `limit * PREFETCH_MULTIPLIER` is used for prefetch limits; verify results are mapped to `RetrievedChunk`; verify zero limit short-circuits.
- **RetrievalService unit tests** (`backend/tests/unit/test_retrieval_service.py`): mock `hybrid_search`; verify both `text` and `vector` are passed; verify `min_dense_similarity` is passed as `score_threshold`.

### Integration tests (real Qdrant)

- **Hybrid roundtrip** (`backend/tests/integration/test_qdrant_roundtrip.py`): upsert chunks with both dense and BM25 vectors, call `hybrid_search`, verify results are returned with correct payload fields.
- **Snapshot filtering with hybrid**: upsert chunks with different snapshot_ids, verify `hybrid_search` scoped by snapshot_id excludes chunks from other snapshots.
- **Keyword boost**: upsert chunks where one contains an exact keyword match; verify hybrid search ranks it higher than dense-only search would (deterministic fixture with controlled vectors).
- **Sparse-only results**: set a high `score_threshold` that filters all dense results; verify BM25-only hits are still returned through RRF.
- **Dense-only results**: upsert a chunk whose text does not match the BM25 query terms; verify dense-only results pass through RRF.
- **Dedup**: upsert a chunk that matches both dense and sparse legs; verify it appears exactly once in results.
