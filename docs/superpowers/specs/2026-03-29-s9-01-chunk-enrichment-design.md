# S9-01: Chunk Enrichment — Design Spec

## Overview

Add an LLM enrichment stage to the ingestion pipeline that generates `summary`, `keywords`, and `questions` per chunk before embedding. Enriched metadata is concatenated to chunk text before indexing, improving retrieval quality by closing the vocabulary gap between user queries and document content.

Enrichment is gated behind a feature flag (`ENRICHMENT_ENABLED`), uses concurrent Gemini API calls (interactive mode), and requires A/B eval to validate whether enrichment provides measurable improvement. This is an experiment — improvement is hypothesized, not guaranteed.

## Problem Statement

Retrieval quality depends on overlap between how users phrase questions and how information is stored in chunks. Common failure modes:

- **Synonym mismatch:** user asks about "company earnings" but chunk contains "revenue growth"
- **Abstraction gap:** user asks "How to deploy?" but chunk contains step-by-step instructions without the word "deploy"
- **Question-statement gap:** user asks a question, chunk contains a declarative statement

Hybrid search (dense + BM25 + RRF) and query rewriting partially address this, but enrichment closes the remaining gap by adding search-optimized metadata at indexing time.

**Key uncertainty:** Whether enrichment provides measurable improvement over the current pipeline is unknown. No benchmark exists for our specific configuration (Gemini Embedding 2 + Qdrant BM25 + RRF). This story includes A/B eval to answer that question.

## Research Summary

A research exploration was conducted before this design (see `documentation/explorations/2026-03-29-chunk-enrichment-techniques-for-rag.md`). Key findings that shaped design decisions:

| Approach | Verdict | Reason |
|----------|---------|--------|
| Anthropic Contextual Retrieval | Deferred | Requires full document per chunk call; Gemini Batch API lacks prompt caching; cost ~15x higher |
| RAGFlow Transformer (summary + keywords + questions) | Adopted (pattern) | Proven field set; chunk-only enrichment is cost-effective |
| LlamaIndex Metadata Extractors | Not adopted (dependency) | Same concept as RAGFlow but adds heavyweight framework dependency; we implement the same pattern natively |
| MDKeyChunker rolling key dictionary | Deferred | Sequential dependency within documents conflicts with batch parallelism |
| HyPE (hypothetical questions) | Partially adopted | Questions field serves the same purpose |
| RAPTOR / Late Chunking / Proposition Chunking | Rejected | Architectural incompatibility or inconsistent benchmarks |
| LlamaIndex as dependency | Rejected | Adds heavyweight framework for 3 prompts; native Gemini API with structured output covers the same need with zero new dependencies |
| Google Gemini native capabilities | Leveraged | Structured Output (JSON Schema) = syntactically validated JSON enrichment, no new dependencies. Batch API available as future cost optimization |

## Design Decisions

### Decision Log

| # | Question | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Research before design? | Yes, quick exploration | RAGFlow may have updated; new techniques (Anthropic Contextual Retrieval, MDKeyChunker) emerged since docs were written |
| 2 | Enrichment strategy | Single-call chunk-only via Gemini interactive API (concurrent asyncio.gather) | No new dependencies; structured output guarantees syntactically valid JSON (semantic quality not guaranteed — validated via A/B eval); fully parallelizable. Gemini Batch API for enrichment deferred — interactive concurrent calls are sufficient and simpler. Document-context enrichment deferred — cost-prohibitive without prompt caching |
| 3 | Fields to generate | summary + keywords + questions | Covers vocabulary gap (keywords for BM25, questions for dense, summary for both). Entities/title/semantic keys rejected per YAGNI — anchor metadata already provides structural context |
| 4 | How enriched data affects retrieval | Concatenation to text before embedding + BM25 | Zero changes to retrieval pipeline. Enriched text improves both dense vector and BM25 sparse vector automatically. Separate named vectors for enriched fields rejected — adds complexity without proven need |
| 5 | Path A handling | Skip enrichment | Path A text_content is already LLM-generated (description, transcript). Enrichment adds marginal value at extra cost. Can be revisited if eval shows poor media retrieval |
| 6 | Reindex mechanism | New snapshot (draft → publish → activate) | Uses existing snapshot lifecycle. Rollback built in. No new mechanisms needed |
| 7 | Feature flag | `ENRICHMENT_ENABLED=false` by default | Required for A/B eval (one snapshot without, one with). Owner controls cost impact. Easy to disable if no improvement measured |

