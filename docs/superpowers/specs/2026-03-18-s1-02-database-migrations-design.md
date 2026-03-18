# S1-02: Database + Migrations — Design Spec

## Story

> SQLAlchemy 2.x, Alembic, asyncpg. All base tables: agents, sources, documents, document_versions, chunks (metadata), knowledge_snapshots, sessions, messages, audit_logs, embedding_profiles, batch_jobs, catalog_items. Tenant-ready fields.

**Outcome:** DB schema is created automatically on container startup (via Docker entrypoint). Locally, `alembic upgrade head` is a manual step.
**Verification:** `docker-compose up` → api service starts with all tables created; `alembic upgrade head` on clean DB → all tables; basic CRUD agent via tests.

## Key Decisions

### 1. Replace raw asyncpg with SQLAlchemy async engine

**Decision:** Remove the raw `asyncpg.create_pool()` from `main.py` lifespan, replace with `create_async_engine` + `async_sessionmaker`.

**Why:** SQLAlchemy uses asyncpg under the hood. Keeping both means two connection pools to the same DB, confusion about which to use, and harder connection monitoring. Health endpoint trivially migrates to `text("SELECT 1")` through a session.

### 2. Models organized by system contours

**Decision:** Group models into 4 files matching the architectural contours.

- `app/db/models/core.py` — Agent, CatalogItem
- `app/db/models/knowledge.py` — Source, Document, DocumentVersion, Chunk, KnowledgeSnapshot, EmbeddingProfile
- `app/db/models/dialogue.py` — Session, Message
- `app/db/models/operations.py` — AuditLog, BatchJob
- `app/db/models/__init__.py` — re-exports all models

**Why:** Reflects the three system circuits from architecture.md (dialogue / knowledge / operational) plus core entities. 3-4 files of ~100-150 lines each is a comfortable size. Avoids both a monolithic file and 12+ tiny files with circular import risks. Each contour grows independently as new stories land.

### 3. Granular mixins for cross-cutting fields

**Decision:** Five composable mixins: `PrimaryKeyMixin`, `TimestampMixin`, `TenantMixin`, `KnowledgeScopeMixin`, `SoftDeleteMixin`. Each model inherits only what it needs.

**Why:** DRY for fields that appear in most models. Mixin composition is explicit — reading a model class declaration tells you exactly what capabilities it has. Changing an index or constraint in one place affects all models consistently.

- `PrimaryKeyMixin` — `id` as UUID v7
- `TimestampMixin` — `created_at`, `updated_at`
- `TenantMixin` — `owner_id`, `agent_id` (both indexed)
- `KnowledgeScopeMixin` — `knowledge_base_id` (indexed)
- `SoftDeleteMixin` — `deleted_at` (nullable)

### 4. UUID v7 for all primary keys

**Decision:** All PKs use `uuid.uuid7()` (Python 3.14 stdlib).

**Why:** Time-ordered UUIDs solve the B-tree fragmentation problem of UUID v4. Globally unique — safe for future sharding/multi-tenancy. No information leakage (unlike auto-increment integers). Python 3.14 has native `uuid.uuid7()` — no third-party library needed.

**UUID v8 considered and rejected:** v8 is a "build your own" format with custom parameters, not time-ordered, not cryptographically secure. It serves niche use cases that don't apply here.

### 5. Migrations via Docker entrypoint script

**Decision:** `alembic upgrade head` runs in the Docker entrypoint before `uvicorn` starts. Not inside application lifespan.

**Why:** Clean separation — migrations are an infrastructure concern, not application logic. No race conditions (unlike running migrations in lifespan when multiple replicas start). Standard pattern: `alembic upgrade head && exec uvicorn ...`.

### 6. Seed agent via Alembic data migration

**Decision:** A second Alembic migration (data migration) INSERTs a default agent with a fixed UUID literal constant (not necessarily v7). The UUID v7 `default=uuid.uuid7` rule applies to runtime-generated PKs; the seed agent is a bootstrap exception with a hardcoded UUID literal that is the same across all environments.

