## Story

**S3-06: Gemini Batch API** — Bulk operations: extend existing `batch_jobs` table with Gemini-specific fields, Gemini → internal status mapping, deduplication on retry, polling.

**Verification:** Upload 10+ files → batch job → all processed; retry → batch not duplicated.

**Stable behavior requiring test coverage:** Ingestion pipeline per-source flow (S2-02), snapshot draft linkage (S2-03), chunk status transitions, embedding service contract, worker task lifecycle.

## Why

Individual file ingestion uses the interactive Gemini Embedding 2 API for each chunk. When loading large knowledge bases (books, bulk uploads, reindex), this becomes expensive. The Gemini Batch API offers the same embeddings at 50% lower cost with an SLO of up to 24 hours. S3-06 adds the infrastructure to route bulk embedding operations through the Batch API while keeping individual file uploads on the fast interactive path.

## What Changes

- Extend `batch_jobs` table with Gemini-specific columns: `snapshot_id`, `source_ids`, `background_task_id` (FK), `request_count`, `succeeded_count`, `failed_count`, `result_metadata` (JSONB), `last_polled_at`.
- Add `BATCH_EMBEDDING` value to `BackgroundTaskType` native enum.
- New `BatchEmbeddingClient` service wrapping `google-genai` SDK batch API (create, poll, parse results).
- New `BatchOrchestrator` service managing batch lifecycle: submission, deduplication guard, result application with shared finalization logic.
- New `POST /api/admin/batch-embed` endpoint: accepts `source_ids`, creates `BackgroundTask` + `BatchJob` synchronously, enqueues worker task. Returns both `task_id` and `batch_job_id` in 202 response.
- New `GET /api/admin/batch-jobs` and `GET /api/admin/batch-jobs/:id` endpoints for monitoring.
- Add `skip_embedding` query parameter to `POST /api/admin/sources`: when true, worker parses and chunks but skips embedding and Qdrant upsert. Chunks saved with status `PENDING`.
- New `process_batch_embed` arq worker task: picks up existing `BatchJob`, submits to Gemini.
- New `poll_active_batches` arq cron task (30s interval): polls processing batches, applies results on completion.
- Auto-threshold in per-source ingestion: when chunk_count exceeds configurable threshold (default 50), automatically routes to Batch API instead of interactive.
- New configuration settings: `batch_embed_chunk_threshold`, `batch_poll_interval_seconds`, `batch_max_items_per_request`.

## Capabilities

### New Capabilities

- `batch-embedding`: Gemini Batch API client, batch orchestration lifecycle (submit, dedup, poll, apply), batch-embed Admin API endpoint, batch jobs monitoring endpoints, polling cron task, skip-embedding upload flow, auto-threshold routing.

### Modified Capabilities

- `ingestion-pipeline`: Add `skip_embedding` flag support in upload and worker. Add auto-threshold batch routing for large sources. Add `BatchSubmittedResult` early-return path bypassing interactive finalization.
- `background-tasks`: Add `BATCH_EMBEDDING` value to `BackgroundTaskType` enum. `BATCH_EMBEDDING` tasks have `source_id=NULL` with `source_ids` stored in `result_metadata`.

## Impact

- **New files:** `app/services/batch_embedding.py`, `app/services/batch_orchestrator.py`, `app/api/batch_schemas.py`, `app/workers/tasks/batch_embed.py`, `app/workers/tasks/batch_poll.py`, `tests/unit/services/test_batch_embedding.py`, `tests/unit/services/test_batch_orchestrator.py`, `tests/unit/test_batch_embed_api.py`, `tests/unit/workers/test_skip_embedding.py`, `tests/unit/workers/test_batch_poll.py`, `tests/integration/test_batch_flow.py`
- **Modified files:** `app/db/models/enums.py`, `app/db/models/operations.py`, `app/core/config.py`, `app/api/admin.py`, `app/api/dependencies.py`, `app/services/source.py`, `app/workers/tasks/pipeline.py`, `app/workers/tasks/handlers/path_a.py`, `app/workers/tasks/handlers/path_b.py`, `app/workers/tasks/ingestion.py`, `app/workers/main.py`, `tests/unit/test_task_status.py`
- **Database:** One Alembic migration: `ALTER TYPE` for enum + new columns on `batch_jobs` + FK + GIN index.
- **API:** Three new endpoints (`batch-embed`, `batch-jobs` list, `batch-jobs` detail). One modified endpoint (`sources` with `skip_embedding` param).
- **Dependencies:** No new dependencies — `google-genai >= 1.14.0` already includes batch API support.
