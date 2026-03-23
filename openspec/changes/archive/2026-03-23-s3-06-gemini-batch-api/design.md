# S3-06: Gemini Batch API — Design

## Story

> Bulk operations: extend existing `batch_jobs` table with Gemini-specific fields, Gemini -> internal status mapping, deduplication on retry, polling.

**Outcome:** bulk uploads are processed cheaper and in parallel.

**Verification:** Upload 10+ files -> batch job -> all processed; retry -> batch not duplicated.

## Context

The interactive Gemini Embedding 2 API (used since S2-02) processes chunks one-at-a-time per source. For large knowledge bases — books with 1000+ chunks, bulk uploads of 10+ files, or full reindex — this is expensive. The Gemini Batch API offers identical embeddings at 50% lower cost with an SLO of up to 24 hours (typically much faster).

S3-06 adds the infrastructure to route bulk embedding operations through the Batch API while keeping individual file uploads on the fast interactive path. The change is entirely within the knowledge circuit and operational circuit; the dialogue circuit is unchanged.

**Current state:**
- `batch_jobs` table exists (S1-02) with base columns: `batch_operation_name`, `operation_type`, `status`, `item_count`, `processed_count`, `error_message`, `started_at`, `completed_at`, tenant fields.
- `BackgroundTaskType` enum has only `INGESTION` (native PG enum). Note: `TEXT_EXTRACTION` exists in `BatchOperationType`, not `BackgroundTaskType`.
- `ChunkStatus` already has `PENDING`, `INDEXED`, `FAILED` — sufficient for batch flow.
- `BatchStatus` and `BatchOperationType` enums already exist.
- `google-genai >= 1.14.0` is already a dependency and includes batch API support.

## Goals / Non-Goals

### Goals

- `BatchEmbeddingClient` wrapping `google-genai` SDK batch operations (create, poll, parse results).
- Schema extension: new columns on `batch_jobs` for Gemini-specific batch tracking (`snapshot_id`, `source_ids`, `background_task_id` FK, counters, `result_metadata` JSONB, `last_polled_at`).
- Status mapping: Gemini batch states to internal `BatchStatus`.
- Deduplication guard: prevent duplicate batch creation on worker retry (per-task) and on repeated `batch-embed` calls (per-source overlap).
- Two entry points: explicit bulk endpoint (`POST /api/admin/batch-embed`) and auto-threshold for large single sources.
- `skip_embedding` query parameter on `POST /api/admin/sources` for two-step bulk ingest.
- Batch monitoring endpoints (`GET /api/admin/batch-jobs`, `GET /api/admin/batch-jobs/:id`).
- Cron-based polling of active batches via arq (30s default interval).

### Non-Goals

- **Admin UI for batch operations** — deferred to S5-03.
- **Batch text extraction** for Path A multimodal sources — same infrastructure, but wiring deferred. S3-06 focuses on embedding batches.
- **Reindex via batch** — uses the same infrastructure but triggered differently; separate story.
- **Webhook/push notification from Gemini** — polling is simpler and sufficient for single-twin self-hosted.

## Decisions

### D1: Both threshold-based and bulk endpoint (hybrid trigger strategy)

Provide two entry points that share the same `BatchEmbeddingClient` and `BatchOrchestrator`:
- **Bulk endpoint** (`POST /api/admin/batch-embed`): covers the verification scenario ("upload 10+ files, then batch embed"). Admin explicitly controls when to batch.
- **Auto-threshold** (per-source): when `chunk_count > batch_embed_chunk_threshold` (default 50) during normal ingestion, automatically routes to Batch API instead of interactive.

**Rejected:** Threshold-only (no explicit control for admins). Bulk-only (misses large single sources like books). Separate services for each path (unnecessary duplication — both use the same batch client).

### D2: Two-step bulk ingest (upload + batch-embed)

Bulk ingest is a two-step process: (1) upload sources with `skip_embedding=true` — each file is parsed and chunked independently via the existing per-source flow, (2) call `POST /api/admin/batch-embed` with collected `source_ids` to trigger batch embedding.

**Rationale:** Separation of concerns — upload/parse and batch-embed are independent operations. The `batch-embed` endpoint works for fresh uploads, reindex, and model changes. Minimizes changes to the existing upload flow. Partial failure in upload does not block embedding of successfully parsed sources.