**Why:** The default agent is not test data — it's the required initial state of the system (one instance = one twin). Data migration in Alembic is reproducible and runs exactly once. A fixed UUID literal (e.g., `00000000-0000-0000-0000-000000000001` or any chosen constant) ensures consistency across environments. Using a plain UUID literal avoids the semantic contradiction of a "deterministic UUID v7" — v7 is inherently time-based, so a fixed constant should not claim to be v7.

### 7. Full schema upfront

**Decision:** All 12 tables with all columns described in spec/architecture/rag docs, including fields needed for later phases (SSE state machine, citation JSONB, batch operation tracking, etc.).

**Why:** The story says "all base tables" — tables are created completely, not as stubs. Since columns are known from the spec, defining them now avoids ALTER TABLE migrations in every future story. Phase 2-4 stories focus on logic, not schema changes. If a field definition needs to change later, that's a normal migration regardless.

### 8. Testcontainers with real PostgreSQL

**Decision:** Integration tests use `testcontainers[postgres]` to spin up an ephemeral PostgreSQL container. Tests run `alembic upgrade head` to verify the full migration chain.

**Why:** The story is entirely about the database layer — testing without a real DB tests nothing. SQLite is not viable (no UUID native type, ARRAY, JSONB). Mocks don't validate schema, constraints, or migrations. Docker is already required for the project. Testcontainers is the standard Python approach for database integration tests.

### 9. knowledge_base_id as field without FK

**Decision:** `knowledge_base_id` is a UUID field in knowledge-contour models, without a FK constraint and without a `knowledge_bases` table.

**Why:** The plan lists exactly 12 tables — `knowledge_bases` is not among them. Tenant-ready is an architectural provision, not a full feature. The field exists for future use; the FK and table will be added in a single migration when multi-KB is needed. Default value is generated at seed time and used by all models.

## File Structure

All paths relative to `backend/`:

```
backend/
  app/db/
    __init__.py
    engine.py              # async engine, session factory
    base.py                # DeclarativeBase, all mixins
    session.py             # get_session FastAPI dependency
    models/
      __init__.py           # re-exports all models
      core.py               # Agent, CatalogItem
      knowledge.py          # Source, Document, DocumentVersion, Chunk,
                            # KnowledgeSnapshot, EmbeddingProfile
      dialogue.py           # Session, Message
      operations.py         # AuditLog, BatchJob
  migrations/               # Alembic migrations directory
    env.py                  # async-aware, imports Base.metadata + all models
    versions/
      001_initial_schema.py     # all 12 tables
      002_seed_agent.py         # default agent insert
  alembic.ini
  entrypoint.sh             # alembic upgrade head && exec uvicorn/arq
```

## Models

### Core Contour

**Agent** — central entity, one twin = one agent.
- PK, TimestampMixin. Agent does NOT use TenantMixin — instead, `owner_id` is defined directly on the model (agent_id is redundant since the PK itself is the agent identity)
- name, description, avatar_url (MinIO path)
- `active_snapshot_id` — nullable UUID, points to the currently active snapshot. Single source of truth for "which snapshot answers"
- `default_knowledge_base_id` — fixed UUID from seed
- language (for BM25 and UI), timezone

**CatalogItem** — product/service of the prototype (book, course, merch, event).
- PK, TenantMixin, TimestampMixin, SoftDeleteMixin
- name, description, item_type (enum: book/course/event/merch/other), url, image_url
- is_active — visible for recommendations
- valid_from, valid_until (nullable) — for time-bound events

### Knowledge Contour

**Source** — where data came from. Entry point to the ingestion pipeline.
- PK, TenantMixin, KnowledgeScopeMixin, TimestampMixin, SoftDeleteMixin
- source_type (enum: markdown/txt/pdf/docx/html/image/audio/video)
- title, description
- public_url (nullable) — only for publicly accessible materials; determines citation format (link vs text)
- file_path (MinIO path), file_size_bytes, mime_type
- catalog_item_id — nullable FK to CatalogItem
- status (enum: pending/processing/ready/failed/deleted)

