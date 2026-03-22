# S3-02: BM25 Sparse Vectors — Design Spec

## Goal

Add Qdrant BM25 sparse vector indexing alongside existing dense vectors, enabling keyword search that works in parallel with semantic search. This is a prerequisite for S3-03 (hybrid retrieval + RRF fusion).

## Scope

**In scope:**

- BM25 sparse index configuration in Qdrant collection
- Collection schema update (recreate with sparse vector)
- `keyword_search` method in QdrantService
- Admin API keyword search endpoint
- `qdrant-client` dependency bump to `>=1.17.1` (BM25 Document API support; keeps S3-03 RRF API support aligned)
- Unit and integration tests

**Out of scope:**

- Hybrid search and RRF fusion (S3-03)
- Changes to Chat API retrieval or RetrievalService (S3-03)
- BGE-M3 sparse fallback (S9-03)

## Success Criteria

From `docs/plan.md`:

1. Keyword search via Qdrant returns results.
2. Stemmer language matches `.env` (`BM25_LANGUAGE`).

## Decisions

### Decision 1: Collection Upgrade Strategy — Recreate in `ensure_collection`

**Chosen:** When `ensure_collection` detects that the existing collection lacks the `bm25` sparse vector or has an incompatible BM25 modifier (not `Modifier.IDF`), it deletes the collection and recreates it with both `dense` and `bm25` vectors. BM25 language changes are **not** auto-detected — changing `BM25_LANGUAGE` requires manual collection deletion and re-ingestion.

**Why:**

- **Project phase.** Phase 3 is dev/staging. Production deployment is far away (Phase 7). Data in the collection is minimal — re-ingestion after recreation is trivial.
- **YAGNI.** Migration scripts or dual-collection architecture are overhead for a problem that does not exist at this stage. Production-grade migration is needed only when there are real users with data that cannot be lost.
- **Consistency.** The `ensure_collection` pattern already exists in `qdrant.py:75-109` — it checks dimension mismatch and raises an error. Extending this logic for sparse vector validation is a natural evolution, not a new mechanism.
- **Single source of truth.** Both vectors (dense + sparse) live in one collection — this is what Qdrant recommends for multi-vector retrieval and what is required for native RRF in S3-03.

**Recovery path after recreation:** No automated reindex path exists at this phase. After collection recreation, the user MUST manually re-upload sources via Admin API to repopulate the Qdrant index. This is acceptable for Phase 3 dev/staging. A reindex command (rebuild from PG + SeaweedFS without re-uploading) is a separate story if needed in later phases.

**Rejected alternatives:**

- *Separate migration CLI command* — zero-downtime upgrade, but significant development overhead with no production data to protect. The command would be used once and become dead code.
- *Separate collection for sparse* — avoids touching the existing collection, but complicates retrieval (two queries + merge), prevents use of Qdrant native RRF fusion (Prefetch + Query), and requires custom fusion in S3-03.

### Decision 2: BM25 Modifier — `Modifier.IDF`

**Chosen:** Use `Modifier.IDF` (Qdrant default) for BM25 sparse vector normalization.

**Why:**

- **Industry standard.** IDF is the canonical part of the BM25 formula (Okapi BM25 = TF x IDF). Without IDF, sparse scores reflect only term frequency in the document, not the term's discriminating power. This is critical for quality retrieval.
- **Qdrant default.** This is Qdrant's default value — tested and optimized in their pipeline. Follows the principle of "boring over novel."
- **RRF compatibility (S3-03).** RRF fusion works with ranks, not absolute scores, but IDF normalization ensures correct ranking of sparse results. Without IDF, sparse ranking would be noisy, reducing fusion effectiveness.

**Rejected alternatives:**

- *`Modifier.NONE`* — raw term-frequency scores without normalization. Stop-words dominate scores (Snowball stemmer removes some but not all). No reason to deviate from the standard.

### Decision 3: Text Source for BM25 — Same `text_content` as Dense Embedding

**Chosen:** Use the same `text_content` that is used for dense embedding generation as the input for BM25 tokenization. At upsert time, pass `chunk.text_content` to both the Gemini embedding call (dense) and the Qdrant `Document` (sparse/BM25).

**Why:**

