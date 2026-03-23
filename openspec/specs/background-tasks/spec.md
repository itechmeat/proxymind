## ADDED Requirements

### Requirement: BackgroundTask model and enums

**[Modified by S3-06]** The system SHALL define a `BackgroundTask` SQLAlchemy model in `app/db/models/background_task.py`, re-exported via `operations.py` and `__init__.py`. The model SHALL use `PrimaryKeyMixin`, `TenantMixin`, and `TimestampMixin`. Two new PostgreSQL native enum types SHALL be created: `background_task_type_enum` (values: INGESTION, BATCH_EMBEDDING) and `background_task_status_enum` (values: PENDING, PROCESSING, COMPLETE, FAILED, CANCELLED). The enum class names SHALL be `BackgroundTaskType` and `BackgroundTaskStatus` to avoid collision with the existing `TaskType` enum (which has RETRIEVAL/QUERY values for EmbeddingProfile).

**[Modified by S3-06]** `BackgroundTaskType` uses `native_enum=True` in PostgreSQL. Adding the `BATCH_EMBEDDING` value requires `ALTER TYPE background_task_type_enum ADD VALUE 'BATCH_EMBEDDING'`, which cannot run inside a transaction in PostgreSQL. The Alembic migration MUST use `op.execute()` outside the default transaction context (e.g., separate migration step with `autocommit` or `connection.execution_options(isolation_level="AUTOCOMMIT")`).

#### Scenario: BackgroundTaskType enum has expected values

- **WHEN** the `BackgroundTaskType` enum is inspected
- **THEN** it SHALL contain exactly the values INGESTION and BATCH_EMBEDDING

#### Scenario: BackgroundTaskStatus enum has expected values

- **WHEN** the `BackgroundTaskStatus` enum is inspected
- **THEN** it SHALL contain exactly the values PENDING, PROCESSING, COMPLETE, FAILED, CANCELLED

#### Scenario: BackgroundTask model is importable from models package

- **WHEN** `from app.db.models import BackgroundTask` is executed
- **THEN** the import SHALL succeed without error

#### Scenario: Enum type names are unique in the schema

- **WHEN** the PostgreSQL schema is inspected
- **THEN** `background_task_type_enum` and `background_task_status_enum` SHALL exist as distinct named enum types that do not collide with any existing enum types

#### Scenario: ALTER TYPE migration adds BATCH_EMBEDDING outside transaction

- **WHEN** the Alembic migration for S3-06 is applied
- **THEN** the `ALTER TYPE background_task_type_enum ADD VALUE 'BATCH_EMBEDDING'` statement SHALL execute outside a transaction block
- **AND** the migration SHALL not fail due to transaction context restrictions

---

### Requirement: BackgroundTask table schema

**[Modified by S3-06]** The `background_tasks` table SHALL contain the following columns: `id` (UUID PK via PrimaryKeyMixin), `task_type` (background_task_type_enum, not nullable), `status` (background_task_status_enum, not nullable), `source_id` (UUID FK to sources.id, nullable, indexed), `arq_job_id` (String, nullable), `error_message` (Text, nullable), `progress` (Integer, nullable, range 0-100), `result_metadata` (JSONB, nullable), `started_at` (DateTime with timezone, nullable), `completed_at` (DateTime with timezone, nullable), plus `owner_id` and `agent_id` from TenantMixin, and `created_at` and `updated_at` from TimestampMixin.

**[Modified by S3-06]** For `BATCH_EMBEDDING` tasks, `source_id` SHALL be NULL because batch tasks span multiple sources. The list of source_ids SHALL be stored in `result_metadata` as `{"source_ids": [...], "knowledge_base_id": "...", "snapshot_id": "..."}`. The `knowledge_base_id` is stored in metadata because `BackgroundTask` inherits `TenantMixin` (which provides `agent_id`) but not `KnowledgeScopeMixin`.

#### Scenario: Table has all required columns

- **WHEN** the `background_tasks` table is inspected in PostgreSQL
- **THEN** all specified columns SHALL exist with the correct types and nullability

#### Scenario: source_id FK constraint

- **WHEN** a BackgroundTask is created with a `source_id` referencing a valid Source
- **THEN** the FK constraint SHALL be satisfied

- **WHEN** a BackgroundTask is created with a `source_id` referencing a non-existent Source
- **THEN** the database SHALL reject the insert

#### Scenario: Indexes exist on frequently queried columns

- **WHEN** the `background_tasks` table indexes are inspected
- **THEN** indexes SHALL exist on `agent_id`, `source_id`, and `status`

#### Scenario: One source can have multiple tasks

- **WHEN** two BackgroundTask records are created referencing the same `source_id`
- **THEN** both inserts SHALL succeed (many-to-one relationship)