**Document** — a specific content unit within a source (1:1 in v1).
- PK, TenantMixin, TimestampMixin
- source_id FK
- title
- status (enum: pending/processing/ready/failed)

**DocumentVersion** — version of a document after update. Enables reindexing without losing previous version. Omits tenant fields — always accessed via its parent Document, which carries tenant scope.
- PK, TimestampMixin
- document_id FK
- version_number — auto-increment per document
- file_path — MinIO path to this specific version
- processing_path (enum: path_a/path_b)
- status

**Chunk** — chunk metadata in PostgreSQL. Vectors live in Qdrant.
- PK, TenantMixin, KnowledgeScopeMixin, TimestampMixin
- document_version_id FK
- snapshot_id — links chunk to draft snapshot at indexing time
- source_id — denormalized for fast citation lookup
- chunk_index — ordinal position in document
- text_content — chunk text (passed to LLM during retrieval)
- token_count — for context budget management
- Anchor metadata (all nullable): anchor_page, anchor_chapter, anchor_section, anchor_timecode
- status (enum: pending/indexed/failed)

**KnowledgeSnapshot** — a published set of versions the twin responds from.
- PK, TenantMixin, KnowledgeScopeMixin, TimestampMixin
- name, description
- status (enum: draft/published/active/archived)
- published_at, activated_at, archived_at (nullable timestamps for lifecycle transitions)
- chunk_count — denormalized counter for UI

**EmbeddingProfile** — metadata of an embedding pass. Tracks which model/settings produced vectors.
- PK, TimestampMixin
- model_name, dimensions, task_type (enum: retrieval/query)
- pipeline_version
- knowledge_base_id, snapshot_id (nullable)

### Dialogue Contour

**Session** — conversation container.
- PK, TenantMixin, TimestampMixin
- snapshot_id — which snapshot was active at session creation (audit)
- status (enum: active/closed)
- message_count — denormalized counter
- channel (enum: web/api/telegram/facebook/vk/instagram/tiktok) — defaults to web
- channel_metadata — JSONB, nullable, for connector-specific data
- Visitor identity provision: visitor_id (nullable UUID), external_user_id (nullable string), channel_connector (nullable string). Pair (channel_connector, external_user_id) is the stable lookup key for implicit provisioning per spec. All nullable — web chat is anonymous.

**Message** — individual message in a session.
- PK, TimestampMixin
- session_id FK
- role (enum: user/assistant)
- content — full text (Markdown for assistant)
- status (enum: received/streaming/complete/partial/failed) — state machine per architecture.md
- idempotency_key — nullable unique string, prevents duplicates on retry
- snapshot_id — which snapshot was used for this response (assistant messages)
- source_ids — ARRAY of UUID, sources used in the response
- citations — JSONB, array of {source_id, source_title, anchor, url}
- content_type_spans — JSONB, nullable, [{start, end, type: "fact"|"inference"|"promo"}]
- token_count_prompt, token_count_completion — cost tracking
- model_name — which LLM model generated the response
- config_commit_hash, config_content_hash — reproducibility (denormalized from audit)

### Operations Contour

**AuditLog** — append-only record of every twin response.
- PK, created_at only (no updated_at — append-only)
- agent_id, session_id, message_id — FK links for tracing
- snapshot_id
- source_ids — ARRAY of UUID
- config_commit_hash, config_content_hash
- model_name
- token_count_prompt, token_count_completion
- retrieval_chunks_count
- latency_ms

No tenant mixin (agent_id is explicit), no soft delete (audit records are immutable).

