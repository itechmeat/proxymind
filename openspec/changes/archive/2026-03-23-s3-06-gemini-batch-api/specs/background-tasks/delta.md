## MODIFIED Requirements

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

## Test Coverage

### CI tests (deterministic)

The following stable behavior MUST be covered by CI tests before archive:

- **Enum values test**: verify `BackgroundTaskType` contains both INGESTION and BATCH_EMBEDDING.
- **BATCH_EMBEDDING task creation**: verify a BackgroundTask can be created with `task_type=BATCH_EMBEDDING` and `source_id=NULL`.
- **result_metadata structure**: verify BATCH_EMBEDDING tasks store `source_ids`, `knowledge_base_id`, `snapshot_id` in `result_metadata`.
- **ALTER TYPE migration**: verify the Alembic migration successfully adds `BATCH_EMBEDDING` to the native enum type.
- **Existing tests updated**: `test_task_status.py` SHALL include `BATCH_EMBEDDING` in expected `BackgroundTaskType` members.
