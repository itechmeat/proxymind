# S2-01: Upload Source — Design Spec

## Overview

S2-01 is the first story of Phase 2 (First E2E Slice) and the first endpoint in the Knowledge Circuit. It accepts a Markdown or TXT file with metadata, persists the file in MinIO, records metadata in PostgreSQL, and enqueues a background task via arq. A noop worker picks up the task and transitions source/task through their status lifecycles. Real parsing and chunking are deferred to S2-02.

### Scope

**In scope:**

- `POST /api/admin/sources` — file upload with metadata
- `GET /api/admin/tasks/{id}` — task status polling
- MinIO client service (upload, delete, key generation)
- arq worker setup (entrypoint, task registration, noop ingestion handler)
- New migration: `background_tasks` table in PostgreSQL
- Auto-creation of `sources` bucket at application startup

**Out of scope:**

- Parsing, chunking, embedding (S2-02)
- Formats beyond Markdown/TXT (S3-01)
- Admin API authentication (S7-01)
- Source listing and deletion endpoints (future stories)

### Verification criteria (from plan.md)

`curl -F file=@doc.md /api/admin/sources` -> 202 + task_id; file in MinIO; record in PG.

---

## Decision Log

### D1: MinIO Python client — `minio` official SDK

**Options considered:**

- **A. `minio` (official SDK)** — lightweight (~2 MB), simple API (`put_object`, `get_object`), direct MinIO feature compatibility. The SDK is synchronous (uses `urllib3` internally); async usage via `asyncio.to_thread()` wrapper.
- **B. `boto3` (AWS SDK)** — S3-standard, ~100 MB, synchronous by default (needs `aioboto3`), overkill for self-hosted.
- **C. `miniopy-async` (community fork)** — fully async but less maintained, may lag behind official SDK.

**Decision: A.** Lightweight, well-maintained, sufficient for self-hosted. Synchronous calls wrapped in `asyncio.to_thread()` for non-blocking usage in FastAPI and arq handlers. If migration to AWS S3 is ever needed, a thin wrapper abstracts the difference (Dependency Inversion per development.md).

### D2: Task storage — separate `background_tasks` table in PostgreSQL

**Options considered:**

- **A. New `background_tasks` table in PostgreSQL** — clean entity, full history, queryable, filterable, extensible.
- **B. Reuse existing `batch_jobs` table** — similar fields but semantically designed for Gemini Batch API. Overloading violates SRP.
- **C. Redis-only (arq result)** — ephemeral, no queryable history, lost on restart, no audit trail.

**Decision: A.** Clean entity that will be reused across S2-02, S3-06, and beyond. `batch_jobs` remains for Gemini Batch API as designed. arq is used as transport (enqueue/execute); PostgreSQL is the source of truth for status.

### D3: File format scope — Markdown + TXT only

**Options considered:**

- **A. Markdown + TXT only** — strict per plan, minimal edge cases, YAGNI.
- **B. Accept all formats, process only MD/TXT** — allows pre-uploading PDF, but confusing UX when nothing happens.
- **C. All text formats (MD, TXT, PDF, DOCX, HTML)** — exceeds S2-01 scope, invades S3-01.

**Decision: A.** Strict per plan. Endpoint rejects unsupported formats with 422 and a list of supported types. Extending to new formats in S3-01 is a one-line whitelist change.

### D4: Worker behavior — noop with full status lifecycle

**Options considered:**

- **A. Stub with `NotImplementedError`** — worker picks up task, immediately fails. Task always in `failed` state.
- **B. Noop with full status lifecycle** — worker transitions task/source through PENDING -> PROCESSING -> COMPLETE/READY. No real processing but full lifecycle works end-to-end.
- **C. Minimal processing (create Document + DocumentVersion)** — partial S2-02 work, intermediate state without chunks.