**Rejected:** Single "bulk upload" endpoint (couples upload and embedding, complex error handling). Automatic batch detection on upload count (implicit, hard to test, race conditions between concurrent uploads).

### D3: Explicit skip_embedding flag

A `skip_embedding: bool = false` query parameter on `POST /api/admin/sources`. When `true`, the worker parses and chunks but skips embedding and Qdrant upsert. Chunks are saved with `status = PENDING`. Source is set to `READY` (parsed and chunked — admin explicitly manages embedding).

**Rationale:** Explicit is better than implicit. Simple boolean, easy to test. No double work (unlike a "re-embed" approach), no race conditions (unlike auto-detect).

### D4: Single arq cron task for polling (30s interval)

One `poll_active_batches` cron job registered in arq WorkerSettings. Polls all `BatchJob` rows with `status = 'processing'`. When no active batches exist, a single `SELECT` returns empty — negligible cost.

**Rationale:** KISS. ProxyMind is self-hosted single-twin; batch count is always low. One mechanism, easy to debug. Resilient to worker restarts — no orphaned batches possible because state lives in PostgreSQL, not in-memory.

**Rejected:** Per-batch scheduled task (complex cleanup on cancellation). Webhook-based (Gemini Batch API does not offer push; would require GCS notification setup — overkill).

### D5: Separate BatchEmbeddingClient service

A new `BatchEmbeddingClient` (`app/services/batch_embedding.py`) wraps the `google-genai` SDK batch API. It is a thin client with no business logic — just create, poll, and parse results. A separate `BatchOrchestrator` (`app/services/batch_orchestrator.py`) manages the batch lifecycle: submission, dedup guard, result application.

**Rationale:** SRP — don't branch in `EmbeddingService`. Batch has a fundamentally different lifecycle (async, polling, result parsing). The client is thin; orchestration logic is in the orchestrator.

**Rejected:** Extending `EmbeddingService` with batch methods (violates SRP, makes the interactive path harder to reason about).

### D6: Dedup guard — two levels

**Per-task dedup** (arq retry safety): Before creating a Gemini batch, check `batch_jobs WHERE background_task_id = :task_id AND status IN ('pending', 'processing')`. If found, join polling instead of creating a new batch. Defensive — arq currently has `retry_jobs = False`, but protects against manual re-enqueue and future policy changes.

**Source-level dedup** (batch-embed endpoint): Before accepting a request, check `batch_jobs WHERE source_ids && :requested_source_ids AND status IN ('pending', 'processing')`. If found, reject with 409 Conflict.

### D7: Status mapping — Gemini to internal

| Gemini Batch State | Internal BatchStatus | Action |
|-------------------|---------------------|--------|
| PENDING / QUEUED | `processing` | Continue polling |
| RUNNING / ACTIVE | `processing` | Update `last_polled_at` |
| SUCCEEDED | `complete` | Parse results, apply embeddings |
| FAILED | `failed` | Log error, mark task FAILED |
| EXPIRED | `failed` | Treat as failure, retryable |
| CANCELLED | `cancelled` | Chunks stay PENDING (retryable) |

Exact SDK enum names (e.g., `JOB_STATE_SUCCEEDED` vs `SUCCEEDED`) to be verified against `google-genai` SDK v1.14+ during implementation.

### D8: Partial failure handling — COMPLETE with per-item tracking

When a batch succeeds but some items fail: `BatchJob.status` -> `COMPLETE`, with `succeeded_count` and `failed_count` populated. Failed items tracked in `result_metadata` JSONB. Succeeded chunks -> `INDEXED` + upserted to Qdrant. Failed chunks remain `PENDING` — retryable via a new `batch-embed` call.

**Rationale:** No new `BatchStatus` enum needed. The batch itself succeeded; partial failures are tracked at item granularity.

### D9: Source status READY for skip_embedding

When `skip_embedding=true`, source is set to `READY` meaning the source's upload lifecycle is complete (parsed and chunked). This does NOT mean the source is searchable — `PENDING` chunks have no vectors in Qdrant. The `ChunkStatus` (PENDING vs INDEXED) tracks embedding state in PostgreSQL.

