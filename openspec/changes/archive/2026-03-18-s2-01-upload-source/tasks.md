## 1. Dependencies and Configuration

- [x] 1.1 Add `arq>=0.27.0`, `minio>=7.2.0`, `python-multipart>=0.0.20` to `pyproject.toml`, run `uv sync`
- [x] 1.2 Create `app/core/constants.py` with `DEFAULT_AGENT_ID` and `DEFAULT_KNOWLEDGE_BASE_ID` (canonical seeded IDs)
- [x] 1.3 Add `upload_max_file_size_mb` and `minio_bucket_sources` settings to `app/core/config.py`

## 2. Database: Enums, Model, Migration

- [x] 2.1 Add `BackgroundTaskType` and `BackgroundTaskStatus` enums to `app/db/models/enums.py`
- [x] 2.2 Create `app/db/models/background_task.py` — BackgroundTask model (PrimaryKeyMixin, TenantMixin, TimestampMixin; fields: task_type, status, source_id FK, arq_job_id, error_message, progress, result_metadata, started_at, completed_at)
- [x] 2.3 Re-export BackgroundTask from `operations.py` and `__init__.py`
- [x] 2.4 Generate Alembic migration `003_add_background_tasks_table.py` (autogenerate + review + rename)
- [x] 2.5 Write unit tests for enum values (`tests/unit/test_task_status.py`)
- [x] 2.6 Write integration test for migration — table exists, correct columns, enum values (`tests/integration/`)

## 3. Storage Service (MinIO)

- [x] 3.1 Create `app/services/__init__.py` and `app/services/storage.py` — StorageService class with `generate_object_key`, `ensure_bucket`, `upload`, `delete` (all via `asyncio.to_thread`)
- [x] 3.2 Create `validate_file_extension` and `determine_source_type` helper functions in storage.py
- [x] 3.3 Write unit tests for key generation, filename sanitization, extension validation (valid, invalid, case-insensitive), source type mapping (`tests/unit/test_source_validation.py`)
- [x] 3.4 Write unit tests for SourceUploadMetadata validation: missing title, title exceeds 255, invalid JSON string, invalid URL format (`tests/unit/test_source_validation.py`)

## 4. Source Service and Schemas

- [x] 4.1 Create `app/api/schemas.py` — SourceUploadMetadata, SourceUploadResponse, TaskStatusResponse (Pydantic models)
- [x] 4.2 Create `app/services/source.py` — SourceService with `create_source_and_task` (commit-before-enqueue, compensating FAILED on enqueue error) and `get_task`; TaskEnqueuer Protocol

## 5. Admin API Router and App Wiring

- [x] 5.1 Create `app/api/dependencies.py` — get_storage_service, ArqTaskEnqueuer, get_source_service
- [x] 5.2 Create `app/api/admin.py` — POST /api/admin/sources (202), GET /api/admin/tasks/{task_id} (200/404); router validates + uploads, delegates orchestration to SourceService
- [x] 5.3 Update `app/main.py` — MinIO client init, StorageService + bucket creation, arq pool, admin router; shutdown with `await arq_pool.close()`

## 6. arq Worker

- [x] 6.1 Create `app/workers/__init__.py`, `app/workers/tasks/__init__.py`
- [x] 6.2 Create `app/workers/tasks/ingestion.py` — process_ingestion handler (noop with full status lifecycle, fail-fast no re-raise, TODO(S2-02) for real pipeline, TODO(S7-04) for stale task detection near fail-fast logic)
- [x] 6.3 Create `app/workers/main.py` — WorkerSettings (redis_settings as class attribute, on_startup/on_shutdown with DB engine)

## 7. Docker Compose

- [x] 7.1 Add `worker` service to `docker-compose.yml`: same Docker image as `api` (build from `./backend`), command `python -m app.workers.run`, depends_on postgres/redis/minio (healthy), env_file with root `.env` and `backend/.env`, `SKIP_MIGRATIONS=1`, no port mapping, no healthcheck

## 8. Integration Tests

- [x] 8.1 Add mock fixtures to `tests/conftest.py` (mock_storage_service, mock_arq_pool)
- [x] 8.2 Write upload endpoint tests (`tests/integration/test_source_upload.py`) — valid .md/.txt, reject .pdf/empty/oversized, invalid metadata, round-trip GET task, enqueue failure → compensating FAILED, GET nonexistent task → 404
- [x] 8.3 Write worker handler tests (`tests/integration/test_ingestion_worker.py`) — full lifecycle, skip non-PENDING, handle missing task (dedicated worker_session_factory with real commits + cleanup)

## 9. Verification

- [x] 9.1 Run `ruff check` + `ruff format --check` — fix any issues
- [x] 9.2 Run full test suite `pytest tests/ -v` — all pass
- [x] 9.3 Manual E2E: `docker compose up --build`, upload .md via curl → 202, GET task → complete, verify MinIO + PG, reject invalid format → 422
