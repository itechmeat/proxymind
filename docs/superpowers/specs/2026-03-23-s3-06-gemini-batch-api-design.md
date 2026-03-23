# S3-06: Gemini Batch API — Design Specification

## Overview

Add Gemini Batch API support to the knowledge circuit for bulk embedding and text extraction operations. This reduces costs by 50% for large-scale ingestion (book uploads, bulk source loading, reindex). The Gemini Batch API processes requests asynchronously with an SLO of up to 24 hours but typically completes much faster.

## Goals

1. **Batch API client** wrapping `google-genai` SDK batch operations
2. **Schema extension** for Gemini-specific batch tracking fields
3. **Status mapping**: Gemini batch states to internal `BatchStatus`
4. **Deduplication guard** preventing duplicate batch creation on worker retry
5. **Two entry points**: explicit bulk endpoint + auto-threshold for large sources

## Non-goals

- New admin UI for batch operations (deferred to S5-03)
- Batch text extraction for Path A multimodal sources (same infrastructure, but wiring deferred — S3-06 focuses on embedding batches first; text extraction batch can reuse the same `BatchEmbeddingClient` when needed)
- Reindex via batch (uses the same infrastructure but triggered differently — reindex story is separate)

## Architecture

### Entry points

```
Entry Point 1: Explicit Bulk Ingest (new)
  POST /api/admin/sources (skip_embedding=true) x N files
  --> each file parsed & chunked independently (existing per-source flow)
  --> chunks saved to PG with status=PENDING (no Qdrant upsert)
  --> source status --> READY (parsed and chunked)
  --> POST /api/admin/batch-embed {source_ids: [...]}
  --> BackgroundTask(BATCH_EMBEDDING) created
  --> worker aggregates PENDING chunks --> Gemini Batch API
  --> cron polls --> results --> upsert to Qdrant --> chunks --> INDEXED

Entry Point 2: Auto-threshold per-source (transparent)
  POST /api/admin/sources (default, skip_embedding=false)
  --> worker parses & chunks
  --> chunk_count > batch_embed_chunk_threshold (default 50)
  --> worker creates BatchJob, submits to Gemini Batch API
  --> source stays PROCESSING until batch completes
  --> cron polls --> results --> upsert to Qdrant --> chunks INDEXED, source READY

Existing flow (unchanged):
  chunk_count <= threshold --> interactive embed_content() as today
```

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
  | PostgreSQL|   | BatchClient    |   | Qdrant  |
  | batch_jobs|   | (Gemini Batch) |   | upsert  |
  | chunks    |   | create / poll  |   |         |
  +-----------+   +----------------+   +---------+