## Architecture

### Pipeline with Enrichment

```text
Path A (unchanged):
  file → Gemini LLM (text_content) → Gemini Embedding 2 → Qdrant

Path B (with enrichment):
  file → LightweightParser → TextChunker → [EnrichmentService] → Gemini Embedding 2 → Qdrant

Path C (with enrichment):
  file → Document AI → TextChunker → [EnrichmentService] → Gemini Embedding 2 → Qdrant
```

Enrichment stage is conditional: only runs when `ENRICHMENT_ENABLED=true`. When disabled, pipeline behaves exactly as before.

### EnrichmentService

**Location:** `backend/app/services/enrichment.py`

**Responsibilities:**
- Accept a list of chunks
- Call Gemini LLM (interactive, concurrent with semaphore) with structured output
- Return per-chunk enrichment results
- Handle failures gracefully (fail-open per chunk)

**Input:** `list[ChunkData]` (text_content, chunk_index, anchors)
**Output:** `list[EnrichmentResult]` with `{summary: str, keywords: list[str], questions: list[str]}`

**Prompt:**

```text
You are a search optimization assistant. Given a text chunk from a document,
generate metadata to improve search retrieval.

<chunk>
{text_content}
</chunk>

Return a JSON object with:
- "summary": 1-2 sentence description of what this chunk contains
- "keywords": 5-8 search terms including synonyms and related concepts
  not explicitly in the text
- "questions": 2-3 natural questions this chunk can answer
```

**Structured output:** Gemini `response_schema` with JSON Schema enforcement — guarantees syntactically valid JSON. Schema:

```json
{
  "type": "object",
  "properties": {
    "summary": {"type": "string"},
    "keywords": {"type": "array", "items": {"type": "string"}},
    "questions": {"type": "array", "items": {"type": "string"}}
  },
  "required": ["summary", "keywords", "questions"]
}
```

**Execution mode:** Interactive only — concurrent `asyncio.gather` of individual Gemini API calls. Concurrency is controlled by `ENRICHMENT_MAX_CONCURRENCY` (default: 10) to respect API rate limits. Gemini Batch API for enrichment is deferred — interactive concurrent calls are sufficient for current scale and simpler to implement.

**Model:** Configurable via `ENRICHMENT_MODEL` (default: `gemini-2.5-flash`). Low temperature (0.1) for factual extraction.

### Text Concatenation

Enriched text for embedding and BM25:

```text
{text_content}

Summary: {summary}
Keywords: {', '.join(keywords)}
Questions: {'\n'.join(questions)}
```

This concatenated text (`enriched_text`) is used for:
- Dense embedding (Gemini Embedding 2)
- BM25 sparse vector generation

The original `text_content` is preserved separately in Qdrant payload for LLM context during generation (clean text without enrichment artifacts).

### Qdrant Payload Extension

New fields added to chunk payload:

```python
{
    # Existing fields — unchanged
    "text_content": str,              # Original chunk text (for LLM context)
    "chunk_id": str,
    "snapshot_id": str,
    # ... all existing fields ...

    # New enrichment fields
    "enriched_summary": str | None,
    "enriched_keywords": list[str] | None,
    "enriched_questions": list[str] | None,
    "enriched_text": str | None,              # Full concatenated text used for embedding
    "enrichment_model": str | None,           # e.g. "gemini-2.5-flash"
    "enrichment_pipeline_version": str | None, # e.g. "s9-01-enrichment-v1"
}
```

