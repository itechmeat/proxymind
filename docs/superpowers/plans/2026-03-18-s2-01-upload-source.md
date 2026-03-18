# S2-01: Upload Source — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accept a Markdown/TXT file via Admin API, persist it in MinIO, record metadata in PostgreSQL, and enqueue a background task via arq that transitions statuses through a full lifecycle.

**Architecture:** Multipart upload endpoint creates Source + BackgroundTask in PostgreSQL, uploads the file to MinIO with a tenant-ready key structure, and enqueues an arq job. A noop worker picks up the task and transitions Source/Task through their status lifecycles. Real parsing deferred to S2-02.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.x async, Alembic, `minio` SDK, `arq`, PostgreSQL, MinIO, Redis, pytest + testcontainers

**Design Spec:** `docs/superpowers/specs/2026-03-18-s2-01-upload-source-design.md`

**Skills available:** @fastapi, @postgresql, @minio, @sqlalchemy-2-async, @async-jobs, @python-testing-patterns, @property-based-testing

---

## File Map

### New files

| File | Responsibility |
|------|----------------|
| `backend/app/db/models/background_task.py` | BackgroundTask SQLAlchemy model |
| `backend/app/core/constants.py` | Canonical seeded IDs (DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID) |
| `backend/app/services/__init__.py` | Services package init |
| `backend/app/services/storage.py` | MinIO operations: upload, delete, key generation, bucket init |
| `backend/app/services/source.py` | Source + BackgroundTask creation, upload orchestration |
| `backend/app/api/admin.py` | Admin API router: POST sources, GET tasks |
| `backend/app/api/schemas.py` | Pydantic request/response schemas |
| `backend/app/api/dependencies.py` | FastAPI DI providers: storage, source service, arq enqueuer |
| `backend/app/workers/__init__.py` | Workers package init |
| `backend/app/workers/main.py` | arq WorkerSettings, on_startup/on_shutdown, task registry |
| `backend/app/workers/run.py` | Python 3.14-compatible worker runner around `create_worker()` |
| `backend/app/workers/tasks/__init__.py` | Tasks package init |
| `backend/app/workers/tasks/ingestion.py` | Noop ingestion handler with status transitions |
| `backend/migrations/versions/003_add_background_tasks_table.py` | Migration for background_tasks table |
| `backend/tests/unit/__init__.py` | Package init |
| `backend/tests/unit/test_source_validation.py` | Metadata/file validation unit tests |
| `backend/tests/unit/test_task_status.py` | Task status transition unit tests |
| `backend/tests/integration/test_source_upload.py` | Upload endpoint integration tests |
| `backend/tests/integration/test_ingestion_worker.py` | Worker handler integration tests |

### Modified files

| File | Change |
|------|--------|
| `backend/pyproject.toml:6-16` | Add `minio`, `arq>=0.27.0`, `python-multipart` to dependencies |
| `backend/app/db/models/enums.py:118` | Append `BackgroundTaskType` and `BackgroundTaskStatus` enums |
| `backend/app/db/models/operations.py:11` | Re-export BackgroundTask |
| `backend/app/db/models/__init__.py:11,14` | Export BackgroundTask in `__all__` |
| `backend/app/core/config.py:31` | Add `upload_max_file_size_mb` and `minio_bucket_sources` settings |
| `backend/app/main.py:1-46` | Add MinIO client init, bucket creation, arq pool, admin router |
| `docker-compose.yml:100` | Add `worker` service before `volumes:` |
| `backend/tests/conftest.py` | Add mock fixtures for MinIO storage service and arq pool |

---

## Tasks

### Task 1: Add dependencies

- [ ] Add `arq>=0.27.0`, `minio>=7.2.0`, `python-multipart>=0.0.20` to `pyproject.toml` dependencies
- [ ] Run `uv sync` to install and update lock file
- [ ] Verify imports: `python -c "import minio; import arq; print('OK')"`
- [ ] Checkpoint (review locally, prepare for commit)

### Task 2: Add BackgroundTask enums and model

- [ ] Add `BackgroundTaskType(StrEnum)` with value `INGESTION` to `enums.py` — named to avoid collision with existing `TaskType` (RETRIEVAL/QUERY for EmbeddingProfile)
- [ ] Add `BackgroundTaskStatus(StrEnum)` with values: PENDING, PROCESSING, COMPLETE, FAILED, CANCELLED
- [ ] Create `background_task.py` model using `PrimaryKeyMixin`, `TenantMixin`, `TimestampMixin`. Fields: `task_type`, `status`, `source_id` (FK → sources.id, nullable, indexed), `arq_job_id` (String), `error_message` (Text), `progress` (Integer), `result_metadata` (JSONB), `started_at`, `completed_at`
- [ ] Re-export from `operations.py` and add to `__init__.py` `__all__`
- [ ] Write unit tests for enum values in `test_task_status.py` — verify BackgroundTaskType has INGESTION, BackgroundTaskStatus has all expected values. No invalid transition tests (no guard layer yet; actual workflow transitions tested in integration tests)
- [ ] Run tests, verify pass
- [ ] Checkpoint (review locally, prepare for commit)