```

### Data flow: bulk ingest

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

## Schema changes

### batch_jobs table extension

New columns added to existing `batch_jobs` table via Alembic migration:

| Column | Type | Nullable | Default | Description |
|--------|------|----------|---------|-------------|
| `snapshot_id` | UUID | YES | — | Snapshot context for this batch |
| `source_ids` | UUID[] (ARRAY) | YES | — | Source IDs included in batch |
| `background_task_id` | UUID FK → background_tasks | YES | — | Link to parent BackgroundTask |
| `request_count` | INTEGER | YES | — | Total items submitted to Gemini |
| `succeeded_count` | INTEGER | YES | — | Items that succeeded |
| `failed_count` | INTEGER | YES | — | Items that failed |
| `result_metadata` | JSONB | YES | — | Detailed results, per-item errors |
| `last_polled_at` | TIMESTAMP | YES | — | Last time status was polled |

Existing columns used as-is:
- `batch_operation_name` — stores Gemini batch operation name/ID
- `operation_type` — `embedding` / `text_extraction`
- `status` — mapped from Gemini states
- `item_count` / `processed_count` — total and completed counts
- `error_message` — batch-level error
- `started_at` / `completed_at` — batch timing
- `agent_id` / `knowledge_base_id` — tenant context

The existing `task_id` (String) field remains for backward compatibility but is superseded by the new `background_task_id` (UUID FK) for proper relational linking.

**Index note:** Consider adding a GIN index on `batch_jobs.source_ids` to optimize the array overlap (`&&`) query used in source-level dedup.

### New enum values

**BackgroundTaskType**: add `BATCH_EMBEDDING`

**Migration note:** `BackgroundTaskType` uses `native_enum=True` in PostgreSQL. Adding a new value to a native enum requires `ALTER TYPE background_task_type_enum ADD VALUE 'BATCH_EMBEDDING'`, which **cannot run inside a transaction** in PostgreSQL. The Alembic migration must use `op.execute()` outside the default transaction context (e.g., separate migration step with `autocommit` or `connection.execution_options(isolation_level="AUTOCOMMIT")`).

No changes to `ChunkStatus` — existing `PENDING` / `INDEXED` / `FAILED` already covers the batch flow:
- `PENDING` = created but not yet embedded (waiting for batch)
- `INDEXED` = embedded and upserted to Qdrant
- `FAILED` = embedding failed

No changes to `BatchOperationType` or `BatchStatus` — existing values are sufficient.

## New services

### BatchEmbeddingClient

**File**: `backend/app/services/batch_embedding.py`

Wraps `google-genai` SDK batch API. Thin client, no business logic.

**Responsibilities:**
- `create_embedding_batch(requests)` — submit batch embedding job to Gemini
- `get_batch_status(batch_name)` — poll batch status
- `get_batch_results(batch_name)` — retrieve completed batch results

**Internal details:**
- Uses same `genai.Client` instance pattern as `EmbeddingService` (lazy singleton, thread-safe)
- Retry on transient errors (429, 5xx) for create/poll — same `tenacity` policy
- Maps SDK response to internal dataclasses (not Gemini SDK types at the boundary)

**Note:** The exact `google-genai` SDK batch API (method names, request format, result parsing) must be verified against SDK v1.14+ documentation during implementation. The design assumes `client.batches.create()` / `client.batches.get()` pattern.

**Risk:** If the `google-genai` SDK does not expose a batch embedding API matching the assumed pattern, the `BatchEmbeddingClient` may need to use the REST API directly or a file-based batch submission via GCS. Implementation should spike the SDK batch API first before building the full orchestration.

### BatchOrchestrator

**File**: `backend/app/services/batch_orchestrator.py`

Orchestrates batch lifecycle. Uses `BatchEmbeddingClient` + DB + Qdrant.

**Responsibilities:**
- `submit_batch(source_ids, agent_id, knowledge_base_id, snapshot_id)` — aggregate chunks, dedup check, create BatchJob, submit to Gemini
- `poll_and_complete(batch_job_id)` — check status, on completion parse results and apply
- `apply_results(batch_job, results)` — upsert embeddings to Qdrant, update chunk statuses

**Dedup guard** (inside `submit_batch`):
```
Step 1: Check for existing in-flight batch:
  SELECT id, batch_operation_name FROM batch_jobs
  WHERE background_task_id = :task_id
    AND status IN ('pending', 'processing')
  If found: return existing batch_job (join polling instead of creating new)

Step 2: Create BatchJob row with status=pending BEFORE calling Gemini API.
  This ensures the dedup guard catches in-flight submissions from concurrent retries.

Step 3: Call Gemini Batch API.