**Decision: B.** Full lifecycle demonstrates working value. Verification is end-to-end: upload -> MinIO -> PG -> enqueue -> worker -> status complete -> GET /tasks/:id -> complete. S2-02 replaces the noop body with the real pipeline. All planned shortcomings have TODO references per development.md stub policy. User requested explicit TODOs with plan references for any deferred work.

### D5: Upload format — multipart/form-data with file + JSON metadata

**Options considered:**

- **A. Multipart: file + JSON metadata field** — one request, Pydantic validates JSON from string field, compatible with curl verification.
- **B. Multipart: file + flat form fields** — simpler for curl but poor FastAPI validation for nested structures, grows with new fields.
- **C. Two requests (metadata first, then presigned upload)** — elegant for large files but two steps, complex client, presigned URL management.

**Decision: A.** Single request, standard pattern, Pydantic validation, compatible with plan verification. Presigned URL can be added as an alternative endpoint for large files in the future.

### D6: Admin API auth — deferred to S7-01

**Options considered:**

- **A. No auth, TODO for S7-01** — YAGNI, project runs locally in Docker on Phase 2, simpler testing.
- **B. Simple Bearer token from .env** — secure by default, but complicates curl verification and tests.
- **C. Optional auth (check if key set)** — fail-open, violates secure defaults from development.md.

**Decision: A.** Phase 2 runs locally. Auth middleware is added as a single layer in S7-01 without touching business logic. Caddy should not expose `/api/admin/*` externally without explicit configuration.

**Security exception:** This decision is an explicit deviation from development.md principles 10-11 (secure by default). Acceptance criteria: S2-01 Admin API is for **local Docker development only**, not for exposed deployments. The TODO(S7-01) MUST be resolved before any non-local deployment. This exception is documented here as an architectural decision, not an oversight.

### D7: Bucket strategy — single `sources` bucket

**Options considered:**

- **A. One bucket `sources`, key = `{agent_id}/{source_id}/{filename}`** — single config point, tenant-ready key structure, standard S3 pattern.
- **B. Multiple buckets by purpose** — better isolation but only one file type on Phase 2; YAGNI.
- **C. One bucket `proxymind` with prefix routing** — simpler but worse isolation in the future.

**Decision: A.** One bucket for source files. Key path includes `agent_id` and `source_id` for tenant-ready organization. Additional buckets for pipeline artifacts decided in S2-02/S3-06.

### D8: Bucket creation — at application startup (lifespan)

**Options considered:**

- **A. At startup in lifespan** — predictable, idempotent, same pattern as Alembic migrations and Redis init.
- **B. Lazy on first upload** — first upload slower, race condition risk, error masking.
- **C. Init container in docker-compose** — separate service for one command, overcomplicates compose.

**Decision: A.** Two lines in lifespan (`bucket_exists()` + `make_bucket()`). One pattern for all infrastructure initialization.

### D9: Tasks table schema — extended with operational fields

**Options considered:**

- **A. Minimal (10 fields)** — enough for S2-01, extend later via migrations.
- **B. Extended with `arq_job_id`, `progress`, `result_metadata`** — each field justified by upcoming stories (S2-02 progress, S5-03 Admin UI, operational debugging).
- **C. Full generic task system** — Celery-style args/kwargs, retry tracking; duplicates arq's job management.

**Decision: B.** Slightly beyond minimum, but every field is justified by stories within the next 2-3 sprints. `arq_job_id` for operational transparency, `progress` for UX in S5-03, `result_metadata` (JSONB) for extensibility without migrations.

### D10: Testing strategy — unit + integration with PG testcontainer

**Options considered:**

- **A. Unit tests + integration with PG testcontainer, mocked MinIO/arq** — balanced coverage, fast CI, migration verification.
- **B. Full integration with MinIO + Redis testcontainers** — more reliable but significantly slower CI, overkill for noop worker.
- **C. Unit tests only** — fast but misses migration verification and endpoint flow.