- **Semantic correctness.** Dense and sparse search the same content. A chunk's text is the single source of truth for both vector representations. This ensures that keyword matches and semantic matches refer to the same text.
- **Data already available.** `text_content` is already part of `QdrantChunkPoint` (used in `ingestion.py:261`). No new data extraction needed — only passing the same text to the `Document` model during upsert.
- **Aligned with spec.** `docs/spec.md:123` states: "Indexing: retrieval-oriented task type (dense) + BM25 sparse vector." One text, two vectors — exactly as specified.

**Rejected alternatives:**

- *Separate `bm25_text` field with preprocessing* — custom preprocessed text for BM25. Duplicates text in payload (storage +50-100%), complicates pipeline for no current benefit. Snowball tokenizer in Qdrant already handles lowercasing and stemming. If S9-01 (chunk enrichment) needs a separate field, it can be added then.

### Decision 4: BM25 Implementation — Qdrant Server-Side BM25 via Document API

**Chosen:** Use Qdrant's server-side BM25 tokenization via the `Document` model API. At collection level, declare a sparse vector with `SparseVectorParams(modifier=Modifier.IDF)`. At upsert time, pass `models.Document(text=chunk.text_content, model="Qdrant/bm25", options=Bm25Config(language=...))` as the sparse vector value. At query time, pass a `Document` with the search text. Qdrant tokenizes server-side — no client-side tokenization needed.

**Why:**

- **Minimal dependencies.** No need to install fastembed, NLTK, or custom tokenizers. The BM25 tokenization (Snowball stemmer, stop-words, IDF) happens inside Qdrant server. The client only passes text and configuration.
- **Qdrant RRF compatibility.** Qdrant native Prefetch + Query supports fusion of dense and BM25 sparse vectors in a single request. This is exactly what S3-03 needs. Both vector types live in the same collection as named vectors.
- **Language support.** `Bm25Config` accepts `language` parameter for Snowball stemmer configuration. Supported languages match `spec.md`: EN, RU, DE, FR, ES, IT, PT, NL, SV, NO, DA, FI, HU, RO, TR.
- **Aligned with spec.** `docs/spec.md:117` states "Obtain a sparse embedding via Qdrant BM25" — the specification explicitly points to Qdrant-native BM25, not client-side sparse vector generation.
- **Dependency:** Requires `qdrant-client>=1.17.1`. BM25 Document API support starts in `1.16.0`, but the repository now pins `1.17.1` so S3-02 BM25 support and S3-03 RRF query support use the same floor. This story is the point where the repository minimum moved from `>=1.14.1` to `>=1.17.1`.

**Rejected alternatives:**

- *Client-side sparse vectors via fastembed/NLTK* — full control over tokenization, but adds a heavy dependency (~500MB for fastembed or NLTK + custom code), an extra pipeline step, and duplicates logic Qdrant already implements. The spec explicitly says "Qdrant BM25."

### Decision 5: Keyword Search Endpoint — Admin API

**Chosen:** `POST /api/admin/search/keyword` — an Admin API endpoint that performs BM25-only search (without dense, without fusion).

**Why:**

- **Verifiability.** Story verification criteria: "keyword search via Qdrant returns results; stemmer language matches `.env`." An isolated BM25-only endpoint is needed for both automated tests and manual verification via curl.
- **Utility beyond S3-02.** In S3-03 (hybrid retrieval + RRF), this endpoint is useful for comparison: dense-only vs keyword-only vs hybrid. In S8-02 (retrieval evals), it measures BM25 precision/recall independently. This is planned infrastructure, not YAGNI.
- **Admin scope.** A diagnostic/debugging endpoint, not for end users. Admin API is the correct location. Does not pollute the Chat API.
- **Minimal cost.** One endpoint + one method in QdrantService. ~20-30 lines of code.

**Rejected alternatives:**

- *Integration test only, no HTTP endpoint* — less code, but cannot verify manually via curl (story verification implies manual check); no infrastructure for evals in S8-02; no way to diagnose BM25 issues in a running system without writing ad-hoc scripts.

### Decision 6: QdrantService API Design — Separate `keyword_search` Method

**Chosen:** Add a new `keyword_search` method alongside the existing `search` method. `search` remains dense-only until S3-03, where `hybrid_search` will be added as a third method.