### Task 3: Alembic migration

- [ ] Run `alembic revision --autogenerate -m "add background_tasks table"`
- [ ] Review generated migration: must create enum types `background_task_type_enum`, `background_task_status_enum`, table `background_tasks` with all columns and indexes. Downgrade must drop table and enum types.
- [ ] Rename file to `003_add_background_tasks_table.py` (keep revision ID)
- [ ] Write integration test: verify table exists with correct columns, verify enum values
- [ ] Run migration test, verify pass
- [ ] Checkpoint (review locally, prepare for commit)

### Task 4: Settings extensions and constants

- [ ] Add `upload_max_file_size_mb: int = 50` and `minio_bucket_sources: str = "sources"` to `Settings` in `config.py`
- [ ] Create `app/core/constants.py` with `DEFAULT_AGENT_ID` and `DEFAULT_KNOWLEDGE_BASE_ID` — same UUIDs as in seed migration 002, but as app-level constants (no import from migration files)
- [ ] Verify: `python -c "from app.core.config import get_settings; s = get_settings(); print(s.upload_max_file_size_mb)"`
- [ ] Verify: `python -c "from app.core.constants import DEFAULT_AGENT_ID; print(DEFAULT_AGENT_ID)"`
- [ ] Checkpoint (review locally, prepare for commit)

### Task 5: Storage service (MinIO)

- [ ] Create `services/__init__.py`
- [ ] Create `StorageService` class in `storage.py`:
  - Constructor takes `Minio` client and bucket name
  - `generate_object_key(agent_id, source_id, filename)` — static method. Key: `{agent_id}/{source_id}/{sanitized_filename}`. Sanitize: strip path separators, limit to 255 chars, replace characters outside `[A-Za-z0-9._-]` with `_`
  - `ensure_bucket()` — check if bucket exists, create if not. Use `asyncio.to_thread()` since minio SDK is synchronous
  - `upload(key, data, content_type)` — put_object via `asyncio.to_thread()`, return key
  - `delete(key)` — remove_object via `asyncio.to_thread()`
- [ ] Create `validate_file_extension(filename, allowed)` function — returns lowercase ext or raises `ValueError`
- [ ] Create `determine_source_type(extension)` function — maps `.md` → MARKDOWN, `.txt` → TXT
- [ ] Write unit tests in `test_source_validation.py`: key generation (normal, path traversal, long filename), extension validation (valid, invalid, case-insensitive), source type determination
- [ ] Run unit tests, verify pass
- [ ] Checkpoint (review locally, prepare for commit)

### Task 6: Source service and Pydantic schemas

- [ ] Create `schemas.py` with:
  - `SourceUploadMetadata` — `title` (1-255 chars, matches DB column String(255)), `description` (optional, max 2000), `public_url` (optional, HttpUrl), `catalog_item_id` (optional, UUID), `language` (optional, str — not stored on Source, processing override only)
  - `SourceUploadResponse` — `source_id`, `task_id`, `status`, `file_path`, `message`
  - `TaskStatusResponse` — `id`, `task_type`, `status`, `source_id`, `progress`, `error_message`, `result_metadata`, `created_at`, `started_at`, `completed_at`
- [ ] Create `SourceService` in `source.py`:
  - Define `TaskEnqueuer` Protocol with async `enqueue(task_id) -> str`
  - Constructor takes `AsyncSession` and `TaskEnqueuer`
  - `create_source_and_task(source_id, ...)` — **important**: accept pre-generated `source_id` and set `source.id = source_id` explicitly (matches the UUID already used for MinIO key). Create Source (PENDING) and BackgroundTask (PENDING), **commit first** (so worker can see the records), then call enqueuer. On enqueue success: update `arq_job_id`, commit. On enqueue failure: compensating update Source → FAILED, Task → FAILED with error_message, commit, re-raise
  - `get_task(task_id)` — select by ID, return or None
  - Use `DEFAULT_AGENT_ID` and `DEFAULT_KNOWLEDGE_BASE_ID` constants from `app/core/constants.py` (new file — canonical seeded IDs, not imported from migration files)
- [ ] Verify imports
- [ ] Checkpoint (review locally, prepare for commit)

### Task 7: Admin router, dependencies, and main.py update

