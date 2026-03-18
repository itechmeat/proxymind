## 1. Dependencies and Configuration

- [x] 1.1 Add `sqlalchemy[asyncio]` (>= 2.0.48) and `alembic` (>= 1.18.4) to `pyproject.toml` main dependencies
- [x] 1.2 Add `testcontainers[postgres]` to `pyproject.toml` dev dependencies
- [x] 1.3 Run `uv lock` and verify all versions meet minimums from `docs/spec.md`

## 2. Database Infrastructure (`app/db/`)

- [x] 2.1 Create `app/db/__init__.py`
- [x] 2.2 Create `app/db/base.py` — DeclarativeBase with `type_annotation_map`, and five mixins: PrimaryKeyMixin (UUID v7), TimestampMixin, TenantMixin, KnowledgeScopeMixin, SoftDeleteMixin
- [x] 2.3 Create `app/db/engine.py` — async engine creation function and `async_sessionmaker` factory
- [x] 2.4 Create `app/db/session.py` — `get_session` FastAPI dependency yielding AsyncSession

## 3. Models by Contour

- [x] 3.1 Create `app/db/models/__init__.py` — re-export all 12 model classes
- [x] 3.2 Create `app/db/models/core.py` — Agent (PK + Timestamp + direct owner_id, no TenantMixin) and CatalogItem (PK + Tenant + Timestamp + SoftDelete)
- [x] 3.3 Create `app/db/models/knowledge.py` — Source, Document, DocumentVersion (no tenant fields), Chunk, KnowledgeSnapshot, EmbeddingProfile. Include all enums (source_type, source_status, document_status, processing_path, chunk_status, snapshot_status, task_type)
- [x] 3.4 Create `app/db/models/dialogue.py` — Session (with channel enum, JSONB channel_metadata, visitor identity fields) and Message (with role enum, status state machine, idempotency_key partial unique index, JSONB citations/content_type_spans, ARRAY source_ids)
- [x] 3.5 Create `app/db/models/operations.py` — AuditLog (append-only: created_at only, explicit agent_id, no TenantMixin) and BatchJob (explicit agent_id + knowledge_base_id, operation_type enum, batch_status enum)

## 4. Alembic Setup

- [x] 4.1 Run `alembic init migrations` from `backend/`, configure `alembic.ini` (no hardcoded URL)
- [x] 4.2 Configure `migrations/env.py` — async-aware with `run_async`, import Base.metadata and all models from `app.db.models`, read database_url from Settings
- [x] 4.3 Generate migration 001 (`alembic revision --autogenerate -m "initial_schema"`) then mandatory hand-edit: verify native PostgreSQL enum types, add partial unique index on idempotency_key (autogenerate won't create it), verify AuditLog has no `updated_at`, review all generated DDL before committing
- [x] 4.4 Create migration 002 (`alembic revision -m "seed_default_agent"`) — data migration inserting default agent with fixed UUID literal and default_knowledge_base_id UUID literal

## 5. Lifespan and Health Endpoint

- [x] 5.1 Update `app/main.py` lifespan — replace `asyncpg.create_pool()` with SQLAlchemy async engine creation; store engine and session factory in `app.state`; dispose engine on shutdown
- [x] 5.2 Update `app/api/health.py` — `/health` remains liveness-only (always returns ok, no DB probe). Move DB check (`text("SELECT 1")` via async session) to `/ready` endpoint. This preserves the existing `/health` contract and follows Kubernetes liveness/readiness semantics.
- [x] 5.3 Remove direct `asyncpg` imports from `app/main.py` (asyncpg remains as SQLAlchemy driver dependency)

## 6. Docker Integration

- [x] 6.1 Create `backend/entrypoint.sh` — `alembic upgrade head && exec uvicorn app.main:app` (api mode only, no worker mode)
- [x] 6.2 Update `backend/Dockerfile` — COPY `migrations/`, `alembic.ini`, `entrypoint.sh`; `RUN chmod +x entrypoint.sh`; update ENTRYPOINT/CMD to use entrypoint.sh
- [x] 6.3 Update `docker-compose.yml` — api service uses new entrypoint; NO worker service added (deferred to S2-01)
- [x] 6.4 Verify `docker-compose up` with empty volumes — all 12 tables created, `/health` returns 200, `/ready` returns 200

## 7. Integration Tests

- [x] 7.1 Create test infrastructure in `tests/conftest.py` — Testcontainers PostgreSQL fixture (session-scoped), alembic upgrade in fixture, `db_session` fixture (function-scoped with rollback), `seeded_agent` fixture
- [x] 7.2 Test: schema integrity — alembic upgrade head succeeds, all 12 tables exist (query `information_schema.tables`), seed agent present with expected UUID
- [x] 7.3 Test: CRUD Agent — create, read, update agent via session; verify timestamps auto-populate, UUID v7 PK generated
- [x] 7.4 Test: relationships — create agent → source → document → document_version → chunk chain; verify FK constraints (reject orphaned document)
- [x] 7.5 Test: soft delete — set `deleted_at` on source, verify record persists
- [x] 7.6 Test: enum constraints — attempt insert with invalid status value, verify rejection
- [x] 7.7 Test: partial unique index — two messages with same non-null idempotency_key rejected; two messages with NULL idempotency_key both succeed
- [x] 7.8 Test: `/ready` endpoint — returns success when DB is accessible; returns failure when DB is unreachable (mock engine to simulate connection error)

## 8. Final Verification

- [x] 8.1 Run full test suite (`pytest`), confirm all pass
- [x] 8.2 Run linters (`ruff check`, `ruff format --check`), confirm no issues
- [x] 8.3 Verify versions of packages added/changed in this story (sqlalchemy, alembic, asyncpg) meet minimums in `docs/spec.md`. Note: other spec.md dependencies (tenacity, arq, LiteLLM) are not in scope for S1-02 and will be added in their respective stories.
