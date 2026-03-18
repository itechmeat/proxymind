## ADDED Requirements

### Requirement: DeclarativeBase and composable mixins

The system SHALL define a single `DeclarativeBase` subclass in `app/db/base.py` serving as the foundation for all models. Five composable mixins SHALL be provided:

- **PrimaryKeyMixin** — `id` column as UUID with `default=uuid.uuid7` (Python 3.14 stdlib). Every model MUST use this mixin.
- **TimestampMixin** — `created_at` (server_default=now, not nullable) and `updated_at` (server_default=now, onupdate=now, not nullable).
- **TenantMixin** — `owner_id` (UUID, nullable, indexed) and `agent_id` (UUID, nullable, indexed). Provides tenant-ready scope without FK constraints.
- **KnowledgeScopeMixin** — `knowledge_base_id` (UUID, nullable, indexed). No FK constraint and no `knowledge_bases` table — this is an architectural provision for future multi-KB support.
- **SoftDeleteMixin** — `deleted_at` (DateTime, nullable). When set, the record is considered logically deleted.

Each model SHALL inherit only the mixins it needs. The mixin composition MUST be visible in the class declaration.

#### Scenario: PrimaryKeyMixin generates UUID v7

WHEN a new model instance is created without an explicit `id`
THEN the `id` field SHALL be auto-populated with a UUID v7 value
AND the UUID SHALL be time-ordered (lexicographic sort matches creation order).

#### Scenario: TimestampMixin sets timestamps automatically

WHEN a new record is inserted
THEN `created_at` and `updated_at` SHALL both be set to the current server time.

WHEN an existing record is updated
THEN `updated_at` SHALL be refreshed to the current server time
AND `created_at` SHALL remain unchanged.

#### Scenario: TenantMixin indexes are present

WHEN the schema is applied to the database
THEN the `owner_id` and `agent_id` columns on models using TenantMixin SHALL each have a B-tree index.

#### Scenario: KnowledgeScopeMixin has no foreign key

WHEN a model using KnowledgeScopeMixin is inspected
THEN `knowledge_base_id` SHALL be a plain UUID column with an index
AND there SHALL be no FK constraint referencing a `knowledge_bases` table.

#### Scenario: SoftDeleteMixin default state

WHEN a new record with SoftDeleteMixin is created
THEN `deleted_at` SHALL be NULL.

WHEN a record is soft-deleted by setting `deleted_at`
THEN the record SHALL remain in the database and be queryable.

---

### Requirement: Model organization by system contours

Models SHALL be organized into four files matching the architectural contours:

- `app/db/models/core.py` — Agent, CatalogItem
- `app/db/models/knowledge.py` — Source, Document, DocumentVersion, Chunk, KnowledgeSnapshot, EmbeddingProfile
- `app/db/models/dialogue.py` — Session, Message
- `app/db/models/operations.py` — AuditLog, BatchJob

`app/db/models/__init__.py` SHALL re-export all 12 model classes for convenient imports and to ensure Alembic autogenerate discovers all metadata.

#### Scenario: All 12 models are importable from the models package

WHEN `from app.db.models import Agent, CatalogItem, Source, Document, DocumentVersion, Chunk, KnowledgeSnapshot, EmbeddingProfile, Session, Message, AuditLog, BatchJob` is executed
THEN all 12 classes SHALL be importable without error.

#### Scenario: Each contour file contains only its designated models

WHEN `app/db/models/core.py` is inspected
THEN it SHALL define exactly Agent and CatalogItem and no other model classes.

---

### Requirement: Core contour models (Agent, CatalogItem)

**Agent** SHALL use PrimaryKeyMixin and TimestampMixin. It SHALL NOT use TenantMixin — instead, `owner_id` is defined directly on the model (since `agent_id` would be redundant with the PK). Agent SHALL include: `name` (String, not nullable), `description` (Text, nullable), `avatar_url` (String, nullable), `active_snapshot_id` (UUID, nullable), `default_knowledge_base_id` (UUID, not nullable, plain UUID with no FK in S1-02), `language` (String, not nullable), `timezone` (String, nullable).

