## Story

**S9-01: Chunk enrichment** — Phase 9: RAG Upgrades (based on eval results).

Verification criteria from plan: A/B eval — with enrichment vs without → documented improvement.

Stable behavior requiring test coverage: EnrichmentService public API, ingestion pipeline (Path B/C), Qdrant upsert, BM25 sparse vector generation, eval runner.

## Why

Retrieval quality depends on overlap between how users phrase queries and how information is stored in chunks. Current hybrid search (dense + BM25 + RRF) partially addresses this, but vocabulary mismatch (synonyms, abstraction level, question-vs-statement phrasing) remains a gap. Chunk enrichment adds LLM-generated metadata (summary, keywords, questions) at indexing time to close this gap.

This is an experiment — no benchmark exists for our specific stack (Gemini Embedding 2 + Qdrant BM25 + RRF). The A/B eval is the deliverable that validates whether enrichment should be enabled.

## What Changes

- New `EnrichmentService` generates summary, keywords, and questions per chunk via Gemini structured output
- Enriched text concatenated to chunk text before both dense embedding and BM25 sparse vector generation
- Original `text_content` preserved for LLM context and citations (clean text, no artifacts)
- New nullable columns on `chunks` DB table for enrichment persistence (Alembic migration): `enriched_summary`, `enriched_keywords`, `enriched_questions`, `enriched_text`, `enrichment_model`, `enrichment_pipeline_version`
- Extended Qdrant payload with enrichment fields
- BM25 sparse vector source changed from `text_content` to the `bm25_text` property, which resolves to `enriched_text` when available and falls back to `text_content`
- Feature flag `ENRICHMENT_ENABLED` (default: false) controls activation
- New vocabulary-gap eval dataset for A/B comparison
- Applies to Path B and C only; Path A (already LLM-generated text) skips enrichment

## Error Handling

Enrichment is fail-open by design. `EnrichmentService` performs up to 3 retries with exponential backoff for retryable Gemini errors before giving up on an individual chunk. Per-chunk failures do not fail ingestion: the affected chunk continues through the pipeline using original `text_content`, and its enrichment columns remain `NULL`. If the enrichment service is unavailable for the whole batch, the pipeline falls back to processing all chunks without enrichment rather than failing the source. Short chunks are skipped before any Gemini call.

Operational visibility for this story is provided through structured logs emitted by the enrichment path. Dedicated metrics/alerting are not introduced in this change and remain future observability work.

## Migration Strategy

The Alembic migration is additive only. Existing rows in `chunks` remain with `NULL` enrichment fields after migration. They are treated as un-enriched until they are reindexed into a new snapshot through the existing snapshot workflow; there is no in-place backfill job in this change. This keeps the migration low-risk and aligns with the A/B eval strategy, where baseline snapshots remain un-enriched and enriched behavior is validated on a separately reindexed snapshot.

## Capabilities

### New Capabilities

- `chunk-enrichment`: LLM enrichment service, pipeline integration, configuration, DB schema, Qdrant payload extension, token budget enforcement, A/B eval dataset

### Modified Capabilities

- `ingestion-pipeline`: Enrichment stage inserted between chunking and embedding; enriched text used for both dense embedding and BM25; batch flow reads enrichment from DB columns
- `vector-storage`: BM25 source changed from `text_content` to `bm25_text` property (backed by `enriched_text` when available); payload extended with enrichment fields

## Impact

- **Backend code:** new service (`enrichment.py`), modified pipeline (`pipeline.py`), modified Qdrant service (`qdrant.py`), modified batch orchestrator (`batch_orchestrator.py`), modified config (`config.py`), modified Chunk model (`knowledge.py`)
- **Database:** new Alembic migration adding 6 nullable columns to `chunks` table
- **Dependencies:** none new — uses existing `google-genai` SDK
- **API:** no public API changes
- **Cost:** ~$1.60 per 1000 chunks (Gemini 2.5 Flash interactive pricing); owner-controlled via feature flag
- **Ingestion time:** marginal increase for interactive enrichment calls (concurrent with semaphore); no additional batch stages
