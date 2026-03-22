## Story

**S3-02: BM25 sparse vectors** — Qdrant BM25 sparse vectors (language from `.env`, Snowball stemmer) indexed alongside dense as named vectors.

**Verification criteria** (from `docs/plan.md`):
- Keyword search via Qdrant returns results
- Stemmer language matches `.env`

**Stable behavior requiring test coverage:** BM25 collection schema creation, upsert with both dense and sparse vectors, keyword search with scope filtering, stemming correctness.

## Why

The retrieval pipeline currently supports only dense (semantic) search via Gemini Embedding 2. Keyword/term-based search is missing — queries with exact terms or proper nouns may not surface relevant chunks. BM25 sparse vectors are the prerequisite for S3-03 (hybrid retrieval + RRF fusion), which combines semantic and keyword search for better recall.

## What Changes

- Extend the Qdrant collection schema with a named sparse vector `"bm25"` using `SparseVectorParams(modifier=Modifier.IDF)`
- Modify `QdrantService._upsert_points` to include BM25 `Document` alongside the dense vector at upsert time — Qdrant tokenizes text server-side via Snowball stemmer
- Add `QdrantService.keyword_search()` method for BM25-only queries
- Add `POST /api/admin/search/keyword` endpoint for verification and diagnostics
- Bump `qdrant-client` from `>=1.14.1` to `>=1.16.0` (BM25 Document API requirement)
- `ensure_collection` auto-recreates the collection when the `bm25` sparse vector is missing (race-safe); dense dimension mismatch remains a hard error

## Capabilities

### New Capabilities

- `bm25-keyword-search`: BM25 sparse vector indexing, keyword search method, admin keyword search endpoint

### Modified Capabilities

- `vector-storage`: Collection schema gains a `"bm25"` sparse vector; `upsert_chunks` now includes BM25 Document; `ensure_collection` detects and auto-recreates on missing sparse vector

## Impact

- **Code:** `backend/app/services/qdrant.py`, `backend/app/api/admin.py`, `backend/app/api/dependencies.py`, `backend/app/api/schemas.py`, `backend/app/main.py`, `backend/app/workers/main.py`
- **Dependencies:** `qdrant-client>=1.16.0` (bump from 1.14.1)
- **APIs:** New `POST /api/admin/search/keyword`
- **Data:** Existing Qdrant collections without `bm25` sparse vector will be auto-recreated on startup (requires re-ingest)
- **No changes to:** ingestion worker task, RetrievalService (dense-only until S3-03), Chat API, config settings (bm25_language already exists)