**CatalogItem** SHALL use PrimaryKeyMixin, TenantMixin, TimestampMixin, and SoftDeleteMixin. It SHALL include: `name` (String, not nullable), `description` (Text, nullable), `item_type` (PostgreSQL enum: book/course/event/merch/other), `url` (String, nullable), `image_url` (String, nullable), `is_active` (Boolean, default true), `valid_from` (DateTime, nullable), `valid_until` (DateTime, nullable).

#### Scenario: Agent has direct owner_id without TenantMixin

WHEN the Agent model is inspected
THEN it SHALL have an `owner_id` column (UUID, nullable)
AND it SHALL NOT inherit TenantMixin.

#### Scenario: Agent default knowledge base has no foreign key in S1-02

WHEN the Agent model is inspected
THEN `default_knowledge_base_id` SHALL be a plain UUID column
AND there SHALL be no FK constraint referencing a `knowledge_bases` table.

#### Scenario: CatalogItem item_type enforces enum values

WHEN a CatalogItem is created with `item_type` set to an invalid value (not in book/course/event/merch/other)
THEN the database SHALL reject the insert with a constraint violation.

#### Scenario: CatalogItem soft delete

WHEN a CatalogItem's `deleted_at` is set to a timestamp
THEN the record SHALL remain in the database
AND `deleted_at` SHALL reflect the deletion time.

---

### Requirement: Knowledge contour models (Source, Document, DocumentVersion, Chunk, KnowledgeSnapshot, EmbeddingProfile)

**Source** SHALL use PrimaryKeyMixin, TenantMixin, KnowledgeScopeMixin, TimestampMixin, SoftDeleteMixin. Columns: `source_type` (enum: markdown/txt/pdf/docx/html/image/audio/video), `title` (String, not nullable), `description` (Text, nullable), `public_url` (String, nullable), `file_path` (String, not nullable), `file_size_bytes` (BigInteger, nullable), `mime_type` (String, nullable), `catalog_item_id` (UUID, nullable FK to CatalogItem), `status` (enum: pending/processing/ready/failed/deleted).

**Document** SHALL use PrimaryKeyMixin, TenantMixin, TimestampMixin. Columns: `source_id` (UUID FK to Source, not nullable), `title` (String, nullable), `status` (enum: pending/processing/ready/failed).

**DocumentVersion** SHALL use PrimaryKeyMixin and TimestampMixin only (no tenant fields — always accessed via Document FK). Columns: `document_id` (UUID FK to Document, not nullable), `version_number` (Integer, not nullable), `file_path` (String, not nullable), `processing_path` (enum: path_a/path_b), `status` (enum: pending/processing/ready/failed).

**Chunk** SHALL use PrimaryKeyMixin, TenantMixin, KnowledgeScopeMixin, TimestampMixin. Columns: `document_version_id` (UUID FK to DocumentVersion, not nullable), `snapshot_id` (UUID, not nullable), `source_id` (UUID, not nullable — denormalized for citation lookup), `chunk_index` (Integer, not nullable), `text_content` (Text, not nullable), `token_count` (Integer, nullable), `anchor_page` (Integer, nullable), `anchor_chapter` (String, nullable), `anchor_section` (String, nullable), `anchor_timecode` (String, nullable), `status` (enum: pending/indexed/failed).

**KnowledgeSnapshot** SHALL use PrimaryKeyMixin, TenantMixin, KnowledgeScopeMixin, TimestampMixin. Columns: `name` (String, not nullable), `description` (Text, nullable), `status` (enum: draft/published/active/archived), `published_at` (DateTime, nullable), `activated_at` (DateTime, nullable), `archived_at` (DateTime, nullable), `chunk_count` (Integer, default 0).

