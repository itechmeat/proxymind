# S3-03: Hybrid Retrieval + RRF — Design Spec

## Story

> Dense (query-oriented) + sparse (BM25) search, Reciprocal Rank Fusion, `min_dense_similarity` filtering before fusion. Scoped by `snapshot_id` + tenant-ready fields.

**Outcome:** retrieval combines semantic and keyword search.

**Verification:** query with exact keyword match ranks the matching chunk higher via hybrid than dense-only (deterministic fixture); filtering by snapshot works.

## Context

S3-02 delivered full BM25 sparse vector support: indexing during ingestion, `keyword_search()` utility method, and Qdrant collection schema with named vectors (`dense` + `bm25`). The retrieval service currently uses dense-only search. S3-03 integrates both into a unified hybrid retrieval pipeline with RRF fusion.

## Design Decisions

### 1. Search strategy: hybrid always

**Decision:** `RetrievalService.search()` always performs hybrid search (dense + BM25 + RRF). No search method selector, no enum, no configuration switch.

**Rationale:**
- BM25 is indexed for all chunks since S3-02; empty sparse indexes do not exist in production.
- RRF degrades gracefully: if sparse contributes no results, ranking is determined by dense alone.
- No real use case for dense-only in production after S3-03.
- KISS: no extra parameter, no branching.

### 2. Pre-fusion similarity filtering via Qdrant prefetch

**Decision:** `min_dense_similarity` is applied as `score_threshold` on the dense prefetch leg inside Qdrant, before RRF fusion. This matches the architecture described in `rag.md`: *"The relevance threshold is applied to dense cosine similarity before RRF fusion."*

**Sparse-only results are intentional.** A chunk may fail the dense threshold but still appear in the final top-N as a BM25-only hit through RRF. This is by design — the whole point of hybrid search is that sparse catches what dense misses (e.g., exact term matches for specific queries). `min_dense_similarity` filters noise from the dense leg, not from the entire retrieval pipeline. The final guardrail against low-quality results is `min_retrieved_chunks` checked by `ChatService` — if too few chunks pass overall, the twin returns a refusal.

**Rationale:**
- Qdrant Prefetch natively supports `score_threshold` per leg.
- Filtering happens server-side — no unnecessary data transfer.
- One round-trip instead of two.
- Semantics match rag.md exactly.

### 3. Prefetch limit multiplier: 2x constant

**Decision:** Each prefetch leg requests `limit * 2` candidates. Defined as `PREFETCH_MULTIPLIER = 2` module-level constant in `qdrant.py`.

**Rationale:**
- 2x is standard practice for RRF fusion — sufficient candidate overlap.
- Minimal load with good coverage.
- No extra configuration parameter until eval data justifies tuning (S8-02).
- Easy to change later — it is just a constant.

### 4. Existing `keyword_search()` stays

**Decision:** `keyword_search()` remains as a utility method for diagnostics and future evals. Not called from the production chat flow.

**Rationale:**
- Useful for diagnostics: "why wasn't this chunk found?" — check dense and sparse separately.
- Needed for baseline comparison in retrieval evals (S8-02).
- Does not pollute the production path.
- Deleting working code without reason is unnecessary churn.

### 5. Rename `search()` → `dense_search()`

**Decision:** Rename the existing dense-only method to `dense_search()`. Add `hybrid_search()` as the new method. RetrievalService calls `hybrid_search()`.

**Rationale:**
- Symmetric naming: `dense_search()`, `keyword_search()`, `hybrid_search()` — three methods, three strategies.
- Each method is self-evident from its name.
- `dense_search()` is needed for baseline comparison in evals (S8-02).
- Production path is clean: retrieval calls only `hybrid_search()`.

### 6. Embedding responsibility stays in RetrievalService

**Decision:** `RetrievalService` generates the dense embedding via `EmbeddingService`, then passes both `text` and `vector` to `QdrantService.hybrid_search()`. QdrantService has no dependency on EmbeddingService.