- Prefix `enriched_` distinguishes generated fields from original data
- `enriched_text` stored for reproducibility — records exactly what was embedded
- `enrichment_model` and `enrichment_pipeline_version` for audit trail
- No new payload indexes — enriched fields are not used for filtering

### Text Source Matrix

Enrichment introduces multiple text representations. This matrix defines which text is used where:

| Consumer | Source | Why |
|----------|--------|-----|
| Dense embedding (Gemini Embedding 2) | `enriched_text` (or `text_content` if unenriched) | Enriched keywords/questions improve semantic match |
| BM25 sparse vector | `enriched_text` (or `text_content` if unenriched) | Enriched keywords close vocabulary gap for lexical search |
| LLM context (answer generation) | `text_content` (original, always) | Clean text without enrichment artifacts avoids confusing the LLM |
| Citation display | `text_content` (original, always) | User sees original document text, not generated metadata |
| Qdrant payload storage | Both: `text_content` + `enriched_text` + individual enrichment fields | Full audit trail; `text_content` for LLM, `enriched_text` for reproducibility |

### Pipeline Integration Point

**File:** `backend/app/workers/tasks/pipeline.py` → `embed_and_index_chunks()`

Enrichment runs **before** both inline and batch embedding paths:

```text
1. If ENRICHMENT_ENABLED:
   a. Call EnrichmentService.enrich(chunks) — concurrent asyncio.gather
   b. For each chunk with successful enrichment:
      - Build enriched_text (concatenation)
      - Store enrichment data in Chunk DB rows (new columns)
   c. For failed chunks: proceed with original text_content
2. Build texts_for_embedding list (enriched_text or text_content per chunk)
3. Branch:
   a. Inline path: EmbeddingService.embed_texts(texts_for_embedding) → Qdrant upsert
   b. Batch path: submit texts_for_embedding to Gemini Batch API → BatchSubmittedResult
      (batch_orchestrator._apply_results reads enrichment data from Chunk DB rows)
4. Qdrant upsert uses enriched_text for both dense embedding and BM25 sparse vector
```

**Key change to Qdrant upsert:** `upsert_chunks()` must use `chunk.enriched_text or chunk.text_content` for BM25 document construction (currently hardcoded to `chunk.text_content`).

### Database Schema Change

New nullable columns on the `chunks` table (Alembic migration required):

| Column | Type | Description |
|--------|------|-------------|
| `enriched_summary` | `TEXT NULL` | LLM-generated summary |
| `enriched_keywords` | `JSONB NULL` | LLM-generated keywords array |
| `enriched_questions` | `JSONB NULL` | LLM-generated questions array |
| `enriched_text` | `TEXT NULL` | Full concatenated text used for embedding |
| `enrichment_model` | `VARCHAR(100) NULL` | Model used for enrichment |
| `enrichment_pipeline_version` | `VARCHAR(50) NULL` | Pipeline version tag |

These columns serve as the persistence contract between the enrichment stage and the batch embedding completion handler (`batch_orchestrator._apply_results`). When batch embedding completes asynchronously, it reads enrichment data from these columns to build the full Qdrant payload.

## Configuration

New environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `ENRICHMENT_ENABLED` | `false` | Feature flag — enables enrichment stage |
| `ENRICHMENT_MODEL` | `gemini-2.5-flash` | LLM model for enrichment |
| `ENRICHMENT_MAX_CONCURRENCY` | `10` | Max concurrent enrichment API calls |
| `ENRICHMENT_TEMPERATURE` | `0.1` | Low creativity for factual extraction |
| `ENRICHMENT_MAX_OUTPUT_TOKENS` | `512` | Per-chunk output token budget |
| `ENRICHMENT_MIN_CHUNK_TOKENS` | `10` | Minimum chunk size to attempt enrichment |

