## Story

**S2-01: Upload source** (Phase 2 — First E2E Slice)

Verification criteria from plan.md: `curl -F file=@doc.md /api/admin/sources` → 202 + task_id; file in MinIO; record in PG.

Phase 2 stable behavior that MUST be covered by tests: upload endpoint validation, Source + BackgroundTask creation, task status retrieval, worker status lifecycle.

## Why

Phase 2 begins the first end-to-end slice — upload a document, process it, ask a question, get an answer. S2-01 is the entry point: accepting source files into the system. Without it, the knowledge circuit has no input. This is the first Admin API endpoint and the first use of MinIO and arq in the project.

## What Changes

- New `POST /api/admin/sources` endpoint accepting Markdown/TXT files with JSON metadata via multipart upload, rejecting empty files and unsupported extensions with `422`, and rejecting files above `UPLOAD_MAX_FILE_SIZE_MB` (default `50`) with `413`
- New `GET /api/admin/tasks/{id}` endpoint for background task status polling
- MinIO integration: file storage service with bucket auto-creation at startup
- arq integration: background task queue with noop ingestion worker (real pipeline in S2-02)
- New `background_tasks` table in PostgreSQL for tracking async job lifecycle
- New `BackgroundTaskType` and `BackgroundTaskStatus` enums
- Docker Compose: new `worker` service (same image, arq entrypoint)
- App-level constants module for canonical seeded IDs

## Capabilities

### New Capabilities

- `source-upload`: Admin API file upload, MinIO storage, Source + BackgroundTask creation, arq enqueue with commit-before-enqueue pattern
- `background-tasks`: Background task model, status lifecycle, task status API, arq worker infrastructure

### Modified Capabilities

- `infrastructure`: Docker Compose gains a `worker` service; MinIO client and arq pool initialized in FastAPI lifespan

## Impact

- **Backend code**: new files in `app/services/`, `app/api/`, `app/workers/`, `app/core/constants.py`, `app/db/models/background_task.py`
- **Dependencies**: `minio`, `arq>=0.27.0`, `python-multipart` added to `pyproject.toml`
- **Database**: new migration `003_add_background_tasks_table.py`
- **Docker**: new `worker` service in `docker-compose.yml`
- **Admin API security**: no auth in S2-01 (explicit security exception — local-only deployment, TODO S7-01)
