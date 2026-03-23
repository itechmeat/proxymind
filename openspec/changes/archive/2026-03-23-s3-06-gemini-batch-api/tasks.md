## 1. Schema Extension — Enums + Migration + Config

- [x] 1.1 Add `BATCH_EMBEDDING` to `BackgroundTaskType` in `app/db/models/enums.py`
- [x] 1.2 Update `test_task_status.py` to expect `["INGESTION", "BATCH_EMBEDDING"]`
- [x] 1.3 Extend `BatchJob` model in `app/db/models/operations.py` with new columns: `snapshot_id`, `source_ids` (UUID ARRAY), `background_task_id` (FK), `request_count`, `succeeded_count`, `failed_count`, `result_metadata` (JSONB), `last_polled_at`
- [x] 1.4 Add batch settings to `app/core/config.py`: `batch_embed_chunk_threshold` (50), `batch_poll_interval_seconds` (30), `batch_max_items_per_request` (1000)
- [x] 1.5 Write config test `test_batch_config_defaults()` using `Settings(**_base_settings())` pattern
- [x] 1.6 Create Alembic migration: `ALTER TYPE background_task_type_enum ADD VALUE` (outside transaction), new columns, FK constraint, GIN index on `source_ids`
- [x] 1.7 Run migration and existing tests — verify no regression

## 2. BatchEmbeddingClient — Gemini SDK Wrapper

- [x] 2.1 Verify `google-genai` SDK batch API surface (spike): check `client.batches.create()` / `client.batches.get()` availability. **Critical:** verify whether SDK supports `custom_id` per request for result correlation AND whether response order matches request order. If neither is available, escalate as blocker. Document findings in code comment.
- [x] 2.2 Write unit tests for `BatchEmbeddingClient`: create batch returns operation name, get_batch_status maps Gemini states to BatchStatus, get_batch_results validates response count matches chunk_ids count
- [x] 2.3 Write unit test for `map_gemini_state()`: all Gemini states → correct BatchStatus
- [x] 2.4 Implement `BatchEmbeddingClient` in `app/services/batch_embedding.py`: `create_embedding_batch()`, `get_batch_status()`, `get_batch_results()` with response count validation and dimension check. Lazy singleton genai.Client, tenacity retry (3 attempts, exponential backoff, 429/5xx)
- [x] 2.5 Run tests — verify pass

## 3. BatchOrchestrator — Submit, Dedup, Apply Results

- [ ] 3.1 Write unit tests for `submit_to_gemini()`: happy path calls Gemini client, dedup skips if batch_operation_name already set, Gemini failure marks BatchJob as FAILED
- [ ] 3.2 Write unit tests for `_apply_results()`: all succeed → chunks INDEXED + Qdrant upsert + Document/DocVersion READY + EmbeddingProfile created + KnowledgeSnapshot.chunk_count updated + BackgroundTask COMPLETE + Source READY; partial failure → succeeded INDEXED, failed PENDING, BatchJob COMPLETE with failed_items metadata; all fail → BatchJob FAILED. Result correlation uses stored chunk_ids from BatchJob.result_metadata (not re-queried from DB)
- [x] 3.3 Implement `BatchOrchestrator` in `app/services/batch_orchestrator.py`: `submit_to_gemini()` (find existing BatchJob by background_task_id, dedup by batch_operation_name, call Gemini, update status), `create_batch_job_for_threshold()` (for auto-threshold path), `poll_and_complete()`, `_apply_results()` with full finalization (shared logic with `_finalize_pipeline_success`)
- [x] 3.4 Run tests — verify pass

## 4. Skip-Embedding Flow — Upload + Worker

- [x] 4.1 Add `skip_embedding: bool = False` parameter to `SourceService.create_source_and_task()`, store in `result_metadata`
- [x] 4.2 Add `skip_embedding: Annotated[bool, Query()] = False` to `upload_source()` in `app/api/admin.py`, pass to service
- [x] 4.3 Add `SkipEmbeddingResult` dataclass to `app/workers/tasks/pipeline.py`
- [x] 4.4 Modify `handle_path_b()`: accept `skip_embedding` param, when True skip embedding+Qdrant and return `SkipEmbeddingResult`
- [x] 4.5 Modify `handle_path_a()`: same skip_embedding support
- [x] 4.6 Modify `_run_ingestion_pipeline()`: read `skip_embedding` from task.result_metadata, pass to handlers, handle `SkipEmbeddingResult` with `_finalize_skip_embedding()` (source→READY, Document/DocVersion→READY, chunks stay PENDING, task→COMPLETE)
- [ ] 4.7 Write unit tests: path_b with skip_embedding returns SkipEmbeddingResult, embedding_service and qdrant_service not called; upload endpoint accepts skip_embedding param
- [x] 4.8 Run tests — verify pass

