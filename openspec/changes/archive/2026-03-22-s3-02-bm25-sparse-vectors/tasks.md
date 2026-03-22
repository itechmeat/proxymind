# S3-02: BM25 Sparse Vectors — Tasks

**Detailed implementation plan:** `docs/superpowers/plans/2026-03-22-s3-02-bm25-sparse-vectors.md`

Each task below maps to a task in the detailed plan. Follow the plan for exact code, commands, and expected outputs.

## Tasks

- [x] **Task 1: Bump qdrant-client dependency**
  Bump `qdrant-client>=1.14.1` to `>=1.16.0` in `backend/pyproject.toml`. Run `uv lock`. Verify `models.Bm25Config` and `models.Document` import successfully.

- [x] **Task 2: Extend QdrantService constructor and ensure_collection for BM25**
  Add `bm25_language` param to constructor. Extend `ensure_collection` to create collection with `sparse_vectors_config={"bm25": SparseVectorParams(modifier=Modifier.IDF)}`. Auto-recreate (race-safe) when existing collection lacks BM25 sparse vector. Dense dimension mismatch remains a hard error. Log configured language at startup. Write unit tests first (TDD): collection creation with sparse vector, recreate on missing BM25, idempotent when schema matches. Update all existing QdrantService tests to pass `bm25_language`.
  Files: `backend/app/services/qdrant.py`, `backend/tests/unit/services/test_qdrant.py`

- [x] **Task 3: Add BM25 Document to upsert**
  Modify `_upsert_points` to include `models.Document(text=point.text_content, model="Qdrant/bm25", options=Bm25Config(language=self._bm25_language))` alongside the dense vector. Write unit test first (TDD): verify vector dict includes both "dense" and "bm25" Document with correct model, text, and language.
  Files: `backend/app/services/qdrant.py`, `backend/tests/unit/services/test_qdrant.py`

- [x] **Task 4: Add keyword_search method to QdrantService**
  Add `keyword_search(text, snapshot_id, agent_id, knowledge_base_id, limit)` that queries the "bm25" sparse vector using Document API with scope filters. Returns `list[RetrievedChunk]`. Retry on transient errors. Write unit tests first (TDD): query structure, empty results, retry on transient error.
  Files: `backend/app/services/qdrant.py`, `backend/tests/unit/services/test_qdrant.py`

- [x] **Task 5: Pass bm25_language to QdrantService in worker and API startup**
  Update `_create_qdrant_service` in `main.py` and QdrantService construction in `workers/main.py` to pass `settings.bm25_language`. Run existing tests to verify no regressions.
  Files: `backend/app/main.py`, `backend/app/workers/main.py`

- [x] **Task 6: Add keyword search Admin API endpoint**
  Add `POST /api/admin/search/keyword` endpoint. Request: query (required), snapshot_id (optional → active), agent_id/knowledge_base_id (optional → defaults), limit. Response: results with nested anchor, query, language, total. No active snapshot → 422. Add dependency getter for QdrantService. Add request/response Pydantic schemas. Write unit tests first (TDD): 200 with results, empty query → 422, no active snapshot → 422.
  Files: `backend/app/api/admin.py`, `backend/app/api/dependencies.py`, `backend/app/api/schemas.py`, `backend/tests/unit/test_admin_keyword_search.py`

- [x] **Task 7: Integration tests with real Qdrant**
  Add integration tests: keyword search finds chunks by text, scoped by snapshot_id, Snowball stemming works ("running" matches "runs"), collection recreation on missing sparse vector. Update all existing integration tests to pass `bm25_language`.
  Files: `backend/tests/integration/test_qdrant_roundtrip.py`

- [x] **Task 8: Final verification**
  Run full test suite (`uv run pytest tests/ -v`). Run linter (`uv run ruff check app/ tests/`). Optionally verify manually with curl if services are running.

## Verification Criteria

From `docs/plan.md` S3-02:
- [x] Keyword search via Qdrant returns results
- [x] Stemmer language matches `.env` (`BM25_LANGUAGE`)