**EmbeddingProfile** SHALL use PrimaryKeyMixin and TimestampMixin. Columns: `model_name` (String, not nullable), `dimensions` (Integer, not nullable), `task_type` (enum: retrieval/query), `pipeline_version` (String, nullable), `knowledge_base_id` (UUID, nullable — direct field, not via mixin), `snapshot_id` (UUID, nullable). Note: in v1 (single-agent, single-KB), EmbeddingProfile is filtered by `knowledge_base_id` directly (the UUID is known from the seed agent). Full tenant derivation (agent/owner from a `knowledge_bases` FK) is deferred until the `knowledge_bases` table is introduced.

#### Scenario: Source FK to CatalogItem

WHEN a Source is created with a `catalog_item_id` referencing a valid CatalogItem
THEN the FK constraint SHALL be satisfied.

WHEN a Source is created with a `catalog_item_id` referencing a non-existent CatalogItem
THEN the database SHALL reject the insert.

#### Scenario: DocumentVersion omits tenant fields

WHEN the DocumentVersion table is inspected
THEN it SHALL NOT have `owner_id`, `agent_id`, or `knowledge_base_id` columns.

#### Scenario: Chunk carries denormalized source_id

WHEN a Chunk record is created
THEN it SHALL have a `source_id` column for fast citation lookup
AND this `source_id` is denormalized (not enforced as FK to Source).

#### Scenario: KnowledgeSnapshot lifecycle timestamps

WHEN a KnowledgeSnapshot transitions to published status
THEN `published_at` SHALL be set.

WHEN a KnowledgeSnapshot transitions to active status
THEN `activated_at` SHALL be set.

WHEN a KnowledgeSnapshot transitions to archived status
THEN `archived_at` SHALL be set.

---

### Requirement: Dialogue contour models (Session, Message)

**Session** SHALL use PrimaryKeyMixin, TenantMixin, TimestampMixin. Columns: `snapshot_id` (UUID, nullable), `status` (enum: active/closed), `message_count` (Integer, default 0), `channel` (enum: web/api/telegram/facebook/vk/instagram/tiktok, default web), `channel_metadata` (JSONB, nullable), `visitor_id` (UUID, nullable), `external_user_id` (String, nullable), `channel_connector` (String, nullable).

**Message** SHALL use PrimaryKeyMixin and TimestampMixin (no TenantMixin — scope inherited via Session FK). Columns: `session_id` (UUID FK to Session, not nullable), `role` (enum: user/assistant), `content` (Text, not nullable), `status` (enum: received/streaming/complete/partial/failed), `idempotency_key` (String, nullable), `snapshot_id` (UUID, nullable), `source_ids` (ARRAY of UUID, nullable), `citations` (JSONB, nullable), `content_type_spans` (JSONB, nullable), `token_count_prompt` (Integer, nullable), `token_count_completion` (Integer, nullable), `model_name` (String, nullable), `config_commit_hash` (String, nullable), `config_content_hash` (String, nullable).

#### Scenario: Session defaults to web channel

WHEN a Session is created without specifying a `channel`
THEN the `channel` column SHALL default to `web`.

#### Scenario: Message inherits scope via Session FK

WHEN the Message table is inspected
THEN it SHALL NOT have `owner_id` or `agent_id` columns
AND it SHALL have a `session_id` FK to Session.

#### Scenario: Message queries by session are indexed

WHEN the Message table is inspected
THEN it SHALL have a B-tree index on `session_id`
AND that index SHALL be separate from the partial unique index on `idempotency_key`.

#### Scenario: Message JSONB fields accept structured data

WHEN a Message is created with `citations` set to `[{"source_id": "...", "source_title": "...", "anchor": "...", "url": "..."}]`
THEN the value SHALL be stored as JSONB and retrievable with the same structure.

---

### Requirement: Operations contour models (AuditLog, BatchJob)