Added to existing `Settings` class in `backend/app/core/config.py` via Pydantic Settings.

## Reindex

Reindexing with enrichment uses the existing snapshot workflow:

1. Enable `ENRICHMENT_ENABLED=true` in `.env`
2. `POST /api/admin/snapshots` → create draft
3. Reindex task processes all sources from active snapshot: re-parse → chunk → **enrich** → embed → upsert into draft
4. `POST /api/admin/snapshots/:id/publish?activate=true`
5. Previous snapshot remains available for rollback

No new endpoints or mechanisms required.

## A/B Eval

### Methodology

1. **Baseline:** Run eval with current pipeline (no enrichment) → save report as baseline
2. **Enriched:** Reindex same sources with `ENRICHMENT_ENABLED=true` → run eval → save report
3. **Compare:** `compare.py` produces delta per metric with GREEN/YELLOW/RED zones

### New Eval Cases

Extend existing datasets with vocabulary-gap-specific cases:

**retrieval_enrichment.yaml** — new dataset targeting enrichment impact:
- Synonym queries: "company earnings" → chunk about "revenue growth"
- Question-form queries: "How to deploy the application?" → chunk with deployment steps
- Abstract queries: "what about the costs?" → chunk with pricing details
- Terminology mismatch: domain-specific term vs layman's term

### Deliverable

A comparison report documenting:
- Metric deltas (Precision@K, Recall@K, MRR, groundedness, citation_accuracy)
- Per-case analysis of worst performers
- Go/no-go decision on enabling enrichment by default

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Enrichment LLM returns invalid JSON | Should not happen (structured output). If it does: chunk indexed without enrichment (fail-open), `enriched_*` fields = `None` |
| Enrichment LLM timeout | Chunk indexed without enrichment |
| Batch enrichment partial failure | Each chunk independent. Succeeded → enriched, failed → unenriched. Partial results applied |
| Token overflow (text + enrichment > 8192) | Enriched text truncated: questions removed first, then keywords, summary preserved last |
| Empty/tiny chunk (< `ENRICHMENT_MIN_CHUNK_TOKENS` tokens) | Enrichment skipped |
| `ENRICHMENT_ENABLED=false` | Entire enrichment stage skipped. Pipeline unchanged |

## Cost Estimation

Gemini 2.5 Flash interactive API: $0.30/M input tokens, $2.50/M output tokens.
(Batch API at -50% available as future optimization if needed.)

| Knowledge base | Chunks | Est. cost (interactive) |
|----------------|--------|------------------------|
| 10 articles | ~100 | ~$0.16 |
| 1 book | ~1,000 | ~$1.60 |
| Small library | ~10,000 | ~$16.10 |

Cost is per-enrichment-pass. Embedding cost is additional (same as current pipeline).

## Testing Strategy

### CI (deterministic)
- EnrichmentService unit tests: mock Gemini → verify structured output parsing
- Pipeline integration: verify enrichment stage is skipped when disabled, called when enabled
- Payload construction: verify enriched fields in Qdrant payload
- Token overflow: verify truncation logic
- Fail-open: verify graceful degradation on enrichment failure

### Evals (on real models)
- A/B comparison: enriched vs unenriched snapshots
- Vocabulary-gap-specific eval cases
- Cost tracking per enrichment run

## Out of Scope

- Document-context enrichment (full document per chunk call) — deferred, cost-prohibitive without prompt caching
- Separate named vectors for enriched fields — deferred, no proven need
- Path A enrichment — deferred, text_content already LLM-generated
- Rolling key dictionary (MDKeyChunker pattern) — deferred, conflicts with batch parallelism
- DSPy prompt optimization — deferred, requires baseline enrichment first
- Retrieval pipeline changes — enrichment improves retrieval purely through better embeddings/BM25, no retrieval code changes