Step 4: Update BatchJob.batch_operation_name with Gemini response.
```

**Result correlation:** chunk_ids are stored in order in `BatchJob.result_metadata` at submission time. Gemini batch requests include `custom_id` set to chunk UUID (if SDK supports it). On result parsing, correlation uses `custom_id` first; if unavailable, falls back to positional matching with a validation check: `len(results) == len(chunk_ids)`. Positional ordering is documented as a constraint that assumes Gemini preserves request order.

**Result application** (inside `apply_results`):
1. Parse batch result — map each result item back to chunk_id via stored chunk_ids list and custom_id/positional matching
2. For succeeded items: upsert vector + payload to Qdrant, set chunk.status = INDEXED
3. For failed items: leave chunk.status = PENDING, log error in result_metadata
4. Update BatchJob: succeeded_count, failed_count, result_metadata
5. If all items succeeded: BatchJob status = COMPLETE
6. If some failed: BatchJob status = COMPLETE (partial failures tracked in metadata)
7. If all failed: BatchJob status = FAILED
8. **Finalize related records** (shared logic with `_finalize_pipeline_success`):
   - `Document` → READY, `DocumentVersion` → READY
   - Create `EmbeddingProfile` record (model, dimensions, task_type, snapshot_id)
   - Update `KnowledgeSnapshot.chunk_count`
   - `BackgroundTask` → COMPLETE (or FAILED if all items failed)
   - Source → READY (for auto-threshold path where source was PROCESSING)

## API changes

### Modified: POST /api/admin/sources

New optional query parameter:

```
skip_embedding: bool = false
```

When `true`:
- File uploaded and saved (existing flow)
- Ingestion task created with `result_metadata.skip_embedding = true`
- Worker parses and chunks but skips embedding and Qdrant upsert
- Chunks saved to PG with `status = PENDING`
- Source set to `READY` (parsed and chunked — admin explicitly manages embedding)
- Task set to `COMPLETE` with `result_metadata.skip_embedding = true`

When `false` (default): existing behavior unchanged.

### New: POST /api/admin/batch-embed

Trigger batch embedding for specified sources.

**Request body:**
```json
{
  "source_ids": ["uuid1", "uuid2", "..."]
}
```

`agent_id` and `knowledge_base_id` are derived from the sources (validated: all sources must belong to the same agent/knowledge_base scope).

**Validation:**
- All source_ids must exist and have status `READY`
- All sources must have at least one chunk with status `PENDING`
- All sources must belong to the same agent_id / knowledge_base_id
- All PENDING chunks for the given source_ids must belong to the same `snapshot_id`. If chunks span multiple snapshots, reject with 400. The `snapshot_id` is derived from the chunks, not from the request body

**Response:** `202 Accepted`
```json
{
  "task_id": "uuid",
  "batch_job_id": "uuid",
  "chunk_count": 342,
  "message": "Batch embedding job created"
}
```

**Flow:**
1. Validate sources and chunks (see Validation above)
2. Create `BackgroundTask` (type=BATCH_EMBEDDING, status=PENDING, **source_id=NULL**, agent_id from sources)
3. Store `source_ids`, `knowledge_base_id`, `snapshot_id` in `BackgroundTask.result_metadata`
4. Create `BatchJob` **synchronously** (status=pending, operation_type=embedding, linked to BackgroundTask). This guarantees `batch_job_id` exists at response time.
5. Store ordered `chunk_ids` list in `BatchJob.result_metadata` as `{"chunk_ids": [...]}` for result correlation.
6. Enqueue `process_batch_embed` arq task
7. Return 202 with both `task_id` and `batch_job_id`

**Note on BackgroundTask.source_id:** For `BATCH_EMBEDDING` tasks, `BackgroundTask.source_id` is `NULL` because batch tasks span multiple sources. The list of source_ids is stored in `BackgroundTask.result_metadata` as `{"source_ids": [...], "knowledge_base_id": "...", "snapshot_id": "..."}`. `knowledge_base_id` is stored in metadata because `BackgroundTask` inherits `TenantMixin` (which provides `agent_id`) but not `KnowledgeScopeMixin`.

**Note on `SourceStatus.READY` for skip_embedding:** When `skip_embedding=true`, source is set to `READY` meaning the source's upload lifecycle is complete (parsed and chunked). This does NOT mean the source is searchable — `PENDING` chunks are never upserted to Qdrant (the embedding + Qdrant upsert step is skipped entirely), so they physically do not exist in the vector index. Qdrant retrieval cannot return them regardless of payload filters. The `ChunkStatus` (PENDING vs INDEXED) tracks this state in PostgreSQL.

### New: GET /api/admin/batch-jobs

List batch jobs with filtering.

**Query params:** `status`, `operation_type`, `limit`, `offset`

**Response:**
```json
{
  "items": [
    {
      "id": "uuid",
      "operation_type": "embedding",
      "status": "processing",
      "item_count": 342,
      "processed_count": 150,
      "succeeded_count": null,
      "failed_count": null,
      "created_at": "...",
      "last_polled_at": "..."
    }
  ],
  "total": 1
}
```

### New: GET /api/admin/batch-jobs/:id

Detailed batch job info.

**Response:** full BatchJob fields including `result_metadata` with per-source breakdown.

## Worker changes

### Modified: process_ingestion

Check `skip_embedding` flag from task context. Two changes to `_run_ingestion_pipeline`:

1. **Skip-embedding path**: after parse+chunk, if `skip_embedding=true`:
   - Do NOT call `embedding_service.embed_texts()` / `embed_file()`
   - Do NOT call `qdrant_service.upsert_chunks()`
   - Set chunks to `PENDING` (already default)
   - Set source to `READY`
   - Finalize task as COMPLETE

2. **Auto-threshold path**: after parse+chunk, if `skip_embedding=false` and `chunk_count > batch_embed_chunk_threshold`:
   - `_run_ingestion_pipeline` returns early with a distinct result type (e.g., `BatchSubmittedResult`) **before** `_finalize_pipeline_success` is called
   - Create `BatchJob` inline via `BatchOrchestrator.create_batch_job_for_threshold()`, then submit to Gemini via `BatchOrchestrator.submit_to_gemini()`
   - Source stays `PROCESSING`, task stays `PROCESSING`
   - The calling code in `_process_task` detects `BatchSubmittedResult` and exits without finalization
   - Cron `poll_active_batches` will complete the lifecycle: apply embeddings, set chunks to INDEXED, source to READY, task to COMPLETE

### New: process_batch_embed

arq task for explicit batch-embed endpoint.

```python
async def process_batch_embed(ctx, task_id: str) -> None:
    # 1. Load BackgroundTask, validate
    # 2. Load source_ids, knowledge_base_id from task.result_metadata
    # 3. Query PENDING chunks for those sources
    # 4. Call BatchOrchestrator.submit_to_gemini() — BatchJob already exists
    #    (created synchronously in the API handler)
    # 5. Task stays PROCESSING (cron completes it)