**Decision: A.** Unit tests for pure logic, integration with PG testcontainer for migration and CRUD, mocked MinIO/arq for endpoint flow. Real MinIO/Redis integration tests deferred to S2-02 when the pipeline becomes meaningful.

---

## Architecture

### Data Flow

```text
Client                    FastAPI                 MinIO           PostgreSQL         Redis/arq
  |                         |                      |                 |                 |
  |-- POST /api/admin/sources (multipart: file + metadata JSON)      |                 |
  |                         |                      |                 |                 |
  |                         |-- validate metadata + file             |                 |
  |                         |                      |                 |                 |
  |                         |-- upload file ------->|                 |                 |
  |                         |  key: {agent_id}/{source_id}/{name}    |                 |
  |                         |                      |                 |                 |
  |                         |-- create Source (PENDING) ------------>|                 |
  |                         |-- create Task (PENDING) ------------->|                 |
  |                         |-- COMMIT ---------------------------->|                 |
  |                         |                      |                 |                 |
  |                         |-- enqueue arq job (task_id) -------------------------->|
  |                         |-- update Task (arq_job_id), COMMIT -->|                 |
  |                         |                      |                 |                 |
  |                         |  [on enqueue failure: compensating update]              |
  |                         |  [Source -> FAILED, Task -> FAILED -->|]                |
  |                         |                      |                 |                 |
  |<-- 202 {task_id, source_id} --|                |                 |                 |
  |                         |                      |                 |                 |
  |                         |              arq Worker picks up job   |                 |
  |                         |                      |     Task -> PROCESSING ---------->|
  |                         |                      |     Source -> PROCESSING -------->|
  |                         |                      |     (noop: real pipeline in S2-02)|
  |                         |                      |     Source -> READY ------------->|
  |                         |                      |     Task -> COMPLETE ------------>|
  |                         |                      |                 |                 |
  |-- GET /api/admin/tasks/{id}   |                |                 |                 |
  |<-- {status, source_id, ...} --|                |                 |                 |
```

### Components

| Component | File | Responsibility |
|-----------|------|----------------|
| Admin router | `app/api/admin.py` | HTTP endpoints, request validation, response serialization |
| Storage service | `app/services/storage.py` | MinIO operations: upload, delete, key generation, bucket management |
| Source service | `app/services/source.py` | Source + Task creation, business logic orchestration |
| Worker settings | `app/workers/main.py` | arq WorkerSettings, DB engine init/shutdown, task function registry (path per architecture.md) |
| Worker runner | `app/workers/run.py` | Python 3.14-compatible wrapper that creates and runs the arq worker inside an active event loop |
| Ingestion task | `app/workers/tasks/ingestion.py` | Noop handler: status transitions for task and source |

---

## Database Schema

### New migration: `003_add_tasks_table.py`

```text
background_tasks
+-- id                  UUID, PK (uuid7)
+-- task_type           ENUM backgroundtasktype (INGESTION)
+-- status              ENUM backgroundtaskstatus (PENDING, PROCESSING, COMPLETE, FAILED, CANCELLED)
+-- source_id           FK -> sources.id, nullable
+-- arq_job_id          TEXT, nullable
+-- error_message       TEXT, nullable
+-- progress            INTEGER, nullable (0-100)
+-- result_metadata     JSONB, nullable
+-- (owner_id, agent_id via TenantMixin)
+-- (created_at, updated_at via TimestampMixin)
+-- started_at          TIMESTAMPTZ, nullable
+-- completed_at        TIMESTAMPTZ, nullable
```

**Indexes:** `ix_background_tasks_agent_id`, `ix_background_tasks_source_id`, `ix_background_tasks_status`

**Enum types:**

- `background_task_type_enum` (INGESTION) — Python enum class `BackgroundTaskType`, named to avoid collision with the existing `TaskType` enum in `enums.py` (which has RETRIEVAL/QUERY values for embedding profiles).
- `background_task_status_enum` (PENDING, PROCESSING, COMPLETE, FAILED, CANCELLED) — Python enum class `BackgroundTaskStatus`.