## 5. Batch-Embed Endpoint + Schemas

- [x] 5.1 Create `BatchEmbedRequest`, `BatchEmbedResponse`, `BatchJobResponse`, `BatchJobListResponse`, `BatchJobDetailResponse` schemas in `app/api/batch_schemas.py`
- [x] 5.2 Add `enqueue_batch_embed()` to `ArqTaskEnqueuer` in `app/api/dependencies.py`, update `TaskEnqueuer` protocol
- [x] 5.3 Implement `POST /api/admin/batch-embed` endpoint: validate sources (exist, READY, have PENDING chunks, same scope, same snapshot_id), source-level dedup (409 if overlap with active batch), create BackgroundTask + BatchJob synchronously (store chunk_ids in BatchJob.result_metadata), enqueue, return 202
- [x] 5.4 Implement `GET /api/admin/batch-jobs` (list with status/operation_type filters, pagination) and `GET /api/admin/batch-jobs/:id` (detail with result_metadata)
- [ ] 5.5 Write unit tests: 202 happy path, 422 nonexistent source, 422 no pending chunks, 422 chunks span multiple snapshots, 422 exceeds batch_max_items_per_request, 409 dedup, GET list/detail
- [x] 5.6 Run tests — verify pass

## 6. Worker Tasks — process_batch_embed + poll_active_batches

- [x] 6.1 Implement `process_batch_embed` in `app/workers/tasks/batch_embed.py`: load BackgroundTask, read source_ids/knowledge_base_id from result_metadata, query PENDING chunks, call `batch_orchestrator.submit_to_gemini()` (BatchJob already exists from API handler), task stays PROCESSING
- [x] 6.2 Implement `poll_active_batches` cron in `app/workers/tasks/batch_poll.py`: query processing BatchJobs, call `batch_orchestrator.poll_and_complete()` for each
- [x] 6.3 Register both tasks + cron in `app/workers/main.py`: add `BatchEmbeddingClient` and `BatchOrchestrator` to worker startup context, register `process_batch_embed` in functions, register `poll_active_batches` as cron (every 30s)
- [ ] 6.4 Write unit tests for process_batch_embed: happy path, no pending chunks → COMPLETE, invalid task_id handled
- [ ] 6.5 Write unit tests for poll_active_batches: no active batches does nothing, completed batch triggers apply
- [x] 6.6 Run tests — verify pass

## 7. Auto-Threshold in Per-Source Ingestion

- [x] 7.1 Add `BatchSubmittedResult` dataclass to `app/workers/tasks/pipeline.py`
- [x] 7.2 Add optional `batch_orchestrator` field to `PipelineServices`
- [x] 7.3 Modify `handle_path_b()`: after chunking, if `not skip_embedding and chunk_count > threshold and batch_orchestrator is not None`, create BatchJob via `create_batch_job_for_threshold()` then submit via `submit_to_gemini()`, return `BatchSubmittedResult`
- [x] 7.4 Modify `_process_task()` in `ingestion.py`: detect `BatchSubmittedResult`, skip finalization, task stays PROCESSING
- [x] 7.5 Wire `batch_orchestrator` in `_load_pipeline_services()` from worker context (`ctx.get("batch_orchestrator")`)
- [ ] 7.6 Write unit tests: chunk_count above threshold returns BatchSubmittedResult, below threshold uses interactive embed
- [x] 7.7 Run tests — verify pass

## 8. Integration Tests

- [ ] 8.1 Write integration test: upload source with skip_embedding=true → source READY, chunks PENDING, no Qdrant entries
- [ ] 8.2 Write integration test: POST /batch-embed with valid source_ids → 202, BackgroundTask and BatchJob created
- [ ] 8.3 Write integration test: POST /batch-embed with active batch for same sources → 409
- [ ] 8.4 Write integration test: poll completes batch → chunks INDEXED, Document/DocVersion READY, EmbeddingProfile created
- [ ] 8.5 Write integration test: GET /batch-jobs returns list, GET /batch-jobs/:id returns detail
- [ ] 8.6 Run full test suite — verify no regressions

## 9. Final Verification

- [ ] 9.1 Run full test suite (`cd backend && python -m pytest tests/ -v`)
- [ ] 9.2 Run linter (`cd backend && ruff check . && ruff format --check .`)
- [ ] 9.3 Re-read `docs/development.md` and self-review against standards
- [ ] 9.4 Verify all installed package versions at or above `docs/spec.md` minimums
- [ ] 9.5 Verify existing ingestion, snapshot, and chat flows are unaffected
