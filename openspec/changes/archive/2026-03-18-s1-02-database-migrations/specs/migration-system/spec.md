## ADDED Requirements

### Requirement: Alembic async-aware configuration

Alembic SHALL be configured in `backend/` with `alembic.ini` and `migrations/env.py`. The `sqlalchemy.url` in `alembic.ini` SHALL NOT contain a hardcoded database URL — it SHALL be read from the environment (via the application's Settings).

`migrations/env.py` SHALL use Alembic's async recipe (`run_async`) with the existing `postgresql+asyncpg://` URL from Settings. No separate sync URL is needed. The env.py SHALL import `Base.metadata` and all models (via `app.db.models`) to ensure autogenerate discovers the complete schema.

The migrations directory SHALL be `backend/migrations/` with versions in `backend/migrations/versions/`.

#### Scenario: Alembic reads database URL from environment

WHEN `alembic upgrade head` is run
THEN Alembic SHALL obtain the database URL from the application's Settings (environment variable)
AND it SHALL NOT use a hardcoded URL from `alembic.ini`.

#### Scenario: Alembic env.py imports all models

WHEN Alembic autogenerate is invoked
THEN it SHALL detect all 12 tables because `migrations/env.py` imports the models package that re-exports all model classes.

#### Scenario: Alembic uses async engine

WHEN a migration is executed
THEN Alembic SHALL connect via the `postgresql+asyncpg://` driver using `run_async`
AND no separate synchronous database URL SHALL be required.

---

### Requirement: Initial schema migration (001)

The first migration (`001_initial_schema.py`) SHALL create all 12 tables in a single migration: `agents`, `catalog_items`, `sources`, `documents`, `document_versions`, `chunks`, `knowledge_snapshots`, `embedding_profiles`, `sessions`, `messages`, `audit_logs`, `batch_jobs`.

This migration SHALL also create all PostgreSQL native enum types used by the models. Tables SHALL be created with all columns, constraints, indexes, and FK relationships as defined by the database-schema capability.

The downgrade path SHALL drop all 12 tables and all enum types.

#### Scenario: Migration 001 creates all tables

WHEN `alembic upgrade head` is run on an empty database
THEN all 12 tables SHALL exist in the database.

#### Scenario: Migration 001 creates enum types

WHEN `alembic upgrade head` is run on an empty database
THEN all PostgreSQL native enum types (e.g., source_type_enum, message_role_enum, snapshot_status_enum, etc.) SHALL exist in `pg_type`.

#### Scenario: Migration 001 creates indexes

WHEN `alembic upgrade head` is run on an empty database
THEN the partial unique index on `messages.idempotency_key` (WHERE idempotency_key IS NOT NULL) SHALL exist
AND a B-tree index on `messages.session_id` SHALL exist
AND B-tree indexes on tenant fields (`owner_id`, `agent_id`) SHALL exist on tables that use TenantMixin.

#### Scenario: Migration 001 downgrade removes all tables

WHEN `alembic downgrade base` is run after a successful upgrade
THEN all 12 tables SHALL be dropped
AND all enum types SHALL be dropped.

---

### Requirement: Seed data migration (002)

The second migration (`002_seed_default_agent.py`) SHALL be a data migration that inserts a default agent record. The agent SHALL use a fixed UUID literal constant (e.g., `00000000-0000-0000-0000-000000000001` or another chosen constant) — NOT a UUID v7. This is a bootstrap exception: the seed agent has the same identity across all environments.

The seed agent SHALL include a `default_knowledge_base_id` (also a fixed UUID literal constant). In S1-02 this column is a plain UUID and SHALL NOT have an FK constraint because the `knowledge_bases` table does not exist yet. The `name` field SHALL be set to a sensible default (e.g., "Default Agent"). The `language` field SHALL be set to a configurable default (e.g., "en").

The downgrade path SHALL delete the seed agent by its fixed UUID.

#### Scenario: Seed agent is present after migrations

WHEN `alembic upgrade head` is run on an empty database
THEN an agent record SHALL exist in the `agents` table with the fixed UUID literal constant
AND the agent SHALL have a non-null `default_knowledge_base_id`.

#### Scenario: Seed agent does not require a knowledge_bases table in S1-02

WHEN migration 002 inserts the seed agent
THEN `default_knowledge_base_id` SHALL be stored as a plain UUID literal
AND migration 002 SHALL NOT depend on a `knowledge_bases` table or FK.

#### Scenario: Seed agent UUID is deterministic

WHEN `alembic upgrade head` is run on two separate databases
THEN both databases SHALL contain an agent with the same UUID
AND the same `default_knowledge_base_id`.

#### Scenario: Seed agent downgrade removes the record

WHEN `alembic downgrade` is run to before migration 002
THEN the seed agent record SHALL no longer exist in the `agents` table.

---

### Requirement: Docker entrypoint integration

The backend Dockerfile SHALL be updated to:

1. COPY `migrations/`, `alembic.ini`, and `entrypoint.sh` into the image.
2. `RUN chmod +x entrypoint.sh`.
3. Use `entrypoint.sh` as the container entrypoint instead of direct uvicorn invocation.

`backend/entrypoint.sh` SHALL run `alembic upgrade head` (or an equivalent migration step) before starting the application server. The migration step MAY retry for a bounded period while PostgreSQL becomes ready. If the migration step ultimately fails, the container MUST NOT start uvicorn.

The entrypoint SHALL support the api service only in S1-02. Worker mode is NOT added in this story.

#### Scenario: Container runs migrations before starting

WHEN the api Docker container starts
THEN `alembic upgrade head` SHALL execute before uvicorn starts
AND if migrations succeed, uvicorn SHALL start.

#### Scenario: Container fails if migrations fail

WHEN `alembic upgrade head` fails (e.g., database unreachable)
THEN the container SHALL exit with a non-zero status
AND uvicorn SHALL NOT start.

#### Scenario: Dockerfile includes migration files

WHEN the Docker image is built
THEN the image SHALL contain the `migrations/` directory, `alembic.ini`, and `entrypoint.sh`.

---

### Requirement: docker-compose.yml integration

The `docker-compose.yml` api service SHALL be updated to use the new entrypoint. The api service SHALL depend on postgres being available.

The worker service SHALL NOT be added or modified in S1-02. The worker runtime (`app.workers.main.WorkerSettings`) does not exist yet — it is deferred to S2-01. Adding a worker service in this story would break `docker-compose up`.

#### Scenario: docker-compose up creates all tables

WHEN `docker-compose up` is run with empty database volumes
THEN the api service SHALL run migrations automatically
AND all 12 tables SHALL be created before the api starts accepting requests.

#### Scenario: Worker service is not present

WHEN `docker-compose.yml` is inspected after S1-02
THEN there SHALL be no worker service definition that references `app.workers.main.WorkerSettings`.

---

### Requirement: Local development workflow

For local development without Docker, the developer SHALL run `alembic upgrade head` manually before starting the application. The application startup (uvicorn) SHALL NOT automatically run migrations — automatic migration is the Docker entrypoint's responsibility only.

PostgreSQL MUST be accessible (via Docker, local install, or other means) before running migrations.

#### Scenario: Local alembic upgrade head succeeds

WHEN a developer runs `alembic upgrade head` from the `backend/` directory with valid PostgreSQL connection settings (via `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` environment variables or `.env` files as consumed by the application's Settings class)
THEN all migrations SHALL apply successfully
AND all 12 tables SHALL be created.

#### Scenario: Application starts without running migrations

WHEN uvicorn is started directly (without the entrypoint script)
THEN the application SHALL NOT attempt to run Alembic migrations
AND the application SHALL assume the database schema is already in place.

---

### Requirement: Worker service explicitly out of scope

The arq worker service and its entrypoint mode SHALL NOT be implemented in S1-02. The `entrypoint.sh` SHALL only support the api mode. Worker mode (arq process) is deferred to S2-01 when the ingestion task queue is introduced.

#### Scenario: entrypoint.sh does not reference worker mode

WHEN `entrypoint.sh` is inspected
THEN it SHALL contain only the api startup path (migration step, then uvicorn on success)
AND it SHALL NOT contain arq worker invocation or a mode switch for worker startup.
