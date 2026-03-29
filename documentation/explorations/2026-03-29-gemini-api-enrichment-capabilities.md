# Exploration: Gemini API Built-in Capabilities for Chunk Enrichment

Date: 2026-03-29

## Research question

Does the Google Gemini API ecosystem have built-in features that could simplify or replace manual chunk enrichment for RAG pipelines? Specifically: can the Batch API produce structured JSON output for 1000+ chunks? Can context caching reduce the cost of contextual enrichment? Does the Embedding API or Document AI provide any enrichment beyond vectors/OCR?

## Scope

**In scope:** Gemini Batch API structured output, context caching, structured output schemas, Gemini Embedding 2 metadata capabilities, Google Cloud Document AI enrichment capabilities. All evaluated against ProxyMind's enrichment needs (summary, keywords, questions per chunk).

**Out of scope:** Enrichment techniques themselves (covered in [2026-03-29-chunk-enrichment-techniques-for-rag.md](./2026-03-29-chunk-enrichment-techniques-for-rag.md)), third-party LLM provider capabilities, query-time techniques.

**Constraint:** ProxyMind uses Gemini Embedding 2, Gemini Batch API, LiteLLM, and Google Cloud Document AI as defined in [docs/spec.md](../../docs/spec.md).

## Findings

### 1. Gemini Batch API -- Structured Output Support

