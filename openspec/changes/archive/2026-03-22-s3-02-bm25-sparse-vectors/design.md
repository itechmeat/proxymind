# S3-02: BM25 Sparse Vectors — Design

## Context

**Background:** ProxyMind's retrieval pipeline currently supports only dense (semantic) search via Gemini Embedding 2. Queries containing exact terms, proper nouns, or technical identifiers may not surface relevant chunks because dense vectors capture meaning, not lexical overlap. BM25 sparse vectors are the standard solution for keyword/term-based search and are a prerequisite for S3-03 (hybrid retrieval + RRF fusion).

**Current state:** The Qdrant collection `proxymind_chunks` stores a single named vector `"dense"` (COSINE, 3072 dimensions). `QdrantService.search()` performs dense-only retrieval. The `bm25_language` setting already exists in `config.py` (default `"english"`) but is only written to chunk payload as metadata — it is not used for tokenization. `qdrant-client` is pinned at `>=1.14.1`, which lacks the BM25 Document API.

**Affected circuit:** Knowledge Circuit (indexing) and a diagnostic Admin API endpoint. The Dialogue Circuit retrieval path (`RetrievalService`, Chat API) remains unchanged — it stays dense-only until S3-03.

## Goals / Non-Goals

### Goals

- Add a `"bm25"` named sparse vector to the Qdrant collection alongside the existing `"dense"` vector
- Use Qdrant server-side BM25 tokenization via the Document API (Snowball stemmer, language from `.env`)
- Include BM25 Document in every upsert alongside the dense vector
- Add `keyword_search` method to `QdrantService` for BM25-only queries
- Add `POST /api/admin/search/keyword` endpoint for verification and diagnostics
- Auto-recreate the collection when the `bm25` sparse vector is missing (with warning log)
- Bump `qdrant-client` to `>=1.16.0`

### Non-Goals

| Feature | Why excluded |
|---------|-------------|
| Hybrid search and RRF fusion | S3-03 — separate story |
| Changes to Chat API retrieval or RetrievalService | S3-03 — `search()` stays dense-only |
| BGE-M3 sparse fallback | S9-03 — evaluated only if Qdrant BM25 shows insufficient quality |
| Automated reindex after collection recreation | No reindex command exists at Phase 3; manual re-upload via Admin API |
| BM25 language auto-detection on change | Language is per-operation; changing `.env` requires manual re-ingest |

## Decisions

### D1: Collection Upgrade Strategy — Recreate in `ensure_collection`

**Chosen:** When `ensure_collection` detects the existing collection lacks the `bm25` sparse vector, it deletes and recreates with both `dense` and `bm25` vectors.

**Rationale:** Phase 3 is dev/staging with minimal data. Migration scripts or dual-collection architecture are overhead for a problem that does not exist yet. The `ensure_collection` pattern already exists and handles schema validation. Both vectors in one collection is what Qdrant recommends for multi-vector retrieval and is required for native RRF in S3-03.

**Rejected:** Separate migration CLI command (used once, becomes dead code). Separate collection for sparse (complicates retrieval, prevents Qdrant native RRF fusion).

### D2: BM25 Modifier — `Modifier.IDF`

**Chosen:** `Modifier.IDF` (Qdrant default) for BM25 sparse vector normalization.

**Rationale:** IDF is the canonical component of Okapi BM25 (TF x IDF). Without it, stop-words dominate scores and term discriminating power is lost. This is Qdrant's default — tested and optimized.

**Rejected:** `Modifier.NONE` — raw term-frequency without normalization; no reason to deviate from the standard.

### D3: Text Source for BM25 — Same `text_content` as Dense Embedding

**Chosen:** Use the same `text_content` for both dense embedding and BM25 tokenization. At upsert time, `chunk.text_content` goes to both Gemini (dense) and the Qdrant Document (sparse).

**Rationale:** Dense and sparse search the same content — one text, two vector representations. `text_content` is already in `QdrantChunkPoint`. No new data extraction needed. Matches `docs/spec.md`: "Indexing: retrieval-oriented task type (dense) + BM25 sparse vector."

**Rejected:** Separate `bm25_text` field with preprocessing — duplicates text in payload (+50-100% storage), complicates pipeline. Snowball tokenizer already handles lowercasing and stemming.

### D4: BM25 Implementation — Qdrant Server-Side via Document API

**Chosen:** Use Qdrant's server-side BM25 tokenization. At collection level, declare `SparseVectorParams(modifier=Modifier.IDF)`. At upsert/query time, pass `models.Document(text=..., model="Qdrant/bm25", options=Bm25Config(language=...))`. Qdrant tokenizes server-side.