**SQLAlchemy model** (`BackgroundTask`) in `app/db/models/background_task.py` (own file, re-exported via `operations.py` for consistent import patterns). Uses `PrimaryKeyMixin`, `TimestampMixin`, `TenantMixin` (which provides `owner_id` and `agent_id` — not listed separately in the schema above to avoid duplication).

**Relationship:** `BackgroundTask.source_id -> Source.id` (many-to-one). One source can have multiple tasks (initial upload, reindex, etc.).

**Note on Document/DocumentVersion:** S2-01 does NOT create Document or DocumentVersion records. The noop worker only transitions Source and Task statuses. Document and DocumentVersion creation is part of the real ingestion pipeline in S2-02, when Docling parses the file and produces chunks. `# TODO(S2-02): Create Document + DocumentVersion records during ingestion.`

---

## API Contracts

### `POST /api/admin/sources`

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | UploadFile | yes | `.md` or `.txt` file |
| `metadata` | string (JSON) | yes | Source metadata (validated via Pydantic) |

**Metadata JSON schema:**

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `title` | string | yes | 1-255 characters (matches Source.title DB column `String(255)`) |
| `description` | string | no | max 2000 characters |
| `public_url` | string (URL) | no | valid HTTP/HTTPS URL |
| `catalog_item_id` | UUID | no | FK to catalog_items |
| `language` | string | no | Not stored on Source — used only to override the agent-level language setting for this upload's processing. Defaults to agent's `language` field. No new column needed on `sources` table. |

`source_type` is determined automatically from file extension (`.md` -> MARKDOWN, `.txt` -> TXT).

**Response:** `202 Accepted`

```json
{
  "source_id": "uuid",
  "task_id": "uuid",
  "status": "pending",
  "file_path": "00000000-.../a1b2c3-.../document.md",
  "message": "Source uploaded and queued for ingestion."
}
```

**Errors:** `422` (invalid format/metadata/empty file), `413` (file too large), `500` (infra failure).

### `GET /api/admin/tasks/{task_id}`

**Response:** `200 OK`

```json
{
  "id": "uuid",
  "task_type": "ingestion",
  "status": "complete",
  "source_id": "uuid",
  "progress": 100,
  "error_message": null,
  "result_metadata": {},
  "created_at": "ISO8601",
  "started_at": "ISO8601",
  "completed_at": "ISO8601"
}
```

**Errors:** `404` (task not found).

### Configuration

`UPLOAD_MAX_FILE_SIZE_MB=50` in settings. Validation approach: read the upload in chunks, track cumulative bytes during the read, and reject the request with 413 before uploading anything to MinIO once the configured limit is exceeded. This keeps the S2-01 Markdown/TXT flow simple while avoiding an unconditional full-file `read()` into memory.

---

## arq Worker Setup

### WorkerSettings (`app/workers/main.py`)

- `redis_settings` from `Settings.redis_url`
- `functions` — registered task handlers
- `max_jobs` — concurrency (default: 10)
- `job_timeout` — 600s (default, revisited in S2-02 for Docling)
- `retry_jobs` — False (fail-fast model in S2-01, no re-raise)

### Docker Compose

New `worker` service added:

```yaml
worker:
  build: ./backend
  command: python -m app.workers.run
  depends_on:
    postgres: { condition: service_healthy }
    redis: { condition: service_healthy }
    minio: { condition: service_healthy }
  env_file: [.env, backend/.env]
  environment:
    SKIP_MIGRATIONS: "1"
```

Same Docker image, different startup command (per architecture.md).

The direct `arq` CLI was replaced with a thin `app/workers/run.py` wrapper because Python 3.14 no longer provides an implicit event loop on the main thread. The wrapper calls `create_worker(WorkerSettings)` inside `asyncio.run(...)`, preserving the same worker settings contract while avoiding the CLI startup failure.