- [ ] Create `dependencies.py`:
  - `get_storage_service(request)` — returns `request.app.state.storage_service`
  - `ArqTaskEnqueuer` class implementing `TaskEnqueuer` — wraps `ArqRedis.enqueue_job("process_ingestion", task_id_str)`, returns `job.job_id`
  - `get_source_service(request, session)` — creates `ArqTaskEnqueuer` from `request.app.state.arq_pool`, returns `SourceService`
- [ ] Create `admin.py` router with prefix `/api/admin`. **Router responsibility boundary**: router only validates request, uploads file to MinIO, and delegates all PG + enqueue orchestration to `SourceService`. Router does NOT own commit/enqueue logic.
  - `POST /sources` (202): accept `UploadFile` + `metadata` (Form string → validate as JSON via `SourceUploadMetadata.model_validate_json`). Read settings from `request.app.state.settings` (not `get_settings()`). Validate file extension, reject empty files with 422, and enforce the upload size limit while streaming request bytes so oversized uploads fail with 413 before MinIO upload. Generate `source_id = uuid.uuid7()`, build MinIO key, upload to MinIO via StorageService. Then call `source_service.create_source_and_task(...)` which handles PG commit + enqueue + compensating failure. On MinIO failure: 500, nothing in PG. On service failure: cleanup MinIO file. Add `# TODO(S7-01)` for auth with security exception note (local-only deployment).
  - `GET /tasks/{task_id}` (200/404): delegate to `source_service.get_task()`, return `TaskStatusResponse`
- [ ] Update `main.py` lifespan:
  - Initialize `Minio` client (host:port, access_key, secret_key, `secure=False` for local Docker development in S2-01)
  - Create `StorageService`, call `ensure_bucket()`, store in `app.state.storage_service`
  - Create arq pool via `create_pool(RedisSettings(...))`, store in `app.state.arq_pool`
  - Shutdown: `await app.state.arq_pool.close()` (async!), then existing cleanup
  - Include `admin_router`
- [ ] Verify app loads: `python -c "from app.main import app; print([r.path for r in app.routes])"`
- [ ] Checkpoint (review locally, prepare for commit)

### Task 8: arq worker setup

- [ ] Create package inits: `workers/__init__.py`, `workers/tasks/__init__.py`
- [ ] Create `workers/tasks/ingestion.py` — `process_ingestion(ctx, task_id_str)`:
  - Get `session_factory` from ctx
  - Load task from PG, verify status == PENDING (skip if not, log warning)
  - Transition: Task → PROCESSING (set `started_at`), Source → PROCESSING
  - Noop body with `# TODO(S2-02)` describing the full Docling pipeline
  - Transition: Source → READY, Task → COMPLETE (set `completed_at`, `progress=100`)
  - On exception: rollback, mark Task → FAILED + Source → FAILED with error_message in a fresh session. Do NOT re-raise (fail-fast: task is already FAILED, arq retry would just skip it)
- [ ] Create `workers/main.py` — `WorkerSettings`:
  - `functions = [process_ingestion]`
  - `on_startup` — create async DB engine + session_factory, store in ctx
  - `on_shutdown` — dispose engine
  - `redis_settings` — class attribute, evaluate `RedisSettings` from `get_settings()` at import time
  - `max_jobs = 10`, `job_timeout = 600`
- [ ] Verify: `python -c "from app.workers.main import WorkerSettings; print(WorkerSettings.functions)"`
- [ ] Checkpoint (review locally, prepare for commit)

### Task 9: Docker Compose — add worker service

- [ ] Add `worker` service to `docker-compose.yml`:
  - Build from `./backend`, command: `python -m app.workers.run`
  - Same env_file as api, depends_on postgres/redis/minio (healthy)
  - Set `SKIP_MIGRATIONS=1` so worker does not race the API container during Alembic startup
  - No port mapping, no healthcheck needed
- [ ] Verify: `docker compose config --services` includes `worker`
- [ ] Checkpoint (review locally, prepare for commit)

### Task 10: Integration tests — upload endpoint

- [ ] Add mock fixtures to `conftest.py`:
  - `mock_storage_service` — MagicMock(spec=StorageService), async upload/delete, static `generate_object_key` from real class
  - `mock_arq_pool` — MagicMock with async `enqueue_job` returning fake job
- [ ] Create `test_source_upload.py` with TestClient fixture that sets `app.state.*` to mocks (bypass lifespan):
  - Test: upload valid .md → 202 with source_id, task_id, status
  - Test: upload valid .txt → 202
  - Test: upload .pdf → 422 "Unsupported file extension"
  - Test: upload empty file → 422
  - Test: invalid metadata JSON → 422
  - Test: missing title in metadata → 422
  - Test: upload then GET task → 200 with correct task_type, status, source_id (round-trip)
  - Test: enqueue failure (mock `enqueue_job` to raise) → 500, Source and Task in PG have status FAILED with error_message
  - Test: GET nonexistent task → 404