**Rationale:** No client-side dependencies (no fastembed, NLTK, custom tokenizers). Language support via `Bm25Config` matches spec requirements. Compatible with Qdrant native Prefetch + Query for S3-03. `docs/spec.md` explicitly says "Qdrant BM25." Requires `qdrant-client>=1.16.0`.

**Rejected:** Client-side sparse vectors via fastembed/NLTK — heavy dependency (~500MB), extra pipeline step, duplicates logic Qdrant already implements.

### D5: Keyword Search Endpoint — Admin API

**Chosen:** `POST /api/admin/search/keyword` — BM25-only search endpoint in Admin API.

**Rationale:** Story verification requires an isolated BM25-only endpoint for automated tests and manual curl verification. Useful beyond S3-02: comparison (dense vs keyword vs hybrid) in S3-03, retrieval evals in S8-02. Admin scope is correct for a diagnostic endpoint.

**Rejected:** Integration test only, no HTTP endpoint — cannot verify manually, no infrastructure for evals, no way to diagnose BM25 issues in a running system.

### D6: QdrantService API Design — Separate `keyword_search` Method

**Chosen:** New `keyword_search` method alongside existing `search`. Three methods for three modes: `search()` (dense), `keyword_search()` (sparse/BM25), `hybrid_search()` (S3-03).

**Rationale:** Single Responsibility — each method has a clean signature with the correct inputs. Zero regression risk to existing `search()`. Each method is testable in isolation. In S3-03, `hybrid_search()` can reuse `keyword_search` internally.

**Rejected:** Extend `search()` with `mode` parameter — violates Open/Closed, mixed input signatures (dense needs a vector, keyword needs text), grows with each new mode.

## Technical Approach

### Dependency Bump

`qdrant-client` bumped from `>=1.14.1` to `>=1.16.0` in `backend/pyproject.toml`. The BM25 Document API (`models.Document`, `models.Bm25Config`) was introduced in v1.16.0.

### Qdrant Document API Mechanism

- **Collection level:** Named sparse vector `"bm25"` with `SparseVectorParams(modifier=Modifier.IDF)`. Language and tokenizer are not per-collection — they are per-operation via `Bm25Config`.
- **Upsert:** Each point includes `"bm25": Document(text=chunk_text, model="Qdrant/bm25", options=Bm25Config(language=...))` alongside the `"dense"` vector. Qdrant tokenizes server-side using the Snowball stemmer.
- **Query:** Same `Document` structure with the search text. Qdrant tokenizes the query server-side and matches against stored sparse vectors.

### Collection Schema

Collection `proxymind_chunks` with two named vectors:

| Named vector | Type | Config |
|---|---|---|
| `dense` (existing) | Dense, COSINE | dimensions from `settings.embedding_dimensions` |
| `bm25` (new) | Sparse | `SparseVectorParams(modifier=Modifier.IDF)` |

Payload indexes remain unchanged (7 keyword indexes).

### `ensure_collection` Logic

1. Check if collection exists.
2. If exists, verify:
   - `dense` vector dimensions match — **raises `CollectionSchemaMismatchError`** on mismatch (unchanged behavior, hard error).
   - `bm25` sparse vector is present.
3. If `bm25` is missing — log WARNING ("Recreating collection — all existing vectors will be lost. Re-ingest sources after restart."), then race-safe delete + recreate with both vectors.
4. If collection does not exist — create with both vectors.
5. Log configured `bm25_language` at startup.
6. Create payload indexes (unchanged).

**Race safety:** Both API and worker call `ensure_collection()` on startup. The delete + create sequence handles 404 on delete (already deleted by another process) and 409 on create (already recreated by another process). The existing 409 handling pattern is extended.

**No sentinel fingerprinting.** BM25 language change is not auto-detected. Changing `BM25_LANGUAGE` in `.env` requires manual collection deletion + re-ingest.

### Upsert Changes

The `_upsert_points` method's vector dict changes from:

```python
vector={"dense": point.vector}
```

to:

```python
vector={
    "dense": point.vector,
    "bm25": models.Document(
        text=point.text_content,
        model="Qdrant/bm25",
        options=models.Bm25Config(language=self._bm25_language),
    ),
}
```

No changes to `QdrantChunkPoint` dataclass or ingestion worker task — `text_content` is already available.

### `keyword_search` Method