### Additional operational risk

The commit-before-enqueue pattern still has one accepted edge case in S2-01: arq enqueue can succeed while the follow-up `Task.arq_job_id` update fails. In that case the worker still receives `task_id` and can process the task correctly, but PostgreSQL loses the correlation identifier for the arq job. This is acceptable for the first E2E slice because task lifecycle remains correct; richer reconciliation and monitoring belong to later operational stories.

### Ingestion task handler (`app/workers/tasks/ingestion.py`)

Noop handler with full status lifecycle:

1. Load Task from PG, verify status == PENDING
2. Task.status -> PROCESSING, Task.started_at -> now()
3. Source.status -> PROCESSING
4. `# TODO(S2-02): Replace with Docling pipeline. Worker downloads file from MinIO, determines processing path (Path A: Gemini native / Path B: Docling), parses, chunks, generates embeddings, upserts to Qdrant. See docs/architecture.md Knowledge circuit.`
5. Source.status -> READY
6. Task.status -> COMPLETE, Task.completed_at -> now(), Task.progress -> 100

On exception: Task -> FAILED, Source -> FAILED, error_message saved. Do NOT re-raise — the task is already finalized as FAILED in PG, so arq retry would find a FAILED task and skip it anyway. Fail-fast is the correct model for S2-01 (noop worker has no retriable errors). When S2-02 introduces real processing with transient failures, the retry model should be revisited: either defer FAILED status until retry budget is exhausted, or allow the worker to process FAILED tasks with a retry counter.

### Worker DB access

Worker creates its own async DB engine and session factory via arq `on_startup` hook. Does not share connection pool with API (separate process).

---

## Error Handling

### Upload failure scenarios

| Scenario | Behavior | Cleanup |
|----------|----------|---------|
| MinIO upload fails | 500, nothing created in PG | Nothing to clean |
| PG create fails after MinIO upload | 500, delete file from MinIO | `storage.delete(key)` |
| arq enqueue fails after MinIO + PG commit | Compensating update: Source -> FAILED, Task -> FAILED. Return 500 | PG records marked FAILED, MinIO file remains (orphan cleanup in future) |
| Duplicate filename | Not a problem: key contains `source_id` (UUID), each upload creates a new source | N/A |

**Operation order in endpoint (fail-safe, commit-before-enqueue):**

1. Validate metadata + file -> fail fast (422)
2. Generate source_id (UUID)
3. Upload to MinIO -> on error: 500, nothing created
4. Create Source (PENDING) + Task (PENDING) in PG -> commit -> on error: delete from MinIO, 500
5. Enqueue arq job -> on success: update Task.arq_job_id, commit
6. On enqueue error: compensating update Source -> FAILED, Task -> FAILED (error_message), commit. Return 500.
7. Return 202

**Rationale for commit-before-enqueue:** If enqueue happens before commit, the worker may pick up the job before the PG transaction is visible, find no task, and silently exit — leaving the task stuck in PENDING forever. Committing first guarantees the task exists when the worker reads it. The trade-off is that on enqueue failure, we need a compensating update instead of a simple rollback — but this is a safer failure mode (FAILED is observable and recoverable; stuck PENDING is not).

### Worker failure scenarios

| Scenario | Behavior |
|----------|----------|
| Worker cannot connect to PG | arq retry (exponential backoff, max 3) |
| Task not found in PG | Log warning, return (idempotent) |
| Task already PROCESSING/COMPLETE | Log warning, skip (idempotent re-delivery) |
| Unhandled exception | Task -> FAILED, Source -> FAILED, error_message saved. No re-raise (fail-fast). |
| Worker crash mid-processing | Task stays PROCESSING. `TODO(S7-04): Add stale task detection. Tasks stuck in PROCESSING for >N minutes should be marked FAILED by a periodic check.` |