**Why:**

- **Single Responsibility.** Three methods — three search modes, each with a clean signature: `search()` (dense), `keyword_search()` (sparse/BM25), `hybrid_search()` (dense + sparse + RRF, in S3-03). This is more transparent than one method with a mode parameter.
- **Backward compatibility.** The existing `search()` is used in `RetrievalService` and Chat API. Not touching it means zero regression risk. `RetrievalService` continues working as before until S3-03.
- **Testability.** Each method is tested in isolation. Unit tests for `keyword_search` do not depend on dense search and vice versa.
- **Preparation for S3-03.** In S3-03, `hybrid_search()` will call both (Qdrant Prefetch dense + sparse -> Query RRF). Having `keyword_search` as a separate method allows reuse or refactoring into an internal `_sparse_prefetch`.

**Rejected alternatives:**

- *Extend `search()` with `mode: Literal["dense", "keyword"]` parameter* — single entry point, but violates Open/Closed (each new mode edits the existing method); in S3-03 a "hybrid" mode would be added, growing the method; the signature becomes ambiguous (dense requires a vector, keyword requires text — different inputs through one method is a code smell).

## Technical Design

### Dependency Bump

`qdrant-client` MUST be bumped from `>=1.14.1` to `>=1.17.1` in `backend/pyproject.toml`. The BM25 Document API (`models.Document`, `models.Bm25Config`) was introduced in `qdrant-client` v1.16.0, and the repository now standardizes on `1.17.1` so BM25 support and later hybrid RRF support share one dependency floor. Without this bump, the implementation will fail on import or at runtime.

### Qdrant API Mechanism

Qdrant server-side BM25 works through the `Document` model API:

- **Collection level:** Declare a named sparse vector with `SparseVectorParams(modifier=Modifier.IDF)`. This configures how sparse scores are normalized but does NOT specify language or tokenizer — those are per-operation.
- **Upsert:** Pass `models.Document(text=chunk_text, model="Qdrant/bm25", options=Bm25Config(language="english"))` as the value for the `"bm25"` named vector. Qdrant tokenizes the text server-side using the specified Snowball stemmer and stores the resulting sparse vector.
- **Query:** Pass `models.Document(text=query_text, model="Qdrant/bm25", options=Bm25Config(language="english"))` as the query. Qdrant tokenizes the query server-side and matches against the stored sparse vectors.

`Bm25Config` parameters used: `language` (Snowball stemmer language). Other parameters (`k`, `b`, `avg_len`, `tokenizer`, `lowercase`, etc.) are left at Qdrant defaults.

**Important:** Because `language` is a per-operation parameter (not per-collection), changing `BM25_LANGUAGE` in `.env` without recreating the collection causes a silent mismatch: existing sparse vectors were tokenized with the old stemmer, but new queries use the new stemmer. At Phase 3, the configured language is logged at startup. Changing `BM25_LANGUAGE` requires manual collection deletion + re-ingest.

### Qdrant Collection Schema

Collection `proxymind_chunks` with two named vectors:

| Named vector | Type | Config |
|---|---|---|
| `dense` (existing) | Dense, COSINE | dimensions from `settings.embedding_dimensions` (default 3072) |
| `bm25` (new) | Sparse | `SparseVectorParams(modifier=Modifier.IDF)` — language is per-operation via `Bm25Config` |

Payload indexes remain unchanged (7 keyword indexes: `snapshot_id`, `agent_id`, `knowledge_base_id`, `source_id`, `status`, `source_type`, `language`).

### Collection Recreation Logic in `ensure_collection`

1. Check if collection exists.
2. If exists — verify:
   a. `dense` vector dimensions match (existing check — **raises `CollectionSchemaMismatchError`** on mismatch, unchanged from before).
   b. `bm25` sparse vector is present.
   c. The existing `bm25` sparse vector uses `SparseVectorParams(modifier=Modifier.IDF)`.
3. If `bm25` sparse vector is missing or its modifier is not `Modifier.IDF` — log at **WARNING** level that the BM25 schema is incompatible and the collection will be recreated. Use the same race-safe delete + recreate path with both vectors.
4. If collection does not exist — create with both vectors.
5. Log configured `bm25_language` at startup.
6. Create payload indexes (unchanged).