**Rationale:** Avoids introducing a new `SourceStatus` enum value. `READY` is semantically correct from the upload perspective. Embedding status is a chunk-level concern.

### D10: Result correlation — custom_id with positional fallback

Chunk UUIDs are stored in order in `BatchJob.result_metadata` at submission time. Gemini batch requests include `custom_id` set to chunk UUID (if SDK supports it). On result parsing, correlation uses `custom_id` first; if unavailable, falls back to positional matching with a validation check: `len(results) == len(chunk_ids)`.

## Architecture

### Component diagram

```
+------------------------------------------------------------+
| Admin API                                                   |
|  POST /api/admin/sources?skip_embedding=true                |
|  POST /api/admin/batch-embed                                |
|  GET  /api/admin/batch-jobs                                 |
|  GET  /api/admin/batch-jobs/:id                             |
+----------------------------+-------------------------------+
                             | enqueue
                             v
+------------------------------------------------------------+
| arq Worker                                                  |
|  process_ingestion     (modified: skip_embedding support)   |
|  process_batch_embed   (new: bulk embed task)               |
|  poll_active_batches   (new: cron, 30s interval)            |
+--------+-----------------+----------------+----------------+
         |                 |                |
         v                 v                v
  +-----------+   +----------------+   +---------+
  | PostgreSQL|   | BatchEmbedding |   | Qdrant  |
  | batch_jobs|   | Client         |   | upsert  |
  | chunks    |   | (Gemini Batch) |   |         |
  +-----------+   +----------------+   +---------+
```

### Data flow: explicit bulk ingest (Entry Point 1)

```
Admin                     API              Worker           Gemini         Qdrant
  |                        |                 |                |              |
  |-- upload source x10 -->|                 |                |              |
  |   (skip_embedding)     |-- enqueue x10 ->|                |              |
  |                        |                 |-- parse/chunk->|              |
  |                        |                 |  (no embed)    |              |
  |                        |                 |                |              |
  |-- POST batch-embed --->|                 |                |              |
  |   {source_ids}         |-- enqueue ----->|                |              |
  |                        |                 |-- create batch>|              |
  |                        |                 |  (embedding)   |              |
  |                        |                 |                |              |
  |                        |       [cron: poll_active_batches]|              |
  |                        |                 |-- get status ->|              |
  |                        |                 |<- SUCCEEDED ---|              |
  |                        |                 |-- parse results|              |
  |                        |                 |-- upsert ------|------------->|
  |                        |                 |-- chunks INDEXED              |
```

### Data flow: auto-threshold (Entry Point 2)

```
Admin                     API              Worker           Gemini         Qdrant
  |                        |                 |                |              |
  |-- upload large source->|                 |                |              |
  |   (skip_embedding=no)  |-- enqueue ----->|                |              |
  |                        |                 |-- parse/chunk  |              |
  |                        |                 |-- chunk_count > threshold     |
  |                        |                 |-- create BatchJob + submit -->|
  |                        |                 |  source stays PROCESSING      |
  |                        |                 |                |              |
  |                        |       [cron: poll_active_batches]|              |
  |                        |                 |-- get status ->|              |
  |                        |                 |<- SUCCEEDED ---|              |
  |                        |                 |-- upsert ------|------------->|
  |                        |                 |-- finalize: chunks INDEXED,   |
  |                        |                 |   source READY, task COMPLETE |
```

### New and modified components

| Component | Location | Responsibility |
|-----------|----------|---------------|
| **BatchEmbeddingClient** | `app/services/batch_embedding.py` | Thin wrapper around `google-genai` SDK batch API: create, poll, parse results |
| **BatchOrchestrator** | `app/services/batch_orchestrator.py` | Batch lifecycle: submit (with dedup), poll_and_complete, apply_results, finalization |
| **batch-embed endpoint** | `app/api/admin.py` | `POST /api/admin/batch-embed` — validate sources, create BackgroundTask + BatchJob, enqueue worker |
| **batch-jobs endpoints** | `app/api/admin.py` | `GET /api/admin/batch-jobs` (list), `GET /api/admin/batch-jobs/:id` (detail) |
| **batch schemas** | `app/api/batch_schemas.py` | Request/response Pydantic models for batch endpoints |
| **process_batch_embed** | `app/workers/tasks/batch_embed.py` | arq task: load existing BatchJob, submit to Gemini |
| **poll_active_batches** | `app/workers/tasks/batch_poll.py` | arq cron: poll processing batches, apply results on completion |
| **process_ingestion** (modified) | `app/workers/tasks/pipeline.py` + handlers | `skip_embedding` support, auto-threshold batch routing |
| **config** (modified) | `app/core/config.py` | Three new settings: `batch_embed_chunk_threshold`, `batch_poll_interval_seconds`, `batch_max_items_per_request` |
| **enums** (modified) | `app/db/models/enums.py` | Add `BATCH_EMBEDDING` to `BackgroundTaskType` |
| **batch_jobs model** (modified) | `app/db/models/operations.py` | New columns: `snapshot_id`, `source_ids`, `background_task_id` FK, counters, `result_metadata`, `last_polled_at` |