### File name safety

- Original filename preserved in `Source.title` (if title not specified in metadata) and in MinIO key
- Filename sanitization: strip path separators, limit length, replace unsafe characters
- MinIO key always unique due to `{source_id}` UUID prefix

---

## Testing Strategy

### Unit tests

**`tests/unit/test_source_validation.py`:**

- Metadata validation: required fields, lengths, types
- File validation: allowed extensions (.md, .txt), reject .pdf/.docx
- source_type determination from extension
- MinIO key generation: format correctness, filename sanitization

**`tests/unit/test_task_status.py`:**

- Enum values: BackgroundTaskType has INGESTION, BackgroundTaskStatus has all expected values
- No invalid transition tests in S2-01 — there is no transition guard layer yet (statuses are plain enum values on the model). Actual workflow transitions (PENDING -> PROCESSING -> COMPLETE) are tested in integration tests via the worker handler.

### Integration tests (PostgreSQL testcontainer)

**`tests/integration/test_migration_003.py`:**

- Migration 003 applies, `background_tasks` table created with correct columns
- Downgrade works: table and enum types removed
- Enum values match expectations

**`tests/integration/test_source_upload.py`:**

- Full flow via FastAPI TestClient:
  - Upload valid .md file -> 202, source_id + task_id in response
  - Source record in PG: correct fields, status=PENDING
  - Task record in PG: correct fields, status=PENDING, source_id linked
  - MinIO upload called with correct key (mocked)
  - arq enqueue called with task_id (mocked)
- Reject invalid file (.pdf) -> 422
- Reject empty file -> 422
- Reject invalid metadata (missing title) -> 422
- GET /api/admin/tasks/{id} -> 200 with correct fields
- GET /api/admin/tasks/{nonexistent} -> 404

**`tests/integration/test_ingestion_worker.py`:**

- Worker handler: task PENDING -> PROCESSING -> COMPLETE
- Worker handler: source PENDING -> PROCESSING -> READY
- Worker handler: on exception -> task FAILED, source FAILED, error_message populated

### Mocking strategy

- **MinIO:** mock via dependency injection. Storage service receives MinIO client through DI; tests substitute a mock.
- **arq:** mock enqueue function. Source service calls `enqueue_job()`; tests substitute a mock.
- **PostgreSQL:** real DB via testcontainer (already configured).

### Not tested in CI

- Real MinIO (mock sufficient for upload verification)
- Real Redis/arq transport (mock enqueue, test handler logic directly)
- E2E docker-compose flow (manual verification per plan)

---

## Deferred Work (TODOs)

| TODO | Story | Description |
|------|-------|-------------|
| Real ingestion pipeline | S2-02 | Replace noop worker body with Docling parsing, chunking, embedding |
| Document/DocumentVersion creation | S2-02 | Create Document and DocumentVersion records during ingestion (skipped in S2-01 noop worker) |
| Admin API auth | S7-01 | Add Bearer token middleware on `/api/admin/*` |
| Stale task detection | S7-04 | Periodic check for tasks stuck in PROCESSING |
| Additional formats | S3-01 | Extend file format whitelist to PDF, DOCX, HTML |
| Source list/delete endpoints | future | `GET /api/admin/sources`, `DELETE /api/admin/sources/:id` |

---

## Dependencies

### New Python packages

| Package | Version | Purpose |
|---------|---------|---------|
| `minio` | latest stable | MinIO client for file upload/download |
| `arq` | >= 0.27.0 | Async background job queue on Redis |

### Existing infrastructure (no changes)

- PostgreSQL (new migration only)
- Redis (arq transport)
- MinIO (bucket auto-created)
- Docker Compose (new `worker` service added)

---

Skills used: superpowers:brainstorming

Docs used: docs/plan.md, docs/spec.md, docs/architecture.md, docs/rag.md, docs/development.md