**BatchJob** — Gemini Batch API operation tracking. Uses explicit `agent_id` and `knowledge_base_id` fields (no mixin) for consistency with AuditLog's pattern — operational tables use explicit fields since they don't need the full tenant mixin.
- PK, TimestampMixin
- agent_id, knowledge_base_id
- task_id — internal arq job reference
- batch_operation_name — Gemini API operation name, key for deduplication guard
- operation_type (enum: embedding/text_extraction/reindex/eval)
- status (enum: pending/processing/complete/failed/cancelled)
- item_count, processed_count — progress tracking
- error_message (nullable)
- started_at, completed_at (nullable)

## Tenant-Ready Scope Matrix

Spec requires `owner_id`, `agent_id`, `knowledge_base_id`, `published_version_id` in data structures. Not every table carries all four fields — the rule is: **direct scope fields where needed for filtering/RLS, inherited scope via FK where join is acceptable.**

| Table | owner_id | agent_id | knowledge_base_id | snapshot_id | Scope strategy |
|-------|----------|----------|--------------------|-------------|----------------|
| Agent | direct | IS the PK | direct (default_kb) | direct (active) | Root entity |
| CatalogItem | via mixin | via mixin | — | — | Direct scope (top-level entity) |
| Source | via mixin | via mixin | via mixin | — | Direct scope (entry point for ingestion) |
| Document | via mixin | via mixin | — | — | Direct scope; kb inherited from Source FK |
| DocumentVersion | — | — | — | — | Inherited via Document FK (always accessed through parent) |
| Chunk | via mixin | via mixin | via mixin | direct | Direct scope (must be filterable by all in Qdrant payload) |
| KnowledgeSnapshot | via mixin | via mixin | via mixin | IS the PK | Direct scope |
| EmbeddingProfile | — | — | direct | direct (nullable) | Scoped by kb + snapshot; agent/owner derived from kb |
| Session | via mixin | via mixin | — | direct | Direct scope (agent_id for routing, snapshot for audit) |
| Message | — | — | — | direct (nullable) | Inherited via Session FK; agent/owner recoverable through session |
| AuditLog | — | direct | — | direct | Minimal direct (agent_id + snapshot); rest via session/message FK |
| BatchJob | — | direct | direct | — | Minimal direct (agent_id + kb for operational queries) |

**Rules:**
1. Tables that serve as Qdrant payload sources (Chunk) or are frequently filtered in isolation (Source, Session, KnowledgeSnapshot) carry direct tenant fields via mixins.
2. Tables always accessed through a parent FK (DocumentVersion → Document, Message → Session) omit tenant fields to avoid redundancy. Scope is recoverable through the FK chain.
3. Operational tables (AuditLog, BatchJob) carry only the fields needed for their specific query patterns — `agent_id` for partitioning, `snapshot_id`/`knowledge_base_id` for operational joins.
4. If future RLS requirements demand direct scope on currently-inherited tables, a migration adds the fields — this is a deliberate trade-off, not an oversight.

## Index Policies

### Partial unique indexes for nullable unique fields

- `idempotency_key` on Message: `UNIQUE WHERE idempotency_key IS NOT NULL`. Standard PostgreSQL pattern — multiple NULLs are allowed, but non-null values must be unique. Prevents dialect-dependent behavior.

### Soft delete and unique constraints

Policy: when a soft-deletable model gains a unique business key in the future, use `UNIQUE WHERE deleted_at IS NULL`. This allows re-creation of a "deleted" entity with the same business key without conflicting with the soft-deleted record. No such unique business keys exist in v1, but the policy is established now.

### JSONB fields stability note

The following JSONB fields are included in full schema upfront. Their top-level structure is defined by spec.md/architecture.md and is considered **stable-by-design**. Internal structure may evolve through application-level changes without requiring schema migration:
- `citations` (Message) — `[{source_id, source_title, anchor, url}]`
- `content_type_spans` (Message) — `[{start, end, type}]`
- `channel_metadata` (Session) — connector-specific, schema-free by design

## Alembic Configuration

