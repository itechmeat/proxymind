# Exploration: Qdrant Built-in BM25 Sparse Vector API

Date: 2026-03-22

## Research question

What is the exact qdrant-client Python SDK API for configuring built-in BM25 sparse vectors? Specifically:

1. How is a collection created with BM25 sparse vectors that auto-index from a text payload field?
2. What is the exact API surface -- `SparseVectorParams`, `Bm25Config`, `Document` model?
3. How is keyword search performed -- raw text query or client-side tokenization?
4. What parameters does `Bm25Config` accept?

## Scope

- **In scope:** qdrant-client Python SDK `1.17.1` (installed in this project), Qdrant server `1.17+`, the `Qdrant/bm25` inference model, `SparseVectorParams`, `Bm25Config`, `Document` model, `Modifier` enum.
- **Out of scope:** fastembed client-side BM25, SPLADE, BM42, ColBERT, third-party integrations (LangChain, Haystack).

## Findings

### 1. There is no "auto-index from payload field" mechanism

The design spec (`docs/superpowers/specs/2026-03-22-s3-02-bm25-sparse-vectors-design.md`) states that Qdrant "automatically tokenizes text and builds sparse vectors from the `text_content` payload field." This is **not how the API works**.

Qdrant does not have a `text_field` parameter on `SparseVectorParams` or `Bm25Config` that would auto-build sparse vectors from an existing payload field. Instead, BM25 sparse vectors must be explicitly provided during upsert, either as:

- A `models.Document(text=..., model="Qdrant/bm25")` object (server-side tokenization via Qdrant inference).
- A `models.SparseVector(indices=..., values=...)` object (client-side tokenization via fastembed).

The `text_content` payload field already stored in each point is **not** automatically consumed by the sparse vector index. The text must be explicitly passed as a `Document` in the vector dict during upsert.