**Dense dimension mismatch remains a hard error.** Auto-recreate applies ONLY to BM25 schema incompatibility (`bm25` missing or configured with a non-`Modifier.IDF` modifier). Silently deleting data on dimension change is too aggressive and out of scope for a BM25 story.

**Race safety:** Both API (`main.py:108`) and worker (`workers/main.py:55`) call `ensure_collection()` on startup. The delete-then-create sequence MUST be guarded:
- Wrap the delete + create in a try/except that handles the case where another process already deleted/recreated the collection (Qdrant returns 404 on delete of non-existent collection, 409 on create of existing collection — both are safe to catch and retry the validation).
- The existing 409 handling pattern in `ensure_collection` already covers the create race. Extend it to also handle 404 on delete.

**Recovery path:** No automated reindex exists at this phase. After recreation, user must re-upload sources via Admin API. Log message explicitly states this.

**BM25 language change:** Not auto-detected. Changing `BM25_LANGUAGE` in `.env` requires manual collection deletion (e.g., `docker-compose down -v` or Qdrant API) followed by re-ingest. The configured language is logged at startup for visibility.

### Ingestion Pipeline Changes

The `_upsert_points` method in QdrantService MUST be modified to include BM25 Document alongside the dense vector for each point.

Current upsert (dense only):
```python
vector={"dense": chunk.vector}
```

Updated upsert (dense + BM25):
```python
vector={
    "dense": point.vector,
    "bm25": models.Document(
        text=point.text_content,
        model="Qdrant/bm25",
        options=models.Bm25Config(language=self.bm25_language),
    ),
}
```

Note: the current code uses `vector=` (singular), not `vectors=`. The field name in `PointStruct` is `vector`.

The `QdrantChunkPoint` dataclass already contains `text_content` — no changes to the dataclass or to the ingestion worker task. The change is isolated to `QdrantService._upsert_points`.

### QdrantService Changes

**Constructor** — new parameter: `bm25_language: str`.

**`ensure_collection`** — extended:

- Collection creation includes `sparse_vectors_config={"bm25": SparseVectorParams(modifier=Modifier.IDF)}`.
- Validation of existing collection: dense dimension mismatch raises `CollectionSchemaMismatchError` (unchanged); missing `bm25` sparse vector or a non-`Modifier.IDF` BM25 modifier triggers race-safe delete + recreate.
- Logs configured `bm25_language` at startup.

**`_upsert_points`** — modified:

- Each point's vector dict includes `"bm25": Document(text=point.text_content, model="Qdrant/bm25", options=Bm25Config(language=self.bm25_language))` alongside the existing dense vector.

**New method `keyword_search`:**

```
async def keyword_search(
    self,
    text: str,
    snapshot_id: UUID,
    agent_id: UUID,
    knowledge_base_id: UUID,
    limit: int = 10,
) -> list[RetrievedChunk]
```

- Queries the `"bm25"` named sparse vector using `models.Document(text=text, model="Qdrant/bm25", options=Bm25Config(language=self.bm25_language))`.
- Payload filter: `snapshot_id`, `agent_id`, `knowledge_base_id` (same scope as dense search).
- Returns `list[RetrievedChunk]` — same type as dense search.
- Retry logic: same pattern as `search` (3 attempts, exponential backoff for transient errors).

**Existing `search` method** — no changes. Remains dense-only until S3-03.

### Admin API Endpoint

**`POST /api/admin/search/keyword`**

Request body:

```json
{
  "query": "string (required, min_length=1)",
  "snapshot_id": "uuid (optional — defaults to active snapshot)",
  "agent_id": "uuid (optional — defaults to DEFAULT_AGENT_ID)",
  "knowledge_base_id": "uuid (optional — defaults to DEFAULT_KNOWLEDGE_BASE_ID)",
  "limit": 10
}
```

Response (200):

```json
{
  "results": [
    {
      "chunk_id": "uuid",
      "source_id": "uuid",
      "text_content": "string",
      "score": 0.85,
      "anchor": {
        "page": 42,
        "chapter": "Chapter 3",
        "section": null,
        "timecode": null
      }
    }
  ],
  "query": "original query",
  "language": "english",
  "total": 3
}
```