```
async def keyword_search(
    text: str,
    snapshot_id: UUID,
    agent_id: UUID,
    knowledge_base_id: UUID,
    limit: int = 10,
) -> list[RetrievedChunk]
```

- Queries the `"bm25"` named sparse vector using a `Document` with the search text and configured language.
- Payload filter: `snapshot_id`, `agent_id`, `knowledge_base_id` (same scope as dense search).
- Returns `list[RetrievedChunk]` — same return type as dense search.
- Retry logic: same pattern as `search` (3 attempts, exponential backoff).

### Admin Endpoint

**`POST /api/admin/search/keyword`**

Request: `query` (required), `snapshot_id` (optional, defaults to active), `agent_id` / `knowledge_base_id` (optional, default to settings), `limit` (default 10).

Response (200): `results` array (chunk_id, source_id, text_content, score, nested anchor object), `query`, `language`, `total`.

- No active snapshot returns 422 (consistent with Chat API behavior).
- Returns `language` in response for stemmer verification.
- Admin auth deferred to S7-01.

### Configuration

No new settings. `bm25_language` already exists in `config.py` (default `"english"`). The behavioral change: it is now actively used for BM25 tokenization at upsert and query time.

### Files Changed

| File | Change |
|---|---|
| `backend/pyproject.toml` | Bump `qdrant-client` to `>=1.16.0` |
| `backend/app/services/qdrant.py` | `bm25_language` param, `ensure_collection` sparse vector validation + race-safe recreate, `_upsert_points` with BM25 Document, `keyword_search` method |
| `backend/app/main.py` | Pass `bm25_language` to QdrantService |
| `backend/app/workers/main.py` | Pass `bm25_language` to QdrantService |
| `backend/app/api/admin.py` | `POST /api/admin/search/keyword` endpoint |
| `backend/app/api/schemas.py` | Request/response models for keyword search |
| `backend/app/api/dependencies.py` | Qdrant service dependency (if needed) |
| `backend/tests/unit/services/test_qdrant.py` | BM25 collection creation, upsert with Document, `keyword_search` |
| `backend/tests/unit/test_admin_keyword_search.py` | Endpoint tests |
| `backend/tests/integration/test_qdrant_roundtrip.py` | Keyword search roundtrip + stemming verification |

## Risks / Trade-offs

### Data loss on collection recreation

When `ensure_collection` detects a missing `bm25` sparse vector, it deletes and recreates the entire collection. All existing dense vectors are lost. Mitigation: Phase 3 is dev/staging with minimal data. The warning log explicitly instructs the user to re-ingest. No automated reindex exists — this is acceptable at the current project phase.

### BM25 language change requires manual action

Because `language` is a per-operation parameter (not per-collection), changing `BM25_LANGUAGE` in `.env` causes a silent mismatch: existing sparse vectors were tokenized with the old stemmer, but new upserts and queries use the new stemmer. Mitigation: the configured language is logged at startup for visibility. Changing language requires manual collection deletion + re-ingest. This is documented, not auto-detected.

### Race condition in `ensure_collection`

Both API server and worker call `ensure_collection()` on startup. If both detect a missing `bm25` vector simultaneously, both may attempt delete + create. Mitigation: the sequence handles 404 on delete (collection already gone) and 409 on create (collection already exists) gracefully. After the race, both processes re-validate and proceed.

### BM25 quality is language-dependent

Snowball stemmer quality varies by language. For some languages (e.g., CJK), Snowball stemming is weak or inapplicable. Mitigation: BGE-M3 sparse fallback is planned as S9-03, evaluated via evals in S8-02. The architecture (named sparse vector in same collection) allows swapping the sparse vector source without changing the retrieval pipeline.

## Migration Plan

1. **Bump `qdrant-client`** from `>=1.14.1` to `>=1.16.0` in `backend/pyproject.toml`.
2. **Collection auto-recreated on first startup.** When the API or worker starts and `ensure_collection` detects the existing collection lacks `bm25`, it deletes and recreates with both vectors. A WARNING is logged.
3. **Re-ingest required.** After collection recreation, all knowledge sources must be re-uploaded via Admin API to repopulate both dense and BM25 vectors. No automated reindex path exists at Phase 3.
4. **No database migrations.** No new PostgreSQL tables or columns. `bm25_language` setting already exists.
5. **No infrastructure changes.** Same Qdrant image, same Docker Compose. The BM25 Document API is a server-side capability already present in the Qdrant version used by the project.

## Open Questions

None. All design decisions were resolved in the brainstorm spec.