### Circuits affected

- **Knowledge circuit:** Modified — new batch embedding path alongside existing interactive path. Ingestion worker gains `skip_embedding` support and auto-threshold routing.
- **Operational circuit:** Modified — new arq cron task (`poll_active_batches`), new arq task (`process_batch_embed`), new `BackgroundTaskType` enum value.
- **Dialogue circuit:** Unchanged.

## Schema changes

### batch_jobs table — new columns (Alembic migration)

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `snapshot_id` | UUID | YES | -- | Snapshot context for this batch |
| `source_ids` | UUID[] (ARRAY) | YES | -- | Source IDs included in batch |
| `background_task_id` | UUID FK -> background_tasks | YES | -- | Link to parent BackgroundTask |
| `request_count` | INTEGER | YES | -- | Total items submitted to Gemini |
| `succeeded_count` | INTEGER | YES | -- | Items that succeeded |
| `failed_count` | INTEGER | YES | -- | Items that failed |
| `result_metadata` | JSONB | YES | -- | Detailed results, per-item errors |
| `last_polled_at` | TIMESTAMP | YES | -- | Last time status was polled |

**Index:** GIN index on `batch_jobs.source_ids` for array overlap (`&&`) queries used in source-level dedup.

### Enum changes

**BackgroundTaskType:** Add `BATCH_EMBEDDING`.

**Migration note:** `BackgroundTaskType` uses `native_enum=True` in PostgreSQL. Adding a value requires `ALTER TYPE ... ADD VALUE`, which cannot run inside a transaction. The Alembic migration must use `op.execute()` with `AUTOCOMMIT` isolation level.

**No changes** to `ChunkStatus`, `BatchOperationType`, or `BatchStatus` — existing values are sufficient.

## API changes

### Modified: POST /api/admin/sources

New optional query parameter: `skip_embedding: bool = false`.

When `true`: file is uploaded, parsed, and chunked (existing flow), but embedding and Qdrant upsert are skipped. Chunks saved with `status = PENDING`. Source set to `READY`. Task set to `COMPLETE` with `result_metadata.skip_embedding = true`.

When `false` (default): existing behavior unchanged, unless chunk_count exceeds auto-threshold.

### New: POST /api/admin/batch-embed

Trigger batch embedding for specified sources. Returns `202 Accepted`.

**Request body:** `{ "source_ids": ["uuid1", "uuid2", ...] }`

**Validation:**
- All source_ids must exist with status `READY`
- All sources must have at least one chunk with status `PENDING`
- All sources must belong to the same `agent_id` / `knowledge_base_id`
- All PENDING chunks must belong to the same `snapshot_id` (derived from chunks, not request body)

**Response:** `{ "task_id": "uuid", "batch_job_id": "uuid", "chunk_count": 342, "message": "Batch embedding job created" }`

**Flow:** Validate -> create `BackgroundTask` (type=BATCH_EMBEDDING, source_id=NULL, agent_id from sources) -> store source_ids/knowledge_base_id/snapshot_id in `BackgroundTask.result_metadata` -> create `BatchJob` synchronously (guarantees batch_job_id at response time) -> store ordered chunk_ids in `BatchJob.result_metadata` -> enqueue `process_batch_embed` -> return 202.

### New: GET /api/admin/batch-jobs

List batch jobs. Query params: `status`, `operation_type`, `limit`, `offset`. Standard paginated response.

### New: GET /api/admin/batch-jobs/:id