- [ ] Run tests, verify all pass
- [ ] Checkpoint (review locally, prepare for commit)

### Task 11: Integration tests — worker handler

- [ ] Create `test_ingestion_worker.py`:
  - Use dedicated `worker_session_factory` fixture (real commits, not savepoint-rollback) — needed because worker creates its own sessions via session_factory
  - Add `autouse` cleanup fixture that DELETEs test BackgroundTasks and Sources after each test
  - Test: create source+task (real commit), run `process_ingestion`, verify task → COMPLETE (progress=100, timestamps set) and source → READY
  - Test: mark task as COMPLETE before worker, run worker, verify source stays PENDING (skipped)
  - Test: call with nonexistent task_id, verify no exception
- [ ] Run tests, verify all pass
- [ ] Checkpoint (review locally, prepare for commit)

### Task 12: Full lint + test run

- [ ] Run `ruff check app/ tests/` — fix any issues
- [ ] Run `ruff format --check app/ tests/` — fix any formatting
- [ ] Run `python -m pytest tests/ -v` — all tests pass
- [ ] Checkpoint (review locally, prepare for commit) fixes if any

### Task 13: Manual E2E verification

- [ ] `docker compose up --build -d` — wait for all services healthy
- [ ] `curl -X POST http://localhost:8000/api/admin/sources -F "file=@docs/plan.md" -F 'metadata={"title":"Development Plan"}'` → 202 with task_id
- [ ] `curl http://localhost:8000/api/admin/tasks/{task_id}` → 200 with status "complete", progress 100
- [ ] Verify file in MinIO console (localhost:9001) in `sources` bucket
- [ ] Verify records in PostgreSQL: `SELECT id, title, status FROM sources` → status "ready"; `SELECT id, status, progress FROM background_tasks` → status "complete"
- [ ] `curl -X POST ... -F "file=@backend/Dockerfile" ...` → 422 "Unsupported file extension"
- [ ] `docker compose down`

---

## Implementation Notes

Key decisions from reviews that affect implementation (not obvious from spec):

1. **source_id identity**: Pre-generate `source_id = uuid.uuid7()` in endpoint, pass it to `create_source_and_task(source_id=...)` which sets `source.id = source_id`. This ensures MinIO key and PG record share the same UUID.

2. **Commit-before-enqueue**: Source+Task are committed to PG before enqueuing the arq job. This prevents a race where the worker picks up the job before the PG transaction is visible. On enqueue failure: compensating update marks Source/Task as FAILED.

3. **Fail-fast worker, no re-raise**: On exception, mark Task/Source as FAILED and do NOT re-raise. Since the task is already FAILED, arq retry would just skip it. Retry model revisited in S2-02 when real transient failures are possible.

4. **Settings access in endpoint**: Use `request.app.state.settings` instead of `get_settings()` — avoids env var dependency in tests.

5. **arq pool close**: `await app.state.arq_pool.close()` — ArqRedis.close() is async.

6. **WorkerSettings.redis_settings**: Must be a class attribute (RedisSettings instance), not a method. arq expects a plain attribute.

7. **Worker test isolation**: Worker creates its own sessions, so tests must use real committed data with explicit cleanup — not the savepoint-rollback pattern used by other integration tests.

8. **Constants module**: `app/core/constants.py` holds canonical seeded IDs (DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID). Runtime code must NOT import from migration files.

9. **BackgroundTask in separate file**: `background_task.py` rather than adding to `operations.py` — keeps focused files, re-exported via `operations.py` for consistency.

10. **Security exception for no-auth**: Explicitly documented in spec as deviation from development.md principles 10-11. S2-01 Admin API is local-only, not for exposed deployments. TODO(S7-01) is mandatory before any non-local deployment.

11. **Checkpoints, not commits**: Plan steps say "Checkpoint" instead of "Commit" — actual commits require explicit user permission per repo policy.

12. **Accepted enqueue/update edge case**: arq enqueue can succeed while the follow-up `arq_job_id` update fails. In S2-01 this is acceptable because the worker still receives `task_id` and completes the lifecycle correctly; only the arq correlation identifier is lost.

---

Skills used: superpowers:writing-plans, superpowers:brainstorming, find-skills

Docs used: docs/plan.md, docs/spec.md, docs/architecture.md, docs/development.md, docs/superpowers/specs/2026-03-18-s2-01-upload-source-design.md