#### Scenario: BATCH_EMBEDDING task has NULL source_id

- **WHEN** a BackgroundTask is created with `task_type=BATCH_EMBEDDING`
- **THEN** `source_id` SHALL be NULL
- **AND** `result_metadata` SHALL contain `source_ids` (array of UUIDs), `knowledge_base_id` (UUID string), and `snapshot_id` (UUID string)

#### Scenario: BATCH_EMBEDDING result_metadata contains required fields

- **WHEN** a BATCH_EMBEDDING BackgroundTask's `result_metadata` is inspected
- **THEN** it SHALL contain `source_ids` as an array of UUID strings
- **AND** it SHALL contain `knowledge_base_id` as a UUID string
- **AND** it SHALL contain `snapshot_id` as a UUID string

---

### Requirement: Alembic migration for background_tasks

An Alembic migration SHALL create the `background_tasks` table, the `background_task_type_enum` and `background_task_status_enum` PostgreSQL enum types, and all required indexes. The downgrade SHALL drop the table and both enum types.

#### Scenario: Migration applies successfully

- **WHEN** the migration is applied to a database with existing schema (migrations 001 and 002)
- **THEN** the `background_tasks` table SHALL be created with all columns and indexes

#### Scenario: Migration downgrade removes table and enums

- **WHEN** the migration is downgraded
- **THEN** the `background_tasks` table SHALL be dropped
- **AND** the `background_task_type_enum` and `background_task_status_enum` types SHALL be removed from PostgreSQL

#### Scenario: Enum values match model definitions

- **WHEN** the migration is applied and `pg_enum` is queried
- **THEN** `background_task_type_enum` SHALL contain exactly ('INGESTION', 'BATCH_EMBEDDING')
- **AND** `background_task_status_enum` SHALL contain exactly ('PENDING', 'PROCESSING', 'COMPLETE', 'FAILED', 'CANCELLED')

---

### Requirement: GET /api/admin/tasks/{task_id} endpoint

The API SHALL expose a `GET /api/admin/tasks/{task_id}` endpoint that returns the status and details of a background task. The response SHALL include: `id`, `task_type`, `status`, `source_id`, `progress`, `error_message`, `result_metadata`, `created_at`, `started_at`, `completed_at`.

#### Scenario: Existing task returns 200

- **WHEN** a GET request is sent to `/api/admin/tasks/{task_id}` with a valid task ID
- **THEN** the response status SHALL be 200
- **AND** the response body SHALL contain all specified fields

#### Scenario: Non-existent task returns 404

- **WHEN** a GET request is sent to `/api/admin/tasks/{task_id}` with a UUID that does not exist
- **THEN** the response status SHALL be 404

#### Scenario: Task status reflects full lifecycle

- **WHEN** a task has been processed by the worker to completion
- **THEN** `GET /api/admin/tasks/{task_id}` SHALL return `status` as "complete", `progress` as 100, `started_at` and `completed_at` as non-null ISO8601 timestamps

#### Scenario: Failed task includes error message

- **WHEN** a task has failed
- **THEN** `GET /api/admin/tasks/{task_id}` SHALL return `status` as "failed" and `error_message` as a non-null string describing the failure

---

### Requirement: arq worker infrastructure

The system SHALL provide an arq worker entry point at `app/workers/main.py` defining `WorkerSettings` with: `functions` (registered task handlers), `redis_settings` (from application configuration), `max_jobs` (default 10), `job_timeout` (default 600 seconds). The worker SHALL create its own async DB engine and session factory via the arq `on_startup` hook and dispose the engine via `on_shutdown`. The worker SHALL NOT share a connection pool with the API process.

#### Scenario: WorkerSettings is importable

- **WHEN** `from app.workers.main import WorkerSettings` is executed
- **THEN** the import SHALL succeed
- **AND** `WorkerSettings.functions` SHALL contain the ingestion task handler

#### Scenario: Worker creates independent DB engine

- **WHEN** the arq worker starts via `on_startup`
- **THEN** a new async DB engine and session factory SHALL be created
- **AND** they SHALL be stored in the arq context dict

#### Scenario: Worker disposes DB engine on shutdown

- **WHEN** the arq worker shuts down via `on_shutdown`
- **THEN** `engine.dispose()` SHALL be called

---

### Requirement: Noop ingestion task handler with full status lifecycle

The ingestion task handler (`app/workers/tasks/ingestion.py`) SHALL implement a noop handler that transitions task and source through a full status lifecycle: Task PENDING -> PROCESSING -> COMPLETE, Source PENDING -> PROCESSING -> READY. The handler SHALL accept a `task_id` string, load the BackgroundTask from PostgreSQL, verify status is PENDING, and perform the transitions. The noop body SHALL contain a `TODO(S2-02)` comment describing the real Docling pipeline to be implemented.

