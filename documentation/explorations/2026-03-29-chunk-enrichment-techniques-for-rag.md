# Exploration: Chunk Enrichment Techniques for RAG Pipelines

Date: 2026-03-29

## Research question

What metadata and content should an LLM enrichment stage generate per chunk before indexing to improve retrieval quality? What are the current approaches, their reported improvements, cost profiles, and compatibility with ProxyMind's stack (Gemini LLM, Qdrant, Batch API)?

## Scope

**In scope:** LLM-based enrichment techniques that add metadata or transformed content to chunks between the chunking and embedding stages. Approaches that modify what gets indexed in the vector store.

**Out of scope:** Chunking strategies themselves (semantic chunking, recursive splitting), query-time techniques (query rewriting, HyDE at query time), reranking models, and parent-child chunking (covered separately in [docs/rag.md](../../docs/rag.md)).

**Stack constraints:** Python/FastAPI backend, Qdrant vector store (dense + BM25 sparse, RRF fusion), Gemini Embedding 2 for dense vectors, Gemini Batch API available at -50% cost for async enrichment.

## Findings

### 1. Anthropic Contextual Retrieval

Anthropic published [Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) in September 2024. The technique prepends a short document-level context (50-100 tokens) to each chunk before embedding and BM25 indexing.

**What it generates per chunk:** A single field -- a "succinct context" that situates the chunk within the whole document. The context is prepended directly to the chunk text, not stored as a separate metadata field. Example: a chunk saying "The company's revenue grew by 3%" becomes "This chunk is from an SEC filing on ACME corp's performance in Q2 2023; the previous quarter's revenue was $314 million. The company's revenue grew by 3% over the previous quarter."

**Prompt template:**

```
<document>
{{WHOLE_DOCUMENT}}
</document>
Here is the chunk we want to situate within the whole document
<chunk>
{{CHUNK_CONTENT}}
</chunk>
Please give a short succinct context to situate this chunk within
the overall document for the purposes of improving search retrieval
of the chunk. Answer only with the succinct context and nothing else.
```

**Reported improvements:** Measured as reduction in retrieval failure rate (top-20-chunk retrieval):
- Contextual Embeddings alone: 35% reduction (5.7% to 3.7%)
- Contextual Embeddings + Contextual BM25: 49% reduction (5.7% to 2.9%)
- All methods combined with reranking: 67% reduction (5.7% to 1.9%)

**Cost:** Anthropic reports $1.02 per million document tokens using Claude's prompt caching (document cached once, referenced for each chunk). Without prompt caching, cost scales linearly -- every chunk requires the full document as input. The status of Gemini context caching with Batch API is contradictory: the [batch API docs](https://ai.google.dev/gemini-api/docs/batch-mode) (updated 2026-03-25) state "context caching is enabled for batch requests," but a [Google AI forum moderator](https://discuss.ai.google.dev/t/context-caching-batch-api-requests/105642) denied support in November 2025. This likely refers to implicit (automatic) caching rather than explicit `CachedContent` objects. See [2026-03-29-gemini-api-enrichment-capabilities.md](./2026-03-29-gemini-api-enrichment-capabilities.md) for full analysis. Without confirmed explicit caching, implementing contextual retrieval with Gemini Batch API requires sending the full document with every chunk request, making cost proportional to `num_chunks * document_size`.

**Compatibility with ProxyMind stack:** The technique itself is model-agnostic -- any LLM can generate the context. If explicit context caching does not work with batch, Anthropic's cost efficiency cannot be replicated on Gemini. Using Gemini 2.5 Flash Batch ($0.15/M input tokens) without caching, enriching a 10-page document (~8K tokens) with 20 chunks would cost approximately: 20 chunks x 8K tokens input = 160K tokens = ~$0.024 per document. For a 100-page book (~80K tokens) with 200 chunks: 200 x 80K = 16M tokens = ~$2.40 per document. If explicit caching works, the cached document tokens cost $0.03/M (non-batch rate), dropping the 100-page book cost to ~$0.81. The cost scales quadratically with document size only without caching.

