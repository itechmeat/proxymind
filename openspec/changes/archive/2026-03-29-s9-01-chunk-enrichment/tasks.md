## 1. Configuration

- [x] 1.1 Add enrichment settings to `backend/app/core/config.py` (`enrichment_enabled`, `enrichment_model`, `enrichment_max_concurrency`, `enrichment_temperature`, `enrichment_max_output_tokens`, `enrichment_min_chunk_tokens`)
- [x] 1.2 Write unit tests for enrichment settings defaults and overrides in `backend/tests/unit/test_enrichment_service.py`

## 2. Database Schema

- [x] 2.1 Add enrichment columns to Chunk model in `backend/app/db/models/knowledge.py` (`enriched_summary`, `enriched_keywords`, `enriched_questions`, `enriched_text`, `enrichment_model`, `enrichment_pipeline_version`)
- [x] 2.2 Generate and apply Alembic migration in `backend/migrations/versions/`
- [x] 2.3 Verify columns exist in PostgreSQL

## 3. Qdrant Payload Extension

- [x] 3.1 Add enrichment fields to `QdrantChunkPoint` dataclass in `backend/app/services/qdrant.py`
- [x] 3.2 Add `bm25_text` property to `QdrantChunkPoint` (returns `enriched_text` when available, `text_content` fallback)
- [x] 3.3 Update `_build_payload` to include enrichment fields
- [x] 3.4 Change BM25 source in `upsert_chunks` from `chunk.text_content` to `chunk.bm25_text`
- [x] 3.5 Write unit tests: payload with enrichment fields, payload without enrichment (None fields), BM25 uses enriched_text when available, BM25 falls back to text_content when unenriched

## 4. EnrichmentService Core

- [x] 4.1 Create `backend/app/services/enrichment.py` with `EnrichmentService` class (concurrent Gemini calls, semaphore, structured output, fail-open)
- [x] 4.2 Implement `EnrichmentResult` dataclass and `ENRICHMENT_PROMPT`
- [x] 4.3 Implement `build_enriched_text` with token budget truncation — priority: (1) try full enrichment, (2) drop questions, (3) drop keywords, (4) if summary alone exceeds budget return original `text_content` unchanged
- [x] 4.4 Write unit tests: successful enrichment, short chunk skip (<min_chunk_tokens), LLM failure returns None (fail-open), multiple chunks all enriched, text concatenation format, token overflow drops questions first, token overflow drops keywords second, over-budget returns original text

## 5. Pipeline Integration

- [x] 5.1 Add `enrichment_service` field to `PipelineServices` dataclass in `backend/app/workers/tasks/pipeline.py`
- [x] 5.2 Insert enrichment stage in `embed_and_index_chunks` BEFORE the batch/inline branch point
- [x] 5.3 Build `texts_for_embedding` list using enriched text (or original on failure)
- [x] 5.4 Persist enrichment data to Chunk DB rows before batch submission
- [x] 5.5 Update QdrantChunkPoint construction to include enrichment fields
- [x] 5.6 Initialize `EnrichmentService` conditionally in worker setup when `ENRICHMENT_ENABLED=true`
- [x] 5.7 Write test: Path B calls enrichment and passes enriched text to embedding
- [x] 5.8 Write test: Path C calls enrichment and passes enriched text to embedding
- [x] 5.9 Write test: Path A does NOT call enrichment (skips entirely)
- [x] 5.10 Write test: enrichment disabled (`ENRICHMENT_ENABLED=false`) — pipeline unchanged, no enrichment calls
- [x] 5.11 Write test: mixed enrichment results (some succeed, some fail) — succeeded chunks get enriched text, failed chunks use original text_content

## 6. Batch Orchestrator

- [x] 6.1 Update `_apply_results` in `backend/app/services/batch_orchestrator.py` to read enrichment fields from Chunk DB rows when building QdrantChunkPoint
- [x] 6.2 Write test: batch completion reads enrichment data from Chunk DB columns and includes it in Qdrant payload
- [x] 6.3 Write test: batch completion with unenriched chunks (enrichment columns NULL) — builds payload with None enrichment fields
- [x] 6.4 Verify existing batch orchestrator tests still pass

## 7. A/B Eval Dataset and Execution

- [x] 7.1 Create `backend/evals/datasets/retrieval_enrichment.yaml` with 6 vocabulary-gap cases (synonym, abstraction, paraphrase, terminology mismatch)
- [x] 7.2 Verify dataset loads correctly via eval loader
- [ ] 7.3 Run baseline eval (enrichment disabled) on all retrieval suites — save report as baseline
- [ ] 7.4 Enable enrichment, reindex seed knowledge into a new snapshot via existing snapshot workflow
- [ ] 7.5 Run enriched eval on all retrieval suites — save report
- [ ] 7.6 Run `compare.py` baseline vs enriched — produce comparison report with metric deltas and GREEN/YELLOW/RED zones
- [ ] 7.7 Write A/B comparison summary document with go/no-go recommendation on enabling enrichment by default

## 8. Documentation

- [x] 8.1 Update `docs/rag.md` — replace "Chunk enrichment (deferred)" section with implemented design including text source matrix
- [x] 8.2 Verify documentation consistency with pipeline diagrams

## 9. Verification

- [x] 9.1 Run full test suite and confirm all tests pass
- [x] 9.2 Verify pipeline works with enrichment disabled (default behavior unchanged)
- [x] 9.3 Run existing pipeline, Qdrant, and eval runner tests to confirm no regressions
- [x] 9.4 Verify eval runner correctly processes the new retrieval_enrichment dataset
- [x] 9.5 Verify compare.py correctly diffs baseline vs enriched reports