**Confidence:** Corroborated -- verified by SDK source code inspection (`SparseVectorParams` has only `index` and `modifier` fields, no `text_field`), multiple official examples ([Qdrant course demo](https://qdrant.tech/course/essentials/day-3/sparse-retrieval-demo/), [hybrid search tutorial](https://qdrant.tech/documentation/tutorials-and-examples/cloud-inference-hybrid-search/)), and the [bm42_eval reference implementation](https://github.com/qdrant/bm42_eval/blob/master/index_bm25_qdrant.py).

### 2. Collection creation: `SparseVectorParams` with `Modifier.IDF`

Collection creation uses `sparse_vectors_config` with a named sparse vector:

```python
await client.create_collection(
    collection_name="proxymind_chunks",
    vectors_config={
        "dense": models.VectorParams(
            size=3072,
            distance=models.Distance.COSINE,
        ),
    },
    sparse_vectors_config={
        "bm25": models.SparseVectorParams(
            modifier=models.Modifier.IDF,
        ),
    },
)
```

`SparseVectorParams` accepts exactly two optional fields (verified from SDK source at `models.py:3261`):

| Field | Type | Description |
|-------|------|-------------|
| `index` | `Optional[SparseIndexParams]` | Custom params for sparse inverted index (full scan threshold, index type). Defaults to collection config. |
| `modifier` | `Optional[Modifier]` | Value modification applied at query time. `Modifier.NONE` (default) or `Modifier.IDF`. |

`Bm25Config` is **not** a parameter of `SparseVectorParams`. They are unrelated types. `Bm25Config` is used as `options` on the `Document` model (see section 4).

**Confidence:** Corroborated -- SDK source code + multiple official examples agree.

### 3. Upserting with server-side BM25: the `Document` model

To have Qdrant tokenize text server-side, pass a `models.Document` object in the vector dict during upsert:

```python
models.PointStruct(
    id=str(chunk_id),
    vector={
        "dense": dense_vector_list,           # list[float]
        "bm25": models.Document(
            text=chunk.text_content,
            model="Qdrant/bm25",
            options=models.Bm25Config(
                language="english",
                avg_len=256.0,
            ),
        ),
    },
    payload={...},
)
```

The `Document` model (SDK source `models.py:861`) has three fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `text` | `str` | Yes | Text to tokenize and embed |
| `model` | `str` | Yes | Model identifier. Must be `"Qdrant/bm25"` for BM25. |
| `options` | `DocumentOptions` (union of `dict[str, Any]` or `Bm25Config`) | No | BM25 configuration parameters |

When `model="Qdrant/bm25"` and the Qdrant server version is 1.15.3+, the qdrant-client sends the `Document` object directly to the server for server-side tokenization rather than using fastembed locally. This is confirmed by the SDK embedder code (`embedder.py:301`): when `use_core_bm25` is true and model is `"Qdrant/bm25"`, it returns the `Document` as-is without local embedding.

**Confidence:** Corroborated -- SDK source code (`embedder.py:301`, `model_embedder.py:356`) + official examples.

### 4. `Bm25Config` parameters

`Bm25Config` (SDK source `models.py:109-152`) accepts the following parameters, all optional:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `k` | `float` | `1.2` | Controls term frequency saturation. Higher = more TF impact. Standard BM25 `k1` parameter. |
| `b` | `float` | `0.75` | Controls document length normalization. 0 = no normalization, 1 = full normalization. Standard BM25 `b` parameter. |
| `avg_len` | `float` | `256` | Expected average document length in the collection. Used for length normalization. |
| `tokenizer` | `TokenizerType` | `None` | Tokenizer type: `"prefix"`, `"whitespace"`, `"word"`, `"multilingual"`. |
| `language` | `str` | `None` (English assumed) | Language for preprocessing (stopwords + stemmer). Set to `"none"` to disable language processing. Free-form string, not the `Language` enum. |
| `lowercase` | `bool` | `None` (true) | Lowercase text before tokenization. |
| `ascii_folding` | `bool` | `None` (false) | Normalize accented characters to ASCII (e.g., "acao" from "acao"). |
| `stopwords` | `StopwordsInterface` | `None` | Stopwords configuration. Can be a `Language` enum value or `StopwordsSet(languages=[...], custom=[...])`. |
| `stemmer` | `StemmingAlgorithm` | `None` | Stemming algorithm. Currently only `SnowballParams(type="snowball", language=...)`. |
| `min_token_len` | `int` | `None` | Minimum token length to keep. |
| `max_token_len` | `int` | `None` | Maximum token length to keep. |

The `language` parameter on `Bm25Config` is a plain `Optional[str]`, not the `Language` enum. The Qdrant docs state it constructs default stopwords and stemmer based on this value. Setting it to `"none"` disables language-specific processing.

**Confidence:** Corroborated -- direct SDK source code inspection.

### 5. Querying: pass raw text via `Document`, no client-side tokenization

For keyword search, pass a `models.Document` as the query. Qdrant tokenizes it server-side:

```python
response = await client.query_points(
    collection_name="proxymind_chunks",
    query=models.Document(
        text="search query text",
        model="Qdrant/bm25",
    ),
    using="bm25",
    query_filter=models.Filter(must=[...]),
    limit=10,
    with_payload=True,
)
```

No client-side tokenization is needed. The text is sent to the server, which tokenizes it using the same BM25 configuration and computes sparse similarity scores with IDF applied at query time.

For hybrid search with RRF fusion, the Prefetch + FusionQuery pattern applies:

```python
response = await client.query_points(
    collection_name="proxymind_chunks",
    prefetch=[
        models.Prefetch(
            query=models.Document(text=query, model="Qdrant/bm25"),
            using="bm25",
            limit=20,
        ),
        models.Prefetch(
            query=dense_vector,
            using="dense",
            limit=20,
        ),
    ],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    limit=10,
    with_payload=True,
)
```

**Confidence:** Corroborated -- official [hybrid search demo](https://qdrant.tech/course/essentials/day-3/hybrid-search-demo/) and [cloud inference tutorial](https://qdrant.tech/documentation/tutorials-and-examples/cloud-inference-hybrid-search/).

### 6. Impact on ingestion pipeline: upsert must change

The current `upsert_chunks` method in `backend/app/services/qdrant.py:111-140` passes `vector={"dense": chunk.vector}`. To add BM25, the vector dict must include a `Document` entry for the `"bm25"` named sparse vector:

```python
vector={
    "dense": chunk.vector,
    "bm25": models.Document(
        text=chunk.text_content,
        model="Qdrant/bm25",
        options=models.Bm25Config(language=self._bm25_language),
    ),
}
```

This contradicts the design spec statement that "no ingestion pipeline changes are required." The ingestion pipeline must be modified to include the `Document` object in the vector dict during upsert. The server does handle tokenization and indexing, but the text must be explicitly provided at upsert time.

**Confidence:** Corroborated -- the SDK source confirms `SparseVectorParams` has no `text_field` and the official examples all show `Document` in the upsert vector dict.

### 7. IDF behavior and `avg_len`

IDF statistics are computed dynamically by Qdrant at query time based on collection statistics. They do not require manual updates when documents are added or removed ([GitHub issue #6690](https://github.com/qdrant/qdrant/issues/6690)).

The `avg_len` parameter in `Bm25Config` is **not** dynamically updated. It is a static estimate that the caller provides. The Qdrant maintainer states this typically depends on chunking strategy and has minimal precision impact. The default is `256`.

There is a [known issue](https://github.com/qdrant/qdrant/issues/6735) where IDF accuracy drops after upsert/delete operations. This was reported in June 2025. The severity and resolution status could not be determined from available sources.

**Confidence:** Substantiated -- based on GitHub issue discussions with Qdrant maintainers.

### 8. Supported languages

The `Language` enum in the SDK (`models.py:1587-1617`) lists languages available for stopwords and stemming:

Arabic, Azerbaijani, Basque, Bengali, Catalan, Chinese, Danish, Dutch, English, Finnish, French, German, Greek, Hebrew, Hinglish, Hungarian, Indonesian, Italian, Japanese, Kazakh, Nepali, Norwegian, Portuguese, Romanian, Russian, Slovene, Spanish, Swedish, Tajik, Turkish.

However, the `Bm25Config.language` field is a plain `str`, not constrained to this enum. The design spec listed a narrower set (EN, RU, DE, FR, ES, IT, PT, NL, SV, NO, DA, FI, HU, RO, TR). The actual supported set is wider based on the `Language` enum.

**Confidence:** Substantiated -- the `Language` enum is verified from SDK source, but its exact relationship to `Bm25Config.language` string values is not explicitly documented.

## Key takeaways

- `SparseVectorParams` does not have a `text_field` parameter. There is no auto-indexing from payload fields. BM25 text must be explicitly provided via `Document` objects during upsert. (Corroborated)
- Collection creation uses `SparseVectorParams(modifier=Modifier.IDF)`. `Bm25Config` is not a parameter of `SparseVectorParams` -- it is passed as `options` on the `Document` model. (Corroborated)
- Both upsert and query use `models.Document(text=..., model="Qdrant/bm25")`. The server handles tokenization. No client-side tokenization is needed. (Corroborated)
- The ingestion pipeline (`upsert_chunks`) must be modified to include the `Document` in the vector dict. The design spec's claim of "no ingestion pipeline changes" is incorrect. (Corroborated)
- `Bm25Config` accepts `k`, `b`, `avg_len`, `tokenizer`, `language`, `lowercase`, `ascii_folding`, `stopwords`, `stemmer`, `min_token_len`, `max_token_len`. (Corroborated)

## Open questions

1. **IDF accuracy after mutations.** GitHub issue #6735 reports IDF degradation after upsert/delete. Current severity and fix status are unknown. This could affect retrieval quality in production.
2. **`avg_len` tuning.** The default is `256`. ProxyMind chunks may have a different average length. Whether this matters enough to compute dynamically at upsert time is untested.
3. **`Bm25Config.language` accepted values.** The field is a plain string. Whether it accepts the same values as the `Language` enum (e.g., `"russian"`, `"chinese"`, `"japanese"`) or a different set is not explicitly documented. The Qdrant docs say "set to `'none'` to disable."
4. **`Bm25Config` consistency between upsert and query.** Whether `Bm25Config` options passed during upsert must match those used at query time (e.g., same `language`, same `tokenizer`) is not documented. Mismatched tokenization could silently degrade results.
5. **Qdrant server version requirement.** The SDK routes `Qdrant/bm25` to server-side processing for Qdrant server >= 1.15.3. The project's Docker Compose Qdrant version should be verified.

## Sources

1. [qdrant-client SDK source `models.py`](local: backend/.venv/lib/python3.14/site-packages/qdrant_client/http/models/models.py) -- `Bm25Config`, `SparseVectorParams`, `Modifier`, `Document`, `Language` enum definitions. Primary source for all API surface findings.
2. [qdrant-client SDK source `embedder.py`](local: backend/.venv/lib/python3.14/site-packages/qdrant_client/embed/embedder.py) -- Confirmed server-side BM25 routing logic for `Qdrant/bm25` model.
3. [Qdrant Sparse Retrieval Demo](https://qdrant.tech/course/essentials/day-3/sparse-retrieval-demo/) -- Official code examples for collection creation, upsert with `Document`, and query.
4. [Qdrant Hybrid Search Demo](https://qdrant.tech/course/essentials/day-3/hybrid-search-demo/) -- Official Prefetch + RRF fusion pattern with both dense and BM25 sparse.
5. [Cloud Inference Hybrid Search Tutorial](https://qdrant.tech/documentation/tutorials-and-examples/cloud-inference-hybrid-search/) -- Full hybrid search example with `Document` model for both dense and sparse.
6. [bm42_eval/index_bm25_qdrant.py](https://github.com/qdrant/bm42_eval/blob/master/index_bm25_qdrant.py) -- Qdrant's own BM25 evaluation script using fastembed client-side approach (alternative to server-side `Document`).
7. [GitHub issue #6690](https://github.com/qdrant/qdrant/issues/6690) -- Maintainer clarification on IDF dynamic computation and `avg_len` behavior.
8. [GitHub issue #6735](https://github.com/qdrant/qdrant/issues/6735) -- Report of IDF accuracy degradation after upsert/delete operations.
9. [Qdrant/bm25 HuggingFace model card](https://huggingface.co/Qdrant/bm25) -- Confirms `Qdrant/bm25` is a fastembed model; server-side routing is a qdrant-client feature, not a model feature.