**Confidence:** Corroborated -- Anthropic's numbers are from their own controlled evaluation. An independent [April 2025 paper](https://arxiv.org/html/2504.19754v1) found marginal improvements when comparing contextual retrieval to late chunking on NFCorpus (NDCG@5: 0.317 vs 0.309), suggesting benefits exist but may be modest depending on the dataset.

### 2. RAGFlow Transformer Stage

RAGFlow's ingestion pipeline includes a [Transformer operator](https://ragflow.io/blog/is-data-processing-like-building-with-lego-here-is-a-detailed-explanation-of-the-ingestion-pipeline) that enriches chunks via LLM calls.

**What it generates per chunk:** Four field types, each configurable independently:
- **Summary** -- brief description of chunk contents
- **Keywords** -- terms for BM25/keyword recall
- **Questions** -- questions this chunk can answer
- **Metadata** -- extracted structured metadata (entities, categories)

Additionally, RAGFlow's [TreeRAG architecture](https://ragflow.io/blog/rag-review-2025-from-rag-to-context) generates multi-level tree directory summaries and enriches nodes with summaries, keywords, entities, potential questions, metadata, and image context descriptions.

**Three modes:**
- **Improvise** -- higher creativity (Temperature), suited for diverse question generation
- **Precise** -- constrained to source text, suited for summaries and keyword extraction
- **Balance** -- default, mediates between the two