- Admin auth is deferred to S7-01. Currently follows the same pattern as existing `/api/admin/*` endpoints (unprotected until S7-01).
- If `snapshot_id` is not provided — uses active snapshot (via SnapshotService). If no active snapshot exists — returns **422** with an error message, consistent with the Chat API behavior (`chat.py:223`).
- `agent_id` and `knowledge_base_id` default to `DEFAULT_AGENT_ID` / `DEFAULT_KNOWLEDGE_BASE_ID`, matching existing admin endpoint patterns.
- Returns `language` in response for verification that stemmer language matches `.env`.
- Response `anchor` is a nested object (page, chapter, section, timecode) — transformed from the flat `anchor_*` keys in `RetrievedChunk.anchor_metadata` for a cleaner API surface.

### Configuration

No new settings. `bm25_language` already exists in `config.py:34` (default `"english"`). Passed to QdrantService via constructor.

The behavioral change: `bm25_language` is now actively used for BM25 tokenization at upsert and query time (previously it was only written to chunk payload as metadata).

## Files Changed

| File | Change |
|---|---|
| `backend/pyproject.toml` | Bump `qdrant-client>=1.14.1` to `>=1.17.1` |
| `backend/app/services/qdrant.py` | Add `bm25_language` param, update `ensure_collection` (sparse vector + language fingerprint + race safety), modify `_upsert_points` to include BM25 Document, add `keyword_search` method |
| `backend/app/workers/main.py` | Pass `bm25_language` to QdrantService constructor |
| `backend/app/main.py` | Pass `bm25_language` to QdrantService in API startup |
| `backend/app/api/admin.py` | Add `POST /api/admin/search/keyword` endpoint |
| `backend/app/services/retrieval.py` | No changes (dense-only until S3-03) |
| `backend/app/workers/tasks/ingestion.py` | No changes (ingestion passes `text_content` via `QdrantChunkPoint`; BM25 Document construction is in `QdrantService`) |
| `backend/app/core/config.py` | No changes (`bm25_language` already exists) |
| `backend/tests/unit/services/test_qdrant.py` | Extend for sparse vector config, BM25 Document in upsert, language fingerprint, `keyword_search` |
| `backend/tests/unit/test_admin_keyword_search.py` | New: endpoint tests |
| `backend/tests/integration/test_qdrant_roundtrip.py` | Extend for keyword search roundtrip + stemming verification |

## Testing Strategy

### Unit Tests (deterministic, CI)

**`backend/tests/unit/services/test_qdrant.py` — extend:**

- Collection creation includes `sparse_vectors_config` with `"bm25"` and `Modifier.IDF`.
- Schema mismatch: collection without sparse vector triggers race-safe recreate with WARNING log.
- Dense dimension mismatch still raises `CollectionSchemaMismatchError` (unchanged).
- `_upsert_points`: verify `vector=` dict includes both `"dense"` vector and `"bm25"` `Document` with correct `model="Qdrant/bm25"`, `text=point.text_content`, and `options.language` matching `bm25_language`.
- `keyword_search`: mock Qdrant client, verify query uses `Document(model="Qdrant/bm25")` with correct language, filter, and limit.
- `keyword_search`: retry on transient errors.
- `keyword_search`: empty results return empty list.

**`backend/tests/unit/test_admin_keyword_search.py` — new:**

- Valid request returns 200 with correct response structure (including nested `anchor` object).
- Default `snapshot_id` uses active snapshot.
- No active snapshot → 422.
- Default `agent_id` / `knowledge_base_id` use defaults.
- Empty query returns 422 validation error.
- Auth test deferred to S7-01 (admin auth not yet implemented).

### Integration Tests (real Qdrant, CI)

**`backend/tests/integration/test_qdrant_roundtrip.py` — extend:**

- Upsert chunks with `text_content` via BM25 Document, then keyword search finds them by keywords.
- Keyword search scoped by `snapshot_id` — chunks from other snapshots are not visible.
- Stemming roundtrip: upsert chunk containing "runs", search for "running" → match (for language=english). This verifies that `Document.options.language` is correctly applied at both upsert and query time.
- Collection recreation on missing sparse vector works end-to-end.

### Not Tested in CI

- BM25 retrieval quality on real documents — deferred to S8-02 (retrieval evals).