```

**Note:** `process_batch_embed` does NOT create a `BatchJob`. The `BatchJob` is created synchronously in the `POST /api/admin/batch-embed` handler to guarantee `batch_job_id` is available in the 202 response. The worker only submits the existing `BatchJob` to Gemini via `submit_to_gemini()`.

### New: poll_active_batches (cron)

Registered in arq WorkerSettings as a cron function.

```python
async def poll_active_batches(ctx) -> None:
    # 1. SELECT batch_jobs WHERE status = 'processing'
    # 2. For each: call BatchOrchestrator.poll_and_complete()
    # 3. Log results
```

**Schedule:** every `batch_poll_interval_seconds` (default 30).

**Behavior when no active batches:** single SELECT returns empty → no API calls → negligible cost.

## Status mapping

| Gemini Batch State | Internal BatchStatus | Action |
|-------------------|---------------------|--------|
| PENDING / QUEUED | `processing` | Continue polling |
| RUNNING / ACTIVE | `processing` | Update `last_polled_at` |
| SUCCEEDED | `complete` | Parse results, apply embeddings |
| FAILED | `failed` | Log error, mark task failed |
| EXPIRED | `failed` | Treat as failure, retryable |
| CANCELLED | `cancelled` | Chunks stay PENDING (retryable) |

**Note:** Exact Gemini SDK enum names (e.g., `JOB_STATE_SUCCEEDED` vs `SUCCEEDED`) will be verified against `google-genai` SDK v1.14+ during implementation.

**Enum casing note:** `BatchJob.status` uses lowercase `BatchStatus` values (`pending`, `processing`, `complete`, `failed`, `cancelled`). `BackgroundTask.status` uses uppercase `BackgroundTaskStatus` values (`PENDING`, `PROCESSING`, `COMPLETE`, `FAILED`). Do not confuse the two when updating statuses.

## Deduplication guard

Two levels of dedup:

### 1. Per-task dedup (arq retry safety)

Before creating a Gemini batch in `BatchOrchestrator.submit_batch()`:

```sql
SELECT id, batch_operation_name FROM batch_jobs
WHERE background_task_id = :task_id
  AND status IN ('pending', 'processing')
LIMIT 1
```

If found: skip batch creation, return existing BatchJob for polling.

**Note:** arq is currently configured with `retry_jobs = False`, so automatic retries do not occur. This guard is defensive — it protects against manual re-enqueue of the same task, operational recovery scripts, or future changes to the retry policy.

### 2. Source-level dedup (batch-embed endpoint)

Before accepting a batch-embed request:

```sql
SELECT id FROM batch_jobs
WHERE source_ids && :requested_source_ids  -- array overlap
  AND status IN ('pending', 'processing')