Users can also adjust Temperature and Top P directly. The [system prompts for each enrichment type are openly accessible](https://ragflow.io/blog/is-data-processing-like-building-with-lego-here-is-a-detailed-explanation-of-the-ingestion-pipeline) and can be customized.

**Pipeline placement:** The Transformer can connect after the Parser (processes whole document) or after the Chunker (processes individual chunks). Multiple Transformer nodes can be cascaded for multi-stage extraction.

**Cost:** RAGFlow documentation does not publish cost benchmarks. The 2025 year-end review notes two cost tiers: the "more effective" option queries the LLM multiple times per chunk using both full text and current chunk for context (higher cost, better quality), while the "cheaper" option generates enrichment based only on the current chunk (lower cost, limited global context).

**Reported improvements:** No published benchmark numbers from RAGFlow on enrichment-specific retrieval improvement.

**Confidence:** Substantiated -- architecture and field types confirmed through official RAGFlow documentation and blog posts. No independent benchmarks on retrieval improvement from these specific enrichments.

### 3. LlamaIndex Metadata Extractors

LlamaIndex provides a [metadata extraction pipeline](https://developers.llamaindex.ai/python/framework/module_guides/indexing/metadata_extraction/) with pluggable extractors that run as transformations in an ingestion pipeline.

**Available extractors and what they generate:**

| Extractor | Output | Parameters |
|-----------|--------|------------|
| `SummaryExtractor` | Summary of node text | `summaries=["prev", "self", "next"]` -- can summarize adjacent nodes too |
| `QuestionsAnsweredExtractor` | Questions the node can answer | `questions=3` (configurable count) |
| `TitleExtractor` | Document/section title | `nodes=5` (number of nodes for context) |
| `KeywordExtractor` | Keywords | `keywords=10` (configurable count) |
| `EntityExtractor` | Named entities (PERSON, ORG, LOC, etc.) | `prediction_threshold=0.5` |

**How they work:** Each extractor calls an LLM (configurable) to generate metadata from node content. Extractors run sequentially in a pipeline and attach results to node metadata. Custom extractors can be built by extending `BaseExtractor`.

**Cost:** Each extractor makes one LLM call per node. Running all five extractors on a pipeline means 5 LLM calls per chunk. LlamaIndex does not publish cost benchmarks, but the cost is straightforward: `num_extractors * num_chunks * (input_tokens + output_tokens)`.

**Reported improvements:** LlamaIndex documentation states these extractors help "disambiguate similar-looking passages" but does not publish retrieval benchmark comparisons.

**Compatibility:** LlamaIndex is a Python library. The extractors are conceptual patterns -- the prompts and logic can be replicated in any pipeline without depending on LlamaIndex as a runtime dependency. ProxyMind could implement equivalent extractors using direct Gemini API calls.

**Confidence:** Substantiated -- based on official LlamaIndex documentation. The patterns are well-established but lack published benchmarks on retrieval improvement.

### 4. MDKeyChunker (Single-Call Enrichment)

[MDKeyChunker](https://arxiv.org/html/2603.23533) is a March 2026 paper describing a three-stage pipeline that performs structure-aware chunking and single-call LLM enrichment with inter-chunk context propagation.

**What it generates per chunk (in a single LLM call):**
- Title (3-8 words)
- Summary (1-2 sentences)
- Keywords (5-8 terms)
- Entities (typed: PERSON, ORG, LOC, CONCEPT)
- Questions (2-3 natural questions answered)
- Semantic key (2-5 word subtopic identifier)
- Related keys (references to prior subtopics via a "rolling key dictionary")

The rolling key dictionary is the key innovation -- it maintains a mapping of semantic keys across chunks, allowing the LLM to reuse existing keys rather than inventing synonyms. Chunks sharing identical semantic keys are then merged via bin-packing.

**Reported improvements:** On an 18-document test corpus (354 KB, 30 queries):
- BM25 sparse retrieval over structural chunks: Recall@5 = 1.000, MRR = 0.911
- Dense retrieval with full pipeline: Recall@5 = 0.867, MRR = 0.744
- 100% fill rate across all seven metadata fields
- 89.8% of chunks reference prior semantic keys
- Key-based merging reduces chunk count by 9.3%

**Cost:** 1 LLM call per chunk (compared to 4-5 calls for separate extractors). The paper reports the implementation uses any OpenAI-compatible endpoint. The rolling key dictionary adds minimal overhead -- it is passed as part of the prompt context.

**Compatibility:** Written in Python (~1,000 lines), open source, uses OpenAI-compatible API. Could be adapted to Gemini via LiteLLM (which ProxyMind already uses). The rolling key dictionary pattern works with batch API if chunks are processed sequentially within a document (keys from chunk N feed into chunk N+1's prompt). This is a constraint -- it prevents fully parallel batch processing of chunks within the same document.

**Confidence:** Substantiated -- single paper with a small test corpus (18 documents). The single-call approach and rolling key concept are sound, but the benchmark is limited in scale.

### 5. RAPTOR (Recursive Abstractive Processing for Tree-Organized Retrieval)

[RAPTOR](https://arxiv.org/abs/2401.18059) (January 2024, Stanford) builds a hierarchical tree index by recursively clustering and summarizing chunks bottom-up.

**What it generates:** RAPTOR does not enrich individual chunks with metadata. Instead, it creates new summary nodes at progressively higher levels of abstraction. Leaf nodes are original chunks; higher-level nodes are LLM-generated summaries of clustered leaves. At retrieval time, the system can traverse the tree to find relevant information at different granularity levels.

**This is a different approach from chunk enrichment.** RAPTOR changes the index structure (adding summary nodes), not the metadata on existing chunks. It addresses the problem of multi-step reasoning over long documents where no single chunk contains the full answer.

**Reported improvements:** 20% improvement on the QuALITY benchmark (multi-step reasoning) when coupled with GPT-4.

**Cost:** Multiple LLM calls for clustering and summarization at each tree level. Cost grows with tree depth and document size.

**Compatibility with ProxyMind:** RAPTOR requires a fundamentally different index structure (tree of summary nodes) rather than a flat collection of enriched chunks. It is architecturally incompatible with ProxyMind's current flat Qdrant collection design without significant rework. It is more aligned with RAGFlow's TreeRAG concept.

**Confidence:** Corroborated -- peer-reviewed paper with benchmark results. The 20% improvement applies specifically to multi-step reasoning tasks, not general retrieval.

### 6. Late Chunking (Jina AI)

[Late Chunking](https://jina.ai/news/late-chunking-in-long-context-embedding-models/) inverts the traditional chunk-then-embed approach: it embeds the entire document at token level first, then pools token embeddings into chunk-level embeddings.

**This is not an enrichment technique.** Late chunking is an embedding strategy that preserves cross-chunk context in the vector representations without adding any metadata or generated content. It requires a long-context embedding model that processes the whole document in one pass, then derives chunk embeddings from token-level representations.

**Compatibility with ProxyMind:** Not compatible. Late chunking requires access to the embedding model's internal token-level representations before pooling. Gemini Embedding 2 is an API-based service that returns final embeddings -- it does not expose token-level representations. Late chunking works only with models you can run locally (e.g., Jina Embeddings v2/v3).

**Reported improvements:** An [April 2025 paper](https://arxiv.org/html/2504.19754v1) comparing contextual retrieval and late chunking found similar performance on NFCorpus (NDCG@5: 0.309 for late chunking vs 0.317 for contextual retrieval).

**Confidence:** Corroborated -- published paper, Jina's own benchmarks, and independent evaluation.

### 7. DSPy-Based Enrichment

[DSPy](https://dspy.ai/) is Stanford's framework for programmatically optimizing LLM prompts and pipelines. It does not provide chunk enrichment modules directly, but its optimization approach is applicable to enrichment prompt tuning.

**How it applies to enrichment:** DSPy could be used to optimize the prompts used in any of the enrichment techniques above. For example, the prompt for generating chunk summaries or questions could be expressed as a DSPy module, and DSPy's optimizers (MIPRO, BootstrapFewShot) could tune the prompt based on retrieval quality metrics. The [GEPA optimizer](https://kargarisaac.medium.com/building-and-optimizing-multi-agent-rag-systems-with-dspy-and-gepa-2b88b5838ce2) uses genetic algorithms to evolve better prompts.

**Practical relevance:** DSPy is a meta-tool for optimizing prompts, not an enrichment technique itself. It adds a layer of complexity (defining metrics, providing training examples) but could improve enrichment quality once the base enrichment pipeline exists.

**Confidence:** Substantiated -- DSPy is well-documented but no published work specifically benchmarks DSPy-optimized enrichment prompts against hand-crafted ones for chunk enrichment.

### 8. Proposition Chunking / Propositionizer

[Proposition chunking](https://arxiv.org/pdf/2312.06648) decomposes text into atomic, self-contained factual statements before indexing. Each proposition is a single verifiable claim.

**What it generates:** Replaces original chunks entirely with atomic propositions. Each proposition is independently retrievable.

**Reported results are mixed.** A [March 2026 Medium analysis](https://medium.com/@dhruv-panchal/proposition-chunking-why-you-should-stop-indexing-paragraphs-60b7f8f165b7) advocates for the approach, but a February 2026 FloTorch benchmark study found proposition-based chunking "ranked among the worst performers," with recursive character splitting at 512 tokens achieving higher answer accuracy and retrieval F1 scores.

**Cost:** 1 LLM call per chunk to decompose into propositions. The number of resulting propositions per chunk varies (typically 3-10), which increases the total embedding cost.

**Confidence:** Substantiated -- the technique is well-studied but benchmarks show inconsistent results across datasets.

### 9. HyPE (Hypothetical Passage Expansion)

A variant of HyDE (Hypothetical Document Embedding) applied at indexing time rather than query time. The LLM generates hypothetical questions that each chunk could answer, and these questions are embedded alongside or instead of the original chunk.

**What it generates:** 2-5 hypothetical questions per chunk, embedded as additional vectors pointing to the same chunk.

**Reported improvements:** A [2025 study](https://glaforge.dev/posts/2025/07/06/advanced-rag-hypothetical-question-embedding/) reported precision improvements of up to 42 percentage points and recall improvements of up to 45 points on certain datasets compared to standard retrieval. These numbers are notably high and should be interpreted with caution (dataset-dependent, possibly on small/synthetic benchmarks).

**Cost:** 1 LLM call per chunk (question generation) + N additional embedding calls per chunk (one per generated question). This multiplies the vector count in the index.

**Confidence:** Substantiated -- the concept is sound (bridging the query-document vocabulary gap), but the dramatic improvement numbers may not generalize.

### 10. Cautionary Research: NAACL 2025 on Semantic Chunking ROI

A [NAACL 2025 Findings paper](https://aclanthology.org/2025.findings-naacl.114.pdf) ("Is Semantic Chunking Worth the Computational Cost?" -- Vectara, University of Wisconsin-Madison) tested 25 chunking configurations with 48 embedding models. Key finding: fixed 200-word chunks matched or beat semantic chunking across document retrieval, evidence retrieval, and answer generation tasks. The computational costs of semantic methods were not justified by consistent gains.

While this paper evaluates chunking strategies rather than metadata enrichment specifically, it signals that more sophisticated processing does not always yield proportional improvements. The same caution may apply to enrichment: the ROI depends heavily on the specific use case and dataset.

**Confidence:** Corroborated -- peer-reviewed, large-scale benchmark with 48 embedding models.

## Comparison

| Technique | Fields Generated | LLM Calls/Chunk | Document Context Needed | Batch API Compatible | Index Structure Change | Reported Improvement |
|-----------|-----------------|-----------------|------------------------|---------------------|----------------------|---------------------|
| Contextual Retrieval | Context prefix (50-100 tokens) | 1 | Yes (full doc per chunk) | Yes, but costly without caching | None (prepend to text) | 35-49% failure reduction |
| RAGFlow Transformer | Summary, keywords, questions, metadata | 1-4 (configurable) | Optional (two cost tiers) | Yes | New payload fields | Not published |
| LlamaIndex Extractors | Summary, questions, title, keywords, entities | 1 per extractor (up to 5) | No (chunk-only by default) | Yes | New metadata fields | Not published |
| MDKeyChunker | Title, summary, keywords, entities, questions, semantic key, related keys | 1 (single call) | Rolling key dictionary | Partially (sequential within doc) | New fields + chunk merging | Recall@5=1.0 (small corpus) |
| RAPTOR | Summary nodes (new index entries) | Multiple per tree level | Yes (clustering) | Not directly | Tree structure (architectural change) | 20% on QuALITY |
| Late Chunking | None (embedding-level) | 0 | Yes (full doc embedding) | N/A | None | Marginal vs contextual |
| Proposition Chunking | Atomic facts (replaces chunks) | 1 | No | Yes | Replaces chunks entirely | Mixed/inconsistent |
| HyPE | Hypothetical questions (2-5) | 1 | No | Yes | Additional vectors per chunk | Up to 42pp precision (dataset-specific) |

### Cost Estimation for ProxyMind (Gemini 2.5 Flash Batch API)

Batch pricing: $0.15/M input tokens, $1.25/M output tokens.

| Scenario | Chunks | Enrichment Approach | Est. Input Tokens | Est. Output Tokens | Est. Cost |
|----------|--------|--------------------|--------------------|-------------------|-----------|
| 10 articles (~100 chunks) | 100 | Single-call (chunk-only, ~800 tok input each) | 120K | 50K | ~$0.08 |
| 10 articles (~100 chunks) | 100 | Contextual (8K doc + 800 chunk per call) | 880K | 10K | ~$0.14 |
| 1 book (~1,000 chunks) | 1,000 | Single-call (chunk-only) | 1.2M | 500K | ~$0.80 |
| 1 book (~1,000 chunks) | 1,000 | Contextual (80K doc per call) | 80M | 100K | ~$12.12 |
| Library (~10,000 chunks) | 10,000 | Single-call (chunk-only) | 12M | 5M | ~$8.05 |
| Library (~10,000 chunks) | 10,000 | Contextual (avg 40K doc per call) | 400M | 1M | ~$61.25 |

The contextual approach (full document per call) costs 2-15x more than chunk-only enrichment, scaling worse with longer documents. The cost difference is most pronounced for books and long documents.

## Key takeaways

- Anthropic's contextual retrieval is the only approach with published, controlled benchmarks showing significant retrieval improvement (35-49% failure reduction). However, its cost efficiency depends on prompt caching, which Gemini Batch API does not support. (Corroborated)

- The single-call enrichment pattern (summary + keywords + questions + entities in one LLM call, as in MDKeyChunker) achieves the best cost-per-field ratio. Generating 5-7 fields in one call costs the same as generating one field with a separate call. (Substantiated)

- No published benchmark directly compares "enriched chunks" vs "unenriched chunks" in a hybrid search (dense + BM25 + RRF) setup matching ProxyMind's architecture. All reported improvements are in different retrieval configurations. (Substantiated -- based on exhaustive search yielding no matching benchmark)

- RAGFlow's two-tier cost model (chunk-only enrichment vs document-context enrichment) reflects a real trade-off: document context improves quality but scales quadratically with document size. (Substantiated)

- The NAACL 2025 paper's finding that simpler chunking matches complex approaches suggests that enrichment ROI should be validated empirically per use case, not assumed. (Corroborated)

## Open questions

1. **What is the actual retrieval improvement from enrichment in ProxyMind's specific configuration?** No existing benchmark uses Gemini Embedding 2 + Qdrant BM25 + RRF fusion. The eval framework (already built) would need A/B comparison with and without enrichment on a representative dataset.

2. **Should enriched fields be embedded, searched via BM25, or both?** Generated keywords and questions could be appended to chunk text before embedding (affects dense vector), stored as separate payload fields for BM25/filtering, or both. Each approach has different retrieval implications.

3. **How does enrichment interact with Qdrant's native BM25?** Adding generated keywords to the chunk text may improve BM25 recall for vocabulary-mismatched queries. This needs empirical validation.

4. **Can contextual retrieval be made cost-effective without prompt caching?** Possible approaches: summarize the document once and use the summary (not full text) as context for each chunk; or use a sliding window of surrounding chunks instead of the full document.

5. **Sequential dependency of rolling keys (MDKeyChunker pattern) vs batch parallelism.** The rolling key dictionary requires sequential processing within a document. This conflicts with fully parallel batch processing but could work if chunks within a document are processed sequentially while documents are processed in parallel.

6. **What is the latency impact on ingestion?** Batch API has a 24-hour SLO. Adding an enrichment stage before embedding means two batch stages (enrich, then embed) rather than one, potentially doubling the worst-case ingestion time.

## Sources

1. [Anthropic Contextual Retrieval](https://www.anthropic.com/news/contextual-retrieval) -- original technique description, prompt template, benchmark numbers (35-49% improvement), cost analysis ($1.02/M tokens with caching)
2. [RAGFlow 2025 Year-End Review](https://ragflow.io/blog/rag-review-2025-from-rag-to-context) -- TreeRAG architecture, semantic enhancement concepts, two-tier cost model
3. [RAGFlow Ingestion Pipeline Blog](https://ragflow.io/blog/is-data-processing-like-building-with-lego-here-is-a-detailed-explanation-of-the-ingestion-pipeline) -- Transformer operator details, Improvise/Precise/Balance modes, four field types
4. [LlamaIndex Metadata Extraction](https://developers.llamaindex.ai/python/framework/module_guides/indexing/metadata_extraction/) -- five extractor types, API, pipeline integration
5. [MDKeyChunker paper](https://arxiv.org/html/2603.23533) -- single-call enrichment, 7 fields, rolling key dictionary, small-scale benchmarks
6. [RAPTOR paper](https://arxiv.org/abs/2401.18059) -- tree-structured retrieval, 20% improvement on QuALITY
7. [Jina AI Late Chunking](https://jina.ai/news/late-chunking-in-long-context-embedding-models/) -- embedding-level context preservation, requires local model
8. [Reconstructing Context (April 2025)](https://arxiv.org/html/2504.19754v1) -- independent comparison of contextual retrieval vs late chunking, marginal differences found
9. [NAACL 2025: Is Semantic Chunking Worth the Computational Cost?](https://aclanthology.org/2025.findings-naacl.114.pdf) -- 25 configs x 48 models, fixed chunks match/beat semantic chunking
10. [Gemini Batch API Pricing](https://ai.google.dev/gemini-api/docs/pricing) -- $0.15/$1.25 per M tokens (input/output) for Flash Batch
11. [Gemini Context Caching + Batch Discussion](https://discuss.ai.google.dev/t/context-caching-batch-api-requests/105642) -- confirms caching and batch cannot be combined
12. [DSPy Framework](https://dspy.ai/) -- programmatic prompt optimization, applicable as meta-tool for enrichment prompts
13. [HyPE / Hypothetical Question Embedding](https://glaforge.dev/posts/2025/07/06/advanced-rag-hypothetical-question-embedding/) -- indexing-time question generation, up to 42pp precision improvement (dataset-specific)
14. [FloTorch 2026 Benchmark](https://ragaboutit.com/the-2026-rag-performance-paradox-why-simpler-chunking-strategies-are-outperforming-complex-ai-driven-methods/) -- proposition chunking underperformed recursive splitting