- `alembic.ini` in `backend/`, `sqlalchemy.url` read from environment (not hardcoded)
- `migrations/env.py` — async-aware using `run_async` with the async engine (same `postgresql+asyncpg://` URL). Imports `Base.metadata` and all models for autogenerate. Reads `database_url` from Settings. No separate sync URL needed — Alembic's async recipe handles the connection lifecycle
- Migration 001: full schema (all 12 tables, all PostgreSQL enum types with `native_enum=True`)
- Migration 002: seed default agent with fixed UUID literal constant

## Docker and Runtime Changes

### Dockerfile changes (required)

The existing Dockerfile currently copies only `app/` and starts uvicorn directly. This story must update it:
- COPY `migrations/`, `alembic.ini`, `entrypoint.sh` into the image
- `RUN chmod +x entrypoint.sh`
- Change `CMD`/`ENTRYPOINT` to use `entrypoint.sh` instead of direct uvicorn invocation

### entrypoint.sh

`backend/entrypoint.sh`:
- `alembic upgrade head && exec uvicorn app.main:app`
- The entrypoint is designed for the api service only in S1-02. Worker mode will be added in S2-01 when the arq worker runtime is introduced.

### docker-compose.yml changes

- **api service:** update `command` to use `entrypoint.sh` (or rely on Dockerfile ENTRYPOINT)
- **worker service:** NOT added in S1-02. The worker runtime (`app.workers.main.WorkerSettings`) does not exist yet — it appears in S2-01 (ingestion task queue). Adding a worker service here would break `docker-compose up`. The entrypoint.sh will gain worker mode support when the worker is introduced.

### Local development (outside Docker)

For local development without Docker:
- Run `alembic upgrade head` manually before starting the app
- Start uvicorn directly: `uvicorn app.main:app --reload`
- PostgreSQL must be accessible (either via Docker or local install)
- The outcome "DB schema is created automatically on startup" applies to the containerized path; locally, `alembic upgrade head` is a manual prerequisite

## Lifespan Changes

- Remove `asyncpg.create_pool()` from `main.py`
- Create SQLAlchemy async engine in lifespan, store in `app.state.engine`
- Session factory stored in `app.state.async_session`
- Shutdown: `await engine.dispose()`
- `/health` remains liveness-only (always ok, no DB probe). DB readiness check (`SELECT 1` via async session) added to `/ready` endpoint

## Config Changes

- No sync URL needed — Alembic env.py uses `run_async` with the existing async `database_url`

## Dependencies

Add to `pyproject.toml`:
- Main: `sqlalchemy[asyncio]` (>= 2.0.48), `alembic` (>= 1.18.4)
- Dev: `testcontainers[postgres]`

Note: `asyncpg` (>= 0.31.0) remains in dependencies as the SQLAlchemy async driver; only the direct pool usage is removed.

## Testing Strategy

### Infrastructure

- Testcontainers spins up an ephemeral PostgreSQL container (session-scoped fixture)
- Fixture runs `alembic upgrade head` on clean DB — verifies full migration chain

### What is tested

1. **Schema integrity** — alembic upgrade head succeeds, all 12 tables exist, seed agent is present
2. **CRUD Agent** — create, read, update via SQLAlchemy session. Verify tenant-ready fields, timestamps, UUID v7 PK
3. **Relationships** — create agent -> source -> document -> chunk chain. Verify FK constraints
4. **Soft delete** — deleting a source sets `deleted_at`, record remains
5. **Enum constraints** — invalid status is rejected by PostgreSQL

### What is NOT tested (out of scope)

- Business logic (no services yet)
- API endpoints for models (S2-01+)
- Qdrant, MinIO, Redis integrations

### Test fixtures

- `db_engine` (session scope) — testcontainers postgres + alembic upgrade
- `db_session` (function scope) — AsyncSession with rollback after each test
- `seeded_agent` (function scope) — loads seed agent from DB

## Skills used

- superpowers:brainstorming

## Docs used

- docs/plan.md
- docs/spec.md
- docs/architecture.md
- docs/rag.md