Detailed batch job info including `result_metadata` with per-source breakdown.

## Worker changes

### Modified: process_ingestion

Two new paths in `_run_ingestion_pipeline`:

1. **Skip-embedding path:** If `skip_embedding=true` in task context, after parse+chunk: skip `embed_texts()` and `qdrant_service.upsert_chunks()`. Chunks stay `PENDING`. Source -> `READY`. Task -> `COMPLETE`.

2. **Auto-threshold path:** If `skip_embedding=false` and `chunk_count > batch_embed_chunk_threshold`, return a `BatchSubmittedResult` before `_finalize_pipeline_success` is called. Create `BatchJob` inline via `BatchOrchestrator`, submit to Gemini. Source stays `PROCESSING`, task stays `PROCESSING`. The calling code in `_process_task` detects `BatchSubmittedResult` and exits without finalization. Cron `poll_active_batches` completes the lifecycle.

### New: process_batch_embed

arq task for the explicit batch-embed endpoint. Loads `BackgroundTask`, retrieves source_ids from metadata, queries PENDING chunks, calls `BatchOrchestrator.submit_to_gemini()` on the pre-created `BatchJob`. Task stays `PROCESSING` (cron completes it).

### New: poll_active_batches (cron)

Registered in arq WorkerSettings. Runs every `batch_poll_interval_seconds` (default 30). Selects all `batch_jobs WHERE status = 'processing'`. For each, calls `BatchOrchestrator.poll_and_complete()`. On completion: parse results, upsert to Qdrant, update chunk statuses, finalize related records (Document -> READY, EmbeddingProfile, snapshot chunk_count, BackgroundTask -> COMPLETE, Source -> READY).

## Configuration

New settings in `app/core/config.py`:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `batch_embed_chunk_threshold` | int | 50 | Chunk count above which per-source ingestion auto-switches to Batch API |
| `batch_poll_interval_seconds` | int | 30 | Cron poll interval for active batch jobs |
| `batch_max_items_per_request` | int | 1000 | Max items per single Gemini batch submission (split if exceeded) |

## Error handling

### Batch-level failure
- `BatchJob.status` -> `FAILED`, `error_message` set
- All chunks remain `PENDING` (retryable via new `batch-embed` call)
- Linked `BackgroundTask` -> `FAILED`
- Source: stays `PROCESSING` (auto-threshold) or stays `READY` (bulk path)

### Partial failure
- `BatchJob.status` -> `COMPLETE`
- `succeeded_count` / `failed_count` populated
- `result_metadata` contains per-item error details
- Succeeded chunks: `INDEXED` + upserted to Qdrant
- Failed chunks: remain `PENDING` (retryable)

### Worker crash during batch processing
- `BatchJob` in PG already has `batch_operation_name` — cron poll picks it up on restart
- Dedup guard prevents duplicate batch creation if task is re-enqueued

### Gemini API unavailable
- `BatchEmbeddingClient` retries with tenacity (3 attempts, exponential backoff)
- If all retries fail: `BatchJob` (already created before Gemini call) -> `FAILED`, `BackgroundTask` -> `FAILED`
- Admin can retry via new `POST /api/admin/batch-embed` call (creates a new BatchJob)

## Risks / Trade-offs

### SDK batch API surface uncertainty
The exact `google-genai` SDK batch API (method names, request format, result parsing) must be verified against SDK v1.14+ during implementation. If the SDK does not expose a batch embedding API matching the assumed `client.batches.create()` / `client.batches.get()` pattern, the `BatchEmbeddingClient` may need to use the REST API directly or file-based batch submission via GCS. **Mitigation:** Spike the SDK batch API first before building the full orchestration.

### Positional result correlation fragility
If Gemini does not support `custom_id` in batch requests, result correlation relies on positional matching, which assumes Gemini preserves request order. **Mitigation:** Validate `len(results) == len(chunk_ids)` before applying. Fall back to failing the batch if length mismatch detected.

### Enum casing mismatch between BatchJob and BackgroundTask
`BatchJob.status` uses lowercase `BatchStatus` values (`pending`, `processing`, `complete`). `BackgroundTask.status` uses uppercase `BackgroundTaskStatus` values (`PENDING`, `PROCESSING`, `COMPLETE`). **Mitigation:** Explicit mapping in `BatchOrchestrator` — never pass one enum type where the other is expected.