**AuditLog** SHALL use PrimaryKeyMixin and `created_at` only (no `updated_at` — append-only). It SHALL NOT use TenantMixin or SoftDeleteMixin. Columns: `agent_id` (UUID, not nullable), `session_id` (UUID, nullable), `message_id` (UUID, nullable), `snapshot_id` (UUID, nullable), `source_ids` (ARRAY of UUID, nullable), `config_commit_hash` (String, nullable), `config_content_hash` (String, nullable), `model_name` (String, nullable), `token_count_prompt` (Integer, nullable), `token_count_completion` (Integer, nullable), `retrieval_chunks_count` (Integer, nullable), `latency_ms` (Integer, nullable).

**BatchJob** SHALL use PrimaryKeyMixin and TimestampMixin. It SHALL NOT use TenantMixin — instead, `agent_id` and `knowledge_base_id` are explicit direct columns. Columns: `agent_id` (UUID, not nullable), `knowledge_base_id` (UUID, nullable), `task_id` (String, nullable), `batch_operation_name` (String, nullable), `operation_type` (enum: embedding/text_extraction/reindex/eval), `status` (enum: pending/processing/complete/failed/cancelled), `item_count` (Integer, nullable), `processed_count` (Integer, nullable), `error_message` (Text, nullable), `started_at` (DateTime, nullable), `completed_at` (DateTime, nullable).

#### Scenario: AuditLog is append-only

WHEN the AuditLog model is inspected
THEN it SHALL have a `created_at` column
AND it SHALL NOT have an `updated_at` column.

#### Scenario: AuditLog has no soft delete

WHEN the AuditLog table is inspected
THEN it SHALL NOT have a `deleted_at` column.

#### Scenario: BatchJob uses explicit tenant fields

WHEN the BatchJob model is inspected
THEN it SHALL have `agent_id` and `knowledge_base_id` as direct columns
AND it SHALL NOT inherit TenantMixin.

---

### Requirement: PostgreSQL native enum types

All enum columns SHALL use PostgreSQL native enums (`native_enum=True` in SQLAlchemy). Each distinct set of enum values SHALL be a named PostgreSQL enum type (e.g., `source_type_enum`, `source_status_enum`, `message_role_enum`, etc.). Enum type names MUST be unique across the schema.

#### Scenario: Enum types are created as PostgreSQL native enums

WHEN the schema is applied
THEN running a query against `pg_type` for each defined enum type SHALL return a result
AND the enum type SHALL contain exactly the values defined in the model.

#### Scenario: Invalid enum value is rejected

WHEN an INSERT is attempted with a value not in the enum definition
THEN PostgreSQL SHALL reject it with a data type error.

---

### Requirement: Relationships and FK constraints

Models SHALL define SQLAlchemy `relationship()` declarations for navigable associations. The following FK constraints MUST exist:

- Document.source_id -> Source.id
- DocumentVersion.document_id -> Document.id
- Chunk.document_version_id -> DocumentVersion.id
- Source.catalog_item_id -> CatalogItem.id
- Message.session_id -> Session.id

Non-FK UUID references (e.g., Chunk.snapshot_id, Session.snapshot_id, Agent.active_snapshot_id) SHALL remain as plain UUID columns without FK constraints to avoid circular dependency and allow cross-store references.

#### Scenario: Cascading relationship from Source to Documents

WHEN a Source is queried
THEN its `documents` relationship SHALL return all associated Document records.

#### Scenario: FK constraint prevents orphaned documents

WHEN a Document is created with a `source_id` referencing a non-existent Source
THEN the database SHALL reject the insert with a foreign key violation.

---

### Requirement: Index policies

A partial unique index SHALL be created on `Message.idempotency_key` with the condition `WHERE idempotency_key IS NOT NULL`. This allows multiple NULL values while enforcing uniqueness for non-null keys.

