# S3-03: Hybrid Retrieval + RRF — Tasks

## 1. QdrantService: Rename and refactor dense_search

- [x] 1.1 Rename `search()` to `dense_search()` in `backend/app/services/qdrant.py`. Signature and behavior unchanged.
- [x] 1.2 Refactor `dense_search()` to use `_build_scope_filter()` instead of inline filter construction.
- [x] 1.3 Update all call sites: `RetrievalService` (`backend/app/services/retrieval.py`) to call `dense_search()` (temporary — will switch to `hybrid_search` in task group 4).
- [x] 1.4 Update all unit test references: `backend/tests/unit/services/test_qdrant.py` (qdrant service tests) and `backend/tests/unit/test_retrieval_service.py` (retrieval mock targets).
- [x] 1.5 Update integration test references: `backend/tests/integration/test_qdrant_roundtrip.py` — rename `service.search()` calls to `service.dense_search()`.
- [x] 1.6 Run tests (`uv run pytest tests/ -v`) to confirm rename is clean with no regressions across all test suites.

## 2. QdrantService: Add hybrid_search method

- [x] 2.1 Add module-level constants `PREFETCH_MULTIPLIER = 2` and `RRF_K = 60` in `backend/app/services/qdrant.py`.
- [x] 2.2 Implement `hybrid_search(*, text, vector, snapshot_id, agent_id, knowledge_base_id, limit, score_threshold)` returning `list[RetrievedChunk]`.
- [x] 2.3 Add short-circuit: if `limit <= 0`, return `[]` without querying Qdrant.
- [x] 2.4 Dense prefetch leg: query `"dense"` named vector, `limit=limit * PREFETCH_MULTIPLIER`, `score_threshold=score_threshold` (when not None).
- [x] 2.5 Sparse prefetch leg: query `"bm25"` named sparse vector via `_build_bm25_document(text)`, `limit=limit * PREFETCH_MULTIPLIER`, no score threshold.
- [x] 2.6 Final query: `RrfQuery(rrf=Rrf(k=RRF_K))`, `limit=limit`, `query_filter=scope_filter` via `_build_scope_filter()`.
- [x] 2.7 Map results via existing `_to_retrieved_chunk()`.

## 3. QdrantService: Unit tests for hybrid_search

- [x] 3.1 `test_hybrid_search_builds_correct_prefetch` — mock `AsyncQdrantClient`, verify Prefetch contains both dense and sparse legs with correct parameters.
- [x] 3.2 `test_hybrid_search_uses_rrf_query_with_explicit_k` — verify `RrfQuery(rrf=Rrf(k=60))` is used, not `FusionQuery`.
- [x] 3.3 `test_hybrid_search_applies_score_threshold` — dense leg includes `score_threshold` when set, omits when None.
- [x] 3.4 `test_hybrid_search_respects_limit` — verify `limit * PREFETCH_MULTIPLIER` on prefetch legs, `limit` on final query.
- [x] 3.5 `test_hybrid_search_applies_scope_filter` — scope filter built via `_build_scope_filter()` and applied to the query.
- [x] 3.6 `test_hybrid_search_retries_on_transient_error` — first attempt fails with connection error, second succeeds.
- [x] 3.7 `test_hybrid_search_zero_limit_short_circuits` — limit=0 returns `[]` without Qdrant call.
- [x] 3.8 Run unit tests to confirm all pass.

## 4. RetrievalService: Switch to hybrid

- [x] 4.1 Update `RetrievalService.search()` in `backend/app/services/retrieval.py` to call `qdrant_service.hybrid_search()` with `text=query` and `vector=embedding`.
- [x] 4.2 Pass configured `min_dense_similarity` as `score_threshold` parameter.
- [x] 4.3 Update existing unit tests in `backend/tests/unit/test_retrieval_service.py` to mock `hybrid_search` instead of `dense_search`.
- [x] 4.4 Add `test_search_calls_hybrid_search_with_text_and_vector` — verify both text and vector are passed.
- [x] 4.5 Run unit tests to confirm all pass.

## 5. Integration tests

- [x] 5.1 `test_hybrid_search_returns_results` — upsert chunks with both dense and BM25 vectors, call `hybrid_search`, verify results returned with correct payload fields.
- [x] 5.2 `test_hybrid_search_filters_by_snapshot` — upsert chunks with different snapshot_ids, verify scope filtering works.
- [x] 5.3 `test_hybrid_search_keyword_boost` — chunk with exact keyword match ranks higher via hybrid than dense-only (deterministic fixture with controlled vectors).
- [x] 5.4 `test_hybrid_search_sparse_only_results` — high `score_threshold` filters all dense results, BM25-only hits still returned through RRF.
- [x] 5.5 `test_hybrid_search_dense_only_results` — sparse leg returns nothing, dense-only results pass through RRF.
- [x] 5.6 `test_hybrid_search_dedup_same_chunk_both_legs` — same chunk matched by both legs appears exactly once in results.
- [x] 5.7 Run integration tests to confirm all pass.

## 6. Final verification

- [x] 6.1 Run full CI test suite (`uv run pytest tests/ -v`).
- [x] 6.2 Run linter (`uv run ruff check app/ tests/`).
- [x] 6.3 Verify no regressions in existing tests (dense_search, keyword_search, retrieval, chat, prompt assembly).
- [x] 6.4 Self-review against `docs/development.md`.

## Verification Criteria

From `docs/plan.md` S3-03:
- [x] Query with exact keyword match ranks the matching chunk higher via hybrid than dense-only (deterministic fixture)
- [x] Filtering by snapshot works with hybrid search