#### Scenario: Successful noop processing

- **WHEN** the ingestion handler processes a task with status PENDING
- **THEN** the BackgroundTask status SHALL transition to PROCESSING (with `started_at` set) then to COMPLETE (with `completed_at` set and `progress` set to 100)
- **AND** the associated Source status SHALL transition to PROCESSING then to READY

#### Scenario: Non-PENDING task is skipped

- **WHEN** the ingestion handler is invoked for a task with status other than PENDING (e.g., COMPLETE, PROCESSING)
- **THEN** the handler SHALL log a warning and return without modifying any records

#### Scenario: Non-existent task is handled gracefully

- **WHEN** the ingestion handler is invoked with a `task_id` that does not exist in PostgreSQL
- **THEN** the handler SHALL log a warning and return without raising an exception

---

### Requirement: Fail-fast worker error handling

On any unhandled exception during task processing, the worker SHALL mark the BackgroundTask as FAILED (with `error_message` populated) and the associated Source as FAILED. The worker SHALL NOT re-raise the exception after marking the failure. This fail-fast behavior is correct for S2-01 (noop worker has no retriable errors); the retry model SHALL be revisited when S2-02 introduces real processing with transient failures.

#### Scenario: Exception marks task and source as FAILED

- **WHEN** an unhandled exception occurs during task processing
- **THEN** the BackgroundTask status SHALL be set to FAILED with `error_message` containing the exception description
- **AND** the associated Source status SHALL be set to FAILED
- **AND** the exception SHALL NOT propagate to arq (no re-raise)

#### Scenario: Error message is persisted

- **WHEN** a task fails and `GET /api/admin/tasks/{task_id}` is called
- **THEN** the `error_message` field SHALL be non-null and contain information about the failure

---

### Requirement: TODO markers for deferred work

The ingestion task handler SHALL contain `TODO(S2-02)` comments describing the replacement of the noop body with the real Docling pipeline (download from MinIO, determine processing path, parse, chunk, embed, upsert to Qdrant). A `TODO(S7-04)` comment SHALL reference stale task detection for tasks stuck in PROCESSING.

#### Scenario: TODO markers present in worker code

- **WHEN** the ingestion task handler source code is inspected
- **THEN** a `TODO(S2-02)` comment SHALL be present describing the real ingestion pipeline
- **AND** the comment SHALL reference Docling, MinIO, and Qdrant

---

### Requirement: CI test coverage for background tasks

Background task model, status lifecycle, and worker behavior SHALL be covered by deterministic CI tests. Tests SHALL use a real PostgreSQL testcontainer. Worker tests SHALL use real committed data with explicit cleanup (not savepoint-rollback) because the worker creates its own sessions via session factory.

#### Scenario: Unit tests cover enum definitions

- **WHEN** unit tests are executed
- **THEN** tests SHALL verify `BackgroundTaskType` has INGESTION and `BackgroundTaskStatus` has all five expected values

#### Scenario: Integration tests cover migration

- **WHEN** integration tests are executed with a PostgreSQL testcontainer
- **THEN** tests SHALL verify: migration applies successfully, `background_tasks` table exists with correct columns, enum values match expectations, downgrade removes the table and enums

#### Scenario: Integration tests cover task status endpoint

- **WHEN** integration tests are executed
- **THEN** tests SHALL verify: `GET /api/admin/tasks/{id}` returns 200 with correct fields after a source is uploaded, `GET /api/admin/tasks/{nonexistent}` returns 404

#### Scenario: Integration tests cover worker handler

- **WHEN** worker integration tests are executed with real committed data
- **THEN** tests SHALL verify: task transitions PENDING -> PROCESSING -> COMPLETE with correct timestamps and progress, source transitions PENDING -> PROCESSING -> READY, already-COMPLETE task is skipped by the worker, non-existent task_id does not cause an exception

---

## Test Coverage

### CI tests (deterministic)

The following stable behavior MUST be covered by CI tests before archive:

- **Enum values test**: verify `BackgroundTaskType` contains both INGESTION and BATCH_EMBEDDING.
- **BATCH_EMBEDDING task creation**: verify a BackgroundTask can be created with `task_type=BATCH_EMBEDDING` and `source_id=NULL`.
- **result_metadata structure**: verify BATCH_EMBEDDING tasks store `source_ids`, `knowledge_base_id`, `snapshot_id` in `result_metadata`.
- **ALTER TYPE migration**: verify the Alembic migration successfully adds `BATCH_EMBEDDING` to the native enum type.
- **Existing tests updated**: `test_task_status.py` SHALL include `BATCH_EMBEDDING` in expected `BackgroundTaskType` members.