### Auto-threshold changes ingestion behavior transparently
Sources with chunk counts above the threshold will silently switch to batch processing, changing latency from seconds to potentially hours. **Mitigation:** Configurable threshold (default 50). Logged clearly. Source stays `PROCESSING` until batch completes, so status is observable.

## Testing strategy

### CI tests (deterministic, no external dependencies)

**Unit tests:**
- `BatchEmbeddingClient`: mock `google-genai` SDK, test create/poll/result-parse
- `BatchOrchestrator`: mock client + DB, test submit/poll/apply/dedup flows
- Status mapping: all Gemini states -> BatchStatus
- Dedup guard: existing batch found -> skip creation
- Chunk aggregation: correct chunks selected for given source_ids
- Auto-threshold detection: chunk_count above/below threshold
- `BatchSubmittedResult` early-return path in process_ingestion

**Integration tests:**
- Skip-embedding flow: upload with `skip_embedding=true` -> chunks PENDING, source READY, no Qdrant entries
- Batch-embed endpoint: create sources -> batch-embed -> verify BatchJob created, BackgroundTask enqueued
- Poll completion: mock Gemini response -> verify Qdrant upsert, chunk INDEXED, source READY
- Partial failure: some items fail -> succeeded chunks INDEXED, failed chunks PENDING
- Dedup: retry same batch-embed -> 409 Conflict
- Existing `test_task_status.py` updated to include `BATCH_EMBEDDING` in expected members

### Quality tests (real Gemini API, separate from CI)
- Smoke: submit small batch (5 chunks) to real Gemini Batch API, verify embeddings match interactive API output
- Latency observation: measure actual batch completion time

## Files changed

| File | Change |
|------|--------|
| `backend/app/services/batch_embedding.py` | **New** — Gemini Batch API client |
| `backend/app/services/batch_orchestrator.py` | **New** — batch lifecycle orchestration |
| `backend/app/api/batch_schemas.py` | **New** — Pydantic request/response models |
| `backend/app/workers/tasks/batch_embed.py` | **New** — arq task for explicit batch-embed |
| `backend/app/workers/tasks/batch_poll.py` | **New** — arq cron for polling active batches |
| `backend/app/db/models/enums.py` | Add `BATCH_EMBEDDING` to `BackgroundTaskType` |
| `backend/app/db/models/operations.py` | New columns on `batch_jobs` table |
| `backend/app/core/config.py` | Three new batch settings |
| `backend/app/api/admin.py` | Three new endpoints (batch-embed, batch-jobs list, batch-jobs detail) |
| `backend/app/api/dependencies.py` | Wire new service dependencies |
| `backend/app/services/source.py` | Pass `skip_embedding` through to worker |
| `backend/app/workers/tasks/pipeline.py` | Skip-embedding path + auto-threshold routing |
| `backend/app/workers/tasks/handlers/path_a.py` | Skip-embedding support |
| `backend/app/workers/tasks/handlers/path_b.py` | Skip-embedding support + auto-threshold |
| `backend/app/workers/tasks/ingestion.py` | Handle `BatchSubmittedResult` return type |
| `backend/app/workers/main.py` | Register `process_batch_embed` + `poll_active_batches` cron |
| `backend/alembic/versions/xxx_add_batch_embedding.py` | **New** — migration for enum + columns + FK + GIN index |
| `backend/tests/unit/services/test_batch_embedding.py` | **New** — BatchEmbeddingClient unit tests |
| `backend/tests/unit/services/test_batch_orchestrator.py` | **New** — BatchOrchestrator unit tests |
| `backend/tests/unit/test_batch_embed_api.py` | **New** — batch-embed endpoint unit tests |
| `backend/tests/unit/workers/test_skip_embedding.py` | **New** — skip-embedding path tests |
| `backend/tests/unit/workers/test_batch_poll.py` | **New** — poll cron tests |
| `backend/tests/integration/test_batch_flow.py` | **New** — end-to-end batch flow integration tests |
| `backend/tests/unit/test_task_status.py` | Update expected `BackgroundTaskType` members |

**Not affected:** Chat API, retrieval service, citation builder, persona loader, frontend.