**Rationale:**
- Preserves current separation of concerns: RetrievalService = orchestrator, QdrantService = Qdrant transport layer.
- QdrantService remains free of external dependencies beyond Qdrant.
- Minimal change to existing flow.
- Consistent with the pattern already working for dense search.

## Implementation approach: Qdrant Native RRF

Uses Qdrant's built-in RRF fusion via `Prefetch` + `RrfQuery`. One round-trip to Qdrant.

Use `RrfQuery(rrf=Rrf(k=60))` with explicit k parameter instead of `FusionQuery(fusion=Fusion.RRF)`. Both are supported by the SDK, and the repository now pins `qdrant-client >= 1.17.1`. `RrfQuery` pins the k constant and makes behavior stable across Qdrant upgrades. `k=60` is the standard RRF default.

**Why not client-side RRF:** Two round-trips, custom RRF implementation to write and test, higher latency, more code — all for no benefit since Qdrant's native RRF is well-tested and sufficient.

**Why not custom scoring:** Overkill without eval data. RRF is the documented target in `rag.md`.

## Architecture

### QdrantService — new `hybrid_search()` method

```python
async def hybrid_search(
    self,
    *,
    text: str,                        # Raw query text for BM25
    vector: list[float],              # Dense embedding from Gemini
    snapshot_id: UUID,
    agent_id: UUID,
    knowledge_base_id: UUID,
    limit: int,
    score_threshold: float | None,    # min_dense_similarity on dense leg
) -> list[RetrievedChunk]
```

Internal flow:
1. Build `scope_filter` via `_build_scope_filter()` (already used by `keyword_search()`; `dense_search()` builds its filter inline — refactor it to use `_build_scope_filter()` too during the rename for consistency).
2. Build BM25 Document via existing `_build_bm25_document(text)`.
3. Construct Qdrant `QueryRequest` with two `Prefetch` legs, each scoped with `filter=scope_filter` so candidate generation is tenant/snapshot-safe before fusion:
   - **Dense:** `query=vector, using="dense", filter=scope_filter, limit=limit*PREFETCH_MULTIPLIER, score_threshold=score_threshold`
   - **Sparse:** `query=bm25_document, using="bm25", filter=scope_filter, limit=limit*PREFETCH_MULTIPLIER`
4. Final query: `RrfQuery(rrf=Rrf(k=60))`, `limit=limit`, `query_filter=scope_filter`. Keeping the top-level filter in addition to per-leg filters is intentional defensive scoping, not accidental duplication.
5. Map results via existing `_to_retrieved_chunk()`.

**Note on score semantics:** After hybrid, `RetrievedChunk.score` is an RRF rank score, not a cosine similarity. Downstream consumers receive it as method-specific metadata; they must not compare hybrid scores against dense-only or BM25-only scores without already knowing which retrieval path produced them. The field name is not renamed to avoid a breaking change.

**Zero limit behavior:** `hybrid_search()` short-circuits to `[]` when `limit <= 0`, without querying Qdrant. This matches the existing pass-through behavior of `dense_search()` and avoids constructing a prefetch with 0 candidates.

### RetrievalService — updated `search()` method

```python
async def search(
    self,
    query: str,
    *,
    snapshot_id: UUID,
    top_n: int | None = None,
) -> list[RetrievedChunk]
```

Internal flow (changed parts in bold):
1. Embed query via `embedding_service.embed_texts([query])`.
2. **Call `qdrant_service.hybrid_search(text=query, vector=embedding, ...)` instead of `dense_search()`.**
3. **Map `top_n` to `limit`: when `top_n is None`, pass the configured `RetrievalService._top_n`; otherwise pass the explicit `top_n` value.**
4. **Pass `min_dense_similarity` through as `score_threshold`.**
5. Return results.

Signature unchanged — ChatService is not affected.

### Renamed method

`QdrantService.search()` → `QdrantService.dense_search()`. Signature unchanged.

## Configuration

No new parameters. All required settings already exist:

| Parameter | Default | Used in |
|-----------|---------|---------|
| `retrieval_top_n` | 5 | `limit` for fusion |
| `min_dense_similarity` | None | `score_threshold` on dense prefetch leg |
| `bm25_language` | "english" | Snowball stemmer language |

New constants in `qdrant.py`:
- `PREFETCH_MULTIPLIER = 2` — candidate pool multiplier for each prefetch leg.
- `RRF_K = 60` — standard RRF k parameter, pinned explicitly via `RrfQuery(rrf=Rrf(k=RRF_K))`.

## Error handling

No new error handling needed:
- Qdrant unavailable: existing `tenacity` retry in `_search_points()`.
- Empty results: `ChatService` checks `min_retrieved_chunks` and returns refusal (not `RetrievalService` — it only returns the result list).
- All failure paths are already covered.

## Testing

### Unit tests — QdrantService (`test_qdrant.py`)

| Test | Verifies |
|------|----------|
| `test_hybrid_search_builds_correct_prefetch` | Mock Qdrant client, verify Prefetch contains both legs with correct params |
| `test_hybrid_search_applies_score_threshold` | Dense leg has score_threshold when min_dense_similarity is set |
| `test_hybrid_search_uses_rrf_query_with_explicit_k` | RrfQuery(rrf=Rrf(k=60)) is used |
| `test_hybrid_search_respects_limit` | Correct limit and prefetch multiplier |

### Unit tests — RetrievalService (`test_retrieval_service.py`)

| Test | Verifies |
|------|----------|
| `test_search_calls_hybrid_search_with_text_and_vector` | Both text and vector are passed to hybrid_search |
| Update existing tests | Mock `hybrid_search` instead of `search` |

### Integration tests — Qdrant roundtrip (`test_qdrant_roundtrip.py`)

| Test | Verifies |
|------|----------|
| `test_hybrid_search_returns_results` | Upsert chunks → hybrid search → results returned |
| `test_hybrid_search_filters_by_snapshot` | Scope filtering works with hybrid |
| `test_hybrid_search_keyword_boost` | Chunk with exact keyword match ranks higher via hybrid than dense-only (deterministic fixture) |
| `test_hybrid_search_sparse_only_results` | Dense leg empty after score_threshold — BM25-only hits still returned |
| `test_hybrid_search_dense_only_results` | Sparse leg returns nothing — dense-only results pass through RRF |
| `test_hybrid_search_dedup_same_chunk_both_legs` | Same chunk matched by both legs appears once in results |

### Rename coverage

Update all references from `qdrant_service.search()` to `dense_search()` in existing tests.

## Files changed

| File | Change |
|------|--------|
| `backend/app/services/qdrant.py` | Rename `search()` → `dense_search()` and refactor it to use `_build_scope_filter()`, add `hybrid_search()`, add `PREFETCH_MULTIPLIER` |
| `backend/app/services/retrieval.py` | Call `hybrid_search()` instead of `search()`, pass `text` alongside `vector` |
| `backend/tests/unit/services/test_qdrant.py` | Add hybrid tests, rename `search` → `dense_search` |
| `backend/tests/unit/test_retrieval_service.py` | Update mock to `hybrid_search`, verify text+vector passed |
| `backend/tests/integration/test_qdrant_roundtrip.py` | Add hybrid roundtrip + keyword boost test |

**Not affected:** `chat.py` (service), `chat.py` (API), ingestion, config, workers.

## Out of scope

- RRF weight tuning (no eval data yet — S8-02).
- Client-side fusion fallback.
- Search method configuration parameter.
- Any changes to ingestion pipeline (BM25 indexing already complete in S3-02).
- **Payload filters for `language`, `status`, `source_type`** — `rag.md:120` lists these as required retrieval filters, but they are not consistently populated in Qdrant payload during ingestion yet. S3-03 uses the existing three-field scope (`snapshot_id`, `agent_id`, `knowledge_base_id`), which is sufficient for current functionality. Extending `_build_scope_filter()` with additional fields is a follow-up when ingestion populates them reliably.