LIMIT 1
```

If found: reject with 409 Conflict ("Active batch already exists for these sources").

## Configuration

New settings in `backend/app/core/config.py`:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `batch_embed_chunk_threshold` | int | 50 | Chunk count above which per-source ingestion auto-switches to Batch API |
| `batch_poll_interval_seconds` | int | 30 | Cron poll interval for active batch jobs |
| `batch_max_items_per_request` | int | 1000 | Max items per single Gemini batch submission (split into multiple batches if exceeded) |

## Error handling

### Batch-level failure

- `BatchJob.status` → `FAILED`, `error_message` set
- All chunks remain `PENDING` (retryable via new `batch-embed` call)
- Linked `BackgroundTask` → `FAILED`
- Linked source: stays `PROCESSING` (auto-threshold) or stays `READY` (bulk — source was already parsed)

### Partial failure (batch succeeds, some items fail)

- `BatchJob.status` → `COMPLETE`
- `succeeded_count` and `failed_count` populated
- `result_metadata` contains per-item error details:
  ```json
  {
    "failed_items": [
      {"chunk_id": "uuid", "error": "INVALID_ARGUMENT: ..."}
    ]
  }
  ```
- Succeeded chunks: `INDEXED` + upserted to Qdrant
- Failed chunks: remain `PENDING` (retryable via new `batch-embed` call for same sources)

### Worker crash during batch processing

- `BatchJob` in PG already has `batch_operation_name` — cron poll will pick it up on restart
- Dedup guard prevents duplicate batch creation if arq retries the task

### Gemini API unavailable

- `BatchEmbeddingClient.create_embedding_batch()` retries with tenacity (3 attempts, exponential backoff)
- If all retries fail: `BatchJob` already exists (created before Gemini call per dedup guard) → set to `FAILED` with error_message. `BackgroundTask` → `FAILED`
- Admin can retry by calling `POST /api/admin/batch-embed` again (creates a new BatchJob)

## Testing strategy

### CI (deterministic, no external dependencies)

**Unit tests:**
- `BatchEmbeddingClient`: mock `google-genai` SDK, test create/poll/result-parse
- `BatchOrchestrator`: mock client + DB, test submit/poll/apply/dedup flows
- Status mapping: all Gemini states → BatchStatus
- Dedup guard: existing batch found → skip creation
- Chunk aggregation: correct chunks selected for given source_ids
- Auto-threshold detection: chunk_count above/below threshold
- `BatchSubmittedResult` early-return path in process_ingestion

**Integration tests:**
- Skip-embedding flow: upload source with `skip_embedding=true` → chunks PENDING, source READY, no Qdrant entries
- Batch-embed endpoint: create sources → batch-embed → verify BatchJob created, BackgroundTask enqueued
- Poll completion: mock Gemini response → verify Qdrant upsert, chunk INDEXED, source READY
- Partial failure: some items fail → succeeded chunks INDEXED, failed chunks PENDING
- Dedup: retry same batch-embed → 409 Conflict
- Existing `test_task_status.py` updated to include `BATCH_EMBEDDING` in expected BackgroundTaskType members

### Quality tests (real Gemini API, separate from CI)

- Smoke test: submit small batch (5 chunks) to real Gemini Batch API, verify embeddings match interactive API output
- Cost verification: compare billing for batch vs interactive for same payload
- Latency observation: measure actual batch completion time vs SLO

## Decisions log

| # | Question | Choice | Rationale |
|---|----------|--------|-----------|
| 1 | Batch trigger strategy | **C: Both threshold-based + bulk endpoint** | Bulk endpoint covers verification ("10+ files -> batch job"). Threshold covers large single sources (books with 1000+ chunks). Both use same BatchClient. Priority: B first (bulk), then A (threshold). |
| 2 | Bulk ingest architecture | **B: Two-step (upload + batch-embed)** | Separation of concerns: upload/parse and batch-embed are independent operations. Flexibility: batch-embed works for fresh uploads, reindex, model changes. Minimal changes to existing upload flow. Isolated partial failure handling. |
| 3 | Skip-embedding mechanism | **A: Explicit skip_embedding flag** | Explicit is better than implicit. Simple boolean, easy to test. No double work (unlike re-embed approach), no race conditions (unlike auto-detect). Bulk UI/script will always set this flag. |
| 4 | Polling architecture | **A: Single arq cron task (30s)** | KISS — one mechanism, easy to debug. ProxyMind is self-hosted single-twin, batch count is always low. Overhead of polling empty list is negligible (one SELECT). Resilient to worker restarts, no orphaned batches possible. |
| 5 | Status mapping | **As documented in architecture.md** | Gemini PENDING/RUNNING -> processing, SUCCEEDED -> complete, FAILED/EXPIRED -> failed, CANCELLED -> cancelled. Exact SDK enum names verified during implementation. |
| 6 | Dedup guard | **Check batch_operation_name per background_task_id** | Prevents duplicate Gemini batches on arq retry. Already documented in architecture.md. Extended with source-level overlap check for batch-embed endpoint. |
| 7 | Batch client architecture | **Separate BatchEmbeddingClient service** | SRP: don't branch in EmbeddingService. Batch has fundamentally different lifecycle (async, polling, result parsing). Batch client is a thin wrapper; orchestration lives in BatchOrchestrator. |
| 8 | Batch operation scope | **Embeddings first, text extraction ready** | S3-06 focuses on embedding batches (primary cost driver). Text extraction batch uses same infrastructure but wiring deferred. BatchEmbeddingClient is generic enough to support both. |
| 9 | Partial failure handling | **COMPLETE + per-item tracking** | BatchJob -> COMPLETE. Failed items tracked in result_metadata JSONB. Failed chunks remain PENDING — retryable via new batch-embed call. No new BatchStatus enum needed. |
| 10 | Source status for skip_embedding | **READY (parsed and chunked)** | Source is fully processed from upload perspective. Embedding status tracked per-chunk (PENDING/INDEXED). Admin explicitly manages batch embedding as a separate step. Avoids introducing new SourceStatus enum. |
