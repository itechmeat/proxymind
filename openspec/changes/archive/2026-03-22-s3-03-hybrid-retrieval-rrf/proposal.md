## Story

S3-03: Hybrid retrieval + RRF

Dense (query-oriented) + sparse (BM25) search, Reciprocal Rank Fusion, min_dense_similarity filtering before fusion. Scoped by snapshot_id + tenant-ready fields.

Outcome: retrieval combines semantic and keyword search.

Verification: a query containing an exact keyword match ranks the matching chunk higher via hybrid than dense-only; filtering by snapshot_id works correctly.

## Why

S3-02 added BM25 sparse vectors alongside dense vectors in Qdrant, but retrieval still uses dense-only search. Users searching for specific terms (names, product codes, acronyms) get suboptimal results because cosine similarity alone cannot capture exact lexical matches. Combining both signals through RRF produces more robust ranking without requiring manual weight tuning between dense and sparse scores.

## What Changes

- Rename `QdrantService.search()` to `QdrantService.dense_search()` to clarify its role as one leg of hybrid retrieval. Refactor internals to use the existing `_build_scope_filter()`. This is an in-repo service rename completed atomically within the same change, not a staged public API deprecation.
- Add `QdrantService.hybrid_search()` that uses Qdrant native RRF via two Prefetch legs (dense + sparse) fused with `RrfQuery(rrf=Rrf(k=RRF_K))` with explicit k parameter (default 60).
- Apply `min_dense_similarity` as `score_threshold` on the dense Prefetch leg before fusion, so low-relevance dense results are excluded before ranking. Sparse-only results intentionally bypass this threshold — BM25 hits that have no dense match above the threshold still surface through RRF.
- Switch `RetrievalService.search()` from calling `dense_search()` to calling `hybrid_search()`, passing both the query text (for BM25) and the query embedding (for dense).
- Add module-level constants: `RRF_K = 60` (RRF k parameter) and `PREFETCH_MULTIPLIER = 2` (candidate pool multiplier for each prefetch leg).
- Add unit and integration tests for hybrid search: RRF ranking correctness, snapshot scoping, min_dense_similarity filtering, sparse-only result passthrough.

## Capabilities

### New Capabilities

- `hybrid-retrieval`: hybrid search method combining dense and sparse Prefetch legs with native RRF fusion, pre-fusion dense similarity filtering, and snapshot-scoped payload filters.

### Modified Capabilities

- `vector-storage`: QdrantService gains a renamed `dense_search()` method and a new `hybrid_search()` method. Score semantics change from raw cosine similarity to RRF rank-based scores on the hybrid path, so downstream code must treat `RetrievedChunk.score` as method-specific metadata.

## Impact

- `backend/app/services/qdrant.py` — rename `search()` to `dense_search()`, add `hybrid_search()`, add RRF constants.
- `backend/app/services/retrieval.py` — switch from `search()` to `hybrid_search()`, pass query text alongside embedding.
- Tests: new unit tests for hybrid search logic, integration tests for RRF ranking and snapshot scoping.
- NOT affected: `chat.py`, ingestion pipeline, config, workers, frontend, database models.