The Gemini Batch API supports structured output (JSON schema-validated responses) in batch mode. The [batch API documentation](https://ai.google.dev/gemini-api/docs/batch-mode) (updated 2026-03-25) explicitly demonstrates using `response_mime_type` and `response_schema` configurations in batch requests, including Pydantic model definitions.

**What this means for chunk enrichment:** A batch job can contain 1000+ `GenerateContentRequest` items, each with a prompt like "Given this chunk, return {summary, keywords, questions}" and a JSON schema enforcing the response structure. Each response is guaranteed to be syntactically valid JSON matching the schema.

**Submission methods:**
- Inline requests: up to 20 MB total payload size
- JSONL file upload: up to 2 GB via the Files API (suitable for large batches)

**Operational constraints:**
- Target turnaround: 24 hours, typically faster
- Jobs expire after 48 hours if not completed
- Not idempotent -- duplicate submissions create separate jobs
- Batch API pricing: 50% of standard interactive API rates

**Pricing for enrichment (Gemini 2.5 Flash Batch):**
- Input: $0.15 per 1M tokens (text/image/video)
- Output: $1.25 per 1M tokens

**Supported models include:** Gemini 2.5 Flash, Gemini 2.5 Pro, Gemini 3 Flash Preview, and others. The exact model list varies; model pages indicate batch support.

**Confidence:** Corroborated -- official documentation with code examples, confirmed by pricing page.

### 2. Gemini Structured Output -- Schema Capabilities

The [structured output documentation](https://ai.google.dev/gemini-api/docs/structured-output) confirms that Gemini can enforce JSON schema on responses.

**Configuration:**
- Set `response_mime_type: "application/json"`
- Set `response_json_schema` to a JSON Schema definition
- Python SDK supports Pydantic models directly via `Schema.model_json_schema()`

**Supported schema types:**
- `string` (with optional `enum`, `format`)
- `number`, `integer` (with `minimum`, `maximum`)
- `boolean`
- `object` (with `properties`, `required`, `additionalProperties`)
- `array` (with `items`, `minItems`, `maxItems`)
- Nullable types via `["string", "null"]`

**An enrichment schema like the following is fully expressible:**

```json
{
  "type": "object",
  "properties": {
    "summary": {"type": "string"},
    "keywords": {"type": "array", "items": {"type": "string"}, "minItems": 3, "maxItems": 10},
    "questions": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 5}
  },
  "required": ["summary", "keywords", "questions"]
}
```

**Limitations:**
- Only a subset of JSON Schema is supported; unsupported properties are silently ignored
- Very large or deeply nested schemas may be rejected
- Syntactic validity is guaranteed; semantic correctness is not (the model could generate a "summary" that is not actually a good summary)
- Streaming structured output returns valid partial JSON that concatenates into the final object

**Supported models:** Gemini 2.5 Pro, Gemini 2.5 Flash, Gemini 3 Flash Preview, Gemini 2.0 Flash. Models from Gemini 2.0 require explicit `propertyOrdering`.

**Confidence:** Corroborated -- official documentation with multiple examples across SDKs.

### 3. Gemini Context Caching -- Current State for Batch

This is the most complex finding due to contradictory sources.

**Two caching mechanisms exist:**

1. **Implicit caching** -- automatically enabled on Gemini 2.5+ models. No configuration needed. Google states "we automatically pass on cost savings if your request hits caches." No guarantee of a cache hit.

2. **Explicit caching** -- developer creates a `CachedContent` object containing content (document, system instructions, etc.), then references it in subsequent requests. Guaranteed cost savings on cache hits.

**Explicit caching pricing (Gemini 2.5 Flash):**
- Cached input tokens: $0.03 per 1M tokens (vs $0.30 standard = 90% reduction)
- Cache storage: $4.50 per 1M tokens per hour
- Minimum token count: 1,024 tokens (Flash), 4,096 tokens (Pro)
- Default TTL: 1 hour, configurable

**The critical question: does caching work with batch API?**

The [batch API documentation](https://ai.google.dev/gemini-api/docs/batch-mode) (updated 2026-03-25) states: "Context caching is enabled for batch requests. If a request in your batch results in a cache hit, the cached tokens are priced the same as for non-batch API traffic."

However, a [Google AI Developer Forum thread](https://discuss.ai.google.dev/t/context-caching-batch-api-requests/105642) from November 2025 includes a moderator stating: "Context Caching is not currently supported with the Batch API." Users reported explicit errors: "Model gemini-2.5-flash-001 does not support cached content with batch prediction."

**Interpretation of the contradiction:**
- The batch docs were updated on 2026-03-25, four months after the forum denial
- The batch docs statement likely refers to **implicit caching** (automatic deduplication), not explicit `CachedContent` objects -- the phrasing "if a request results in a cache hit" aligns with implicit/automatic behavior rather than developer-managed explicit caches
- The forum thread specifically discusses **explicit caching** (`CachedContent` objects referenced in batch requests), which produced errors
- The [caching documentation page](https://ai.google.dev/gemini-api/docs/caching) makes no mention of batch API at all

**What this means for contextual enrichment:**
- **Explicit caching + batch (cache document, reference in each chunk request):** Status unclear. Was explicitly broken as of November 2025. May or may not work as of March 2026. The official docs do not clearly confirm explicit cache support in batch.
- **Implicit caching in batch:** Appears to be supported per the March 2026 docs. If a batch contains 200 requests all with the same document prefix, implicit caching may deduplicate the shared content. No cost savings guarantee.
- **Cached token pricing in batch:** Cached tokens are priced at non-batch rates ($0.03/M for Flash), not at the 50% batch discount. Non-cached tokens get the standard batch discount ($0.15/M).

**Confidence:** Substantiated with caveats -- official docs and forum are contradictory. The situation may have changed between November 2025 and March 2026, but no explicit announcement confirms this. Testing would be required to determine whether explicit `CachedContent` objects work in batch as of the current date.

### 4. Gemini Embedding 2 -- No Built-in Enrichment

The [embeddings documentation](https://ai.google.dev/gemini-api/docs/embeddings) is unambiguous: the Embedding API returns **only embedding vectors**. The documentation explicitly states: "Unlike generative AI models that create new content, the Gemini Embedding model is only intended to transform the format of your input data into a numerical representation."

**What the API returns:** An array of floating-point values (the embedding vector). Nothing else -- no keywords, no summaries, no entities, no confidence scores, no token counts.

**Task types available (optimize the vector, not add metadata):**
- `SEMANTIC_SIMILARITY`
- `CLASSIFICATION`
- `CLUSTERING`
- `RETRIEVAL_DOCUMENT` (used for indexing in ProxyMind)
- `RETRIEVAL_QUERY` (used for search in ProxyMind)
- `CODE_RETRIEVAL_QUERY`
- `QUESTION_ANSWERING`
- `FACT_VERIFICATION`

**Dimensions:** 128-3,072 (Matryoshka representation learning allows truncation).

**Input limits for `gemini-embedding-2-preview`:** 8,192 tokens max across all modalities. Supports text, images (6 max), audio (80s max), video (120s max), PDFs (6 pages max).

**Confidence:** Corroborated -- explicit documentation statement rules out any enrichment capability.

### 5. Google Cloud Document AI -- Limited Enrichment Potential

Document AI provides several processors, some of which extract structured data that could partially serve enrichment needs.

**Processors with enrichment-relevant output:**

| Processor | Output | Enrichment Relevance |
|-----------|--------|---------------------|
| Summarizer | Abstract and bullet-point summaries | Directly produces summaries (up to 250 pages in batch) |
| Form Parser | Key-value pairs + 11 generic entity types (email, phone, URL, date_time, address, person, organization, quantity, price, id, page_number) | Entity extraction overlaps with enrichment needs |
| Layout Parser | Context-aware chunks with ancestral headings and table headers | Structural context, not semantic enrichment |
| Custom Extractor | Developer-defined fields using generative AI | Could be configured for enrichment but requires separate setup |

**What Document AI does NOT do:**
- Does not extract keywords
- Does not generate questions a passage can answer
- Does not produce semantic summaries at the chunk level (Summarizer works on whole documents, not individual chunks)
- Does not generate metadata designed for retrieval optimization

**Layout Parser for RAG:** The Layout Parser creates "context-aware chunks" that preserve hierarchical structure (heading ancestry, table headers). This is structural enrichment -- it ensures chunks carry their section context. It does not add LLM-generated semantic metadata (summaries, keywords, questions). ProxyMind's Path C already uses Document AI for parsing; the Layout Parser's chunking could replace custom chunking for Path C documents but would not substitute for LLM-based enrichment.

**Summarizer processor:** Generates document-level summaries (abstract + bullet points) for documents up to 250 pages in batch mode. This could produce a document-level summary to use as context in chunk enrichment prompts (similar to the Anthropic contextual retrieval approach but using a pre-generated summary instead of the full document). It does not operate at the chunk level.

**Entity extraction via Form Parser:** Extracts 11 generic entity types. This is limited to structured entities (names, dates, organizations) and does not cover the broader semantic enrichment (summaries, keywords, questions) needed for retrieval improvement.

**Confidence:** Substantiated -- based on official Document AI documentation. The Summarizer's potential as a document-level context provider for chunk enrichment is an inference, not a documented use case.

## Comparison

### What IS possible with each technology

| Capability | Batch API | Structured Output | Context Caching | Embedding 2 | Document AI |
|-----------|-----------|-------------------|-----------------|-------------|-------------|
| Generate summary per chunk | Yes (via LLM prompt) | Enforces JSON schema on output | Reduces cost of repeated context | No | Document-level only (Summarizer) |
| Generate keywords per chunk | Yes (via LLM prompt) | Enforces array schema | Reduces cost of repeated context | No | No |
| Generate questions per chunk | Yes (via LLM prompt) | Enforces array schema | Reduces cost of repeated context | No | No |
| Extract entities | Yes (via LLM prompt) | Enforces typed schema | Reduces cost of repeated context | No | 11 types (Form Parser) |
| Process 1000 chunks | Yes (JSONL file, up to 2GB) | Yes (per-request schema) | Unknown for explicit caching | N/A | Yes (batch processing) |
| 50% cost reduction | Yes | N/A (no cost impact) | 90% input reduction (explicit) | N/A | No (standard pricing) |

### What IS NOT possible

| Limitation | Technology |
|-----------|-----------|
| Embedding API cannot extract any metadata | Embedding 2 |
| Document AI cannot generate keywords or questions | Document AI |
| Document AI Summarizer works at document level, not chunk level | Document AI |
| Explicit context caching may not work with batch API | Context Caching + Batch |
| Cached tokens in batch are priced at non-batch rates | Context Caching + Batch |
| Structured output does not guarantee semantic quality | Structured Output |

### Cost modeling: enrichment approaches using Gemini 2.5 Flash Batch

Scenario: 1,000 chunks from a single 80K-token document.

| Approach | Input Tokens | Output Tokens | Input Cost | Output Cost | Total |
|----------|-------------|---------------|------------|-------------|-------|
| Chunk-only enrichment (800 tok prompt + chunk per call) | 1.2M | 500K | $0.18 | $0.63 | $0.81 |
| Contextual enrichment (80K doc + chunk per call, no caching) | 80M | 500K | $12.00 | $0.63 | $12.63 |
| Contextual with explicit caching (if it works in batch) | 80K (cached) + 1.2M (uncached) | 500K | $0.002 (cached) + $0.18 | $0.63 | $0.81 |
| Contextual with doc summary (5K summary + chunk per call) | 5.8M | 500K | $0.87 | $0.63 | $1.50 |

Notes:
- Cached token rate: $0.03/M (non-batch rate, per batch docs)
- Non-cached batch rate: $0.15/M input, $1.25/M output
- "Contextual with doc summary" uses the Document AI Summarizer to generate a ~5K token summary first, then includes it with each chunk instead of the full 80K document

## Key takeaways

- Gemini Batch API fully supports structured output (JSON schema validation) in batch mode, enabling schema-enforced enrichment responses (summary + keywords + questions) for 1000+ chunks in a single batch job. (Corroborated)

- Gemini Embedding 2 provides no metadata, enrichment, or content analysis -- it returns only embedding vectors. Any enrichment must come from a separate LLM call. (Corroborated)

- The status of explicit context caching with Batch API is contradictory: official docs (March 2026) say "context caching is enabled for batch requests," but a moderator on the Google AI forum (November 2025) said it is not supported, and users reported errors. This likely refers to implicit (automatic) caching, not explicit `CachedContent` objects. Testing is required to resolve. (Substantiated -- contradictory sources)

- Document AI provides document-level summarization and entity extraction (11 types) but does not generate chunk-level summaries, keywords, or questions. Its Summarizer could produce a condensed document context (~5K tokens) to include in chunk enrichment prompts as a cheaper alternative to sending the full document. (Substantiated)

- Even if explicit caching works in batch, cached tokens are priced at non-batch rates ($0.03/M for Flash vs $0.15/M batch). The cost difference between cached-contextual and chunk-only enrichment is small enough that contextual enrichment becomes viable if caching works. (Substantiated -- per pricing page)

## Open questions

1. **Does explicit `CachedContent` work with Gemini Batch API as of March 2026?** The only way to resolve the documentation contradiction is to test it. Create an explicit cache, submit a batch referencing it, and observe whether the job succeeds or fails.

2. **Does implicit caching in batch reliably hit when all requests share the same document prefix?** The docs mention automatic cost savings but provide no guarantee. A batch of 200 requests with identical 80K prefixes may or may not trigger implicit cache hits.

3. **What is the actual turnaround time for a 1000-request enrichment batch?** The SLO is 24 hours, but docs say "in majority of cases, it is much quicker." Real-world turnaround data for structured output batches is not published.

4. **Can Document AI Summarizer output be used as context caching input?** The workflow would be: Summarizer generates a 5K-token document summary, cache it, then reference it in 200 chunk enrichment requests. This depends on question 1.

5. **Does Gemini 3 Flash support batch mode?** The batch docs reference `gemini-3-flash-preview` but Gemini 3 Flash does not show batch pricing on the pricing page (only standard/free tiers are listed). It may be available but unpriced during preview.

## Sources

1. [Gemini Batch API documentation](https://ai.google.dev/gemini-api/docs/batch-mode) -- structured output support in batch, context caching statement, submission methods, limits (updated 2026-03-25)
2. [Gemini Context Caching documentation](https://ai.google.dev/gemini-api/docs/caching) -- implicit vs explicit caching, minimum tokens, TTL, pricing model
3. [Gemini Structured Output documentation](https://ai.google.dev/gemini-api/docs/structured-output) -- JSON schema support, supported types, limitations, model compatibility
4. [Gemini Embeddings documentation](https://ai.google.dev/gemini-api/docs/embeddings) -- confirms vector-only output, task types, input limits
5. [Gemini API Pricing](https://ai.google.dev/gemini-api/docs/pricing) -- per-model token rates for standard, batch, and cached tiers
6. [Google AI Developer Forum: Context Caching + Batch](https://discuss.ai.google.dev/t/context-caching-batch-api-requests/105642) -- moderator denial of batch+caching (November 2025), user error reports
7. [Document AI Overview](https://docs.cloud.google.com/document-ai/docs/overview) -- processor types, Summarizer, entity extraction
8. [Document AI Processors List](https://docs.cloud.google.com/document-ai/docs/processors-list) -- detailed processor capabilities, Form Parser entity types, Layout Parser chunking
9. [Document AI Layout Parser Chunking](https://docs.cloud.google.com/document-ai/docs/layout-parse-chunk) -- context-aware chunks with ancestral headings