The soft delete index policy SHALL be established: when a soft-deletable model gains a unique business key in the future, it MUST use `UNIQUE WHERE deleted_at IS NULL`. No such unique business keys exist in v1, but the policy is documented in the codebase.

#### Scenario: Partial unique index on idempotency_key

WHEN two Messages are created with the same non-null `idempotency_key`
THEN the database SHALL reject the second insert with a unique constraint violation.

WHEN two Messages are created with `idempotency_key` set to NULL
THEN both inserts SHALL succeed.

---

### Requirement: JSONB field stability contract

The following JSONB fields are defined in the full schema upfront with a stable top-level structure:

- `Message.citations` — `[{source_id, source_title, anchor, url}]`
- `Message.content_type_spans` — `[{start, end, type}]`
- `Session.channel_metadata` — connector-specific, schema-free by design

Internal structure MAY evolve through application-level changes without requiring schema migration. The database column type SHALL remain JSONB.

#### Scenario: JSONB fields store and retrieve structured data

WHEN a Message is saved with `citations` as a JSON array of objects
THEN the same structure SHALL be retrievable via a SQLAlchemy query without data loss.

---

### Requirement: Tenant-ready scope matrix compliance

Models SHALL comply with the scope matrix defined in the design spec:

1. Tables that are frequently filtered in isolation (Source, Session, KnowledgeSnapshot, Chunk) SHALL carry direct tenant fields via mixins.
2. Tables always accessed through a parent FK (DocumentVersion, Message) SHALL omit tenant fields — scope is recoverable through the FK chain.
3. Operational tables (AuditLog, BatchJob) SHALL carry only the fields needed for their specific query patterns using explicit columns, not mixins.
4. Agent SHALL define `owner_id` directly (not via TenantMixin) since `agent_id` would be redundant with the PK.

#### Scenario: Scope matrix for knowledge contour

WHEN the Chunk model is inspected
THEN it SHALL have `owner_id`, `agent_id` (from TenantMixin) and `knowledge_base_id` (from KnowledgeScopeMixin).

WHEN the DocumentVersion model is inspected
THEN it SHALL NOT have `owner_id`, `agent_id`, or `knowledge_base_id`.

#### Scenario: Scope matrix for operational contour

WHEN the AuditLog model is inspected
THEN it SHALL have `agent_id` as a direct column
AND it SHALL NOT have `owner_id` or `knowledge_base_id`.

---

### Requirement: Async engine and session management

The application SHALL replace the raw `asyncpg.create_pool()` with SQLAlchemy `create_async_engine` and `async_sessionmaker`. The module `app/db/engine.py` SHALL provide engine creation and session factory functions. The module `app/db/session.py` SHALL provide a FastAPI dependency (`get_session`) that yields an `AsyncSession`.

During application lifespan startup, the async engine SHALL be created and stored in `app.state.engine`, and the session factory SHALL be stored in `app.state.async_session`. During shutdown, `engine.dispose()` SHALL be called.

The `/health` endpoint SHALL remain a liveness-only check — it MUST always return a successful status without probing external dependencies. The DB readiness check (`text("SELECT 1")` via async session) SHALL be placed on the `/ready` endpoint. This preserves the existing `/health` contract and follows standard Kubernetes liveness/readiness semantics.

#### Scenario: Health endpoint remains liveness-only

WHEN `GET /health` is called
THEN it SHALL return a successful status regardless of database connectivity
AND it SHALL NOT execute any database queries.

#### Scenario: Ready endpoint checks database connectivity

WHEN `GET /ready` is called while the database is accessible
THEN the readiness check SHALL execute `SELECT 1` via an async SQLAlchemy session
AND return a successful readiness status.

WHEN `GET /ready` is called while the database is unreachable
THEN the readiness check SHALL return a failure status.

#### Scenario: Engine disposal on shutdown

WHEN the application shuts down
THEN `engine.dispose()` SHALL be called to release all database connections.
