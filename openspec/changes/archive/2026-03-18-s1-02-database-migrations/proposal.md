## Story

**S1-02: Database + migrations** (Phase 1: Bootstrap)

Verification criteria:
- `alembic upgrade head` → all tables created
- Basic CRUD agent via tests

## Why

The backend has a running FastAPI app with a raw asyncpg pool but no ORM, no models, and no migration system. Every subsequent story (ingestion, snapshots, chat, audit) depends on having a well-defined database schema. Without it, no business logic can be persisted or tested against real data structures.

## What Changes

- Replace raw `asyncpg.create_pool()` with SQLAlchemy 2.x async engine and session management
- Add Alembic for database migrations with async-aware configuration
- Create all 12 base tables: agents, sources, documents, document_versions, chunks, knowledge_snapshots, sessions, messages, audit_logs, embedding_profiles, batch_jobs, catalog_items
- Add tenant-ready fields (owner_id, agent_id, knowledge_base_id) as architectural provisions
- Seed a default agent via Alembic data migration
- Update Dockerfile to include migrations and entrypoint script
- Add integration tests with Testcontainers (real PostgreSQL)

## Capabilities

### New Capabilities

- `database-schema`: SQLAlchemy models for all 12 base tables, organized by system contours (core, knowledge, dialogue, operations). Includes mixins, enums, relationships, and tenant-ready fields.
- `migration-system`: Alembic configuration, initial schema migration, seed data migration, Docker entrypoint integration, and local development workflow.

### Modified Capabilities

_(none — no existing specs to modify)_

## Impact

- **Backend code:** `app/main.py` (lifespan rewrite), `app/api/health.py` (`/health` stays liveness-only; `/ready` gains DB probe via async session), new `app/db/` package
- **Dependencies:** add `sqlalchemy[asyncio]`, `alembic`; dev: `testcontainers[postgres]`
- **Infrastructure:** Dockerfile changes (COPY migrations, entrypoint), docker-compose.yml (api command update)
- **Existing behavior:** `/health` remains liveness-only (no DB probe). DB readiness check (`SELECT 1` via SQLAlchemy session) added to `/ready` endpoint
