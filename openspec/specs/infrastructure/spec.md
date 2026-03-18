## ADDED Requirements

### Requirement: Docker Compose services

Docker Compose SHALL define six services: `postgres`, `qdrant`, `minio`, `redis`, `api`, and `worker`. Each service SHALL use image versions at or above the minimums specified in `docs/spec.md`. The `api` service SHALL build from `./backend` and expose port 8000. The `worker` service SHALL build from `./backend` with the command `python -m app.workers.run`. The `worker` service SHALL use the same Docker image as `api` but with a different startup command. The `worker` service SHALL set `SKIP_MIGRATIONS=1` so the worker does not race the API container during Alembic startup. The `worker` service SHALL NOT expose any ports and SHALL NOT require a healthcheck.

#### Scenario: All services start successfully

- **WHEN** `docker-compose up` is executed after the one-time local setup (copying `.env.example` files)
- **THEN** all six services SHALL reach a running state without errors

#### Scenario: Image versions meet spec minimums

- **WHEN** inspecting docker-compose.yml service definitions
- **THEN** PostgreSQL SHALL use image tag `18` or higher, Qdrant SHALL use `qdrant/qdrant` at 1.17+, Redis SHALL use image tag `8` or higher, MinIO SHALL use a compatible release image, and the `api` service SHALL build from `./backend`

#### Scenario: Worker service exists in Docker Compose

- **WHEN** `docker compose config --services` is executed
- **THEN** the output SHALL include `worker`

#### Scenario: Worker uses same image as API

- **WHEN** the `worker` service definition is inspected in `docker-compose.yml`
- **THEN** it SHALL use the same `build` configuration as the `api` service (`./backend`)
- **AND** its command SHALL be `python -m app.workers.run`

#### Scenario: Worker depends on healthy stores

- **WHEN** the `worker` service `depends_on` is inspected
- **THEN** it SHALL declare dependencies on `postgres`, `redis`, and `minio` with `condition: service_healthy`

#### Scenario: Worker receives env files

- **WHEN** the `worker` service definition is inspected
- **THEN** it SHALL declare `env_file` that includes both the root `.env` and `backend/.env`
- **AND** it SHALL set `SKIP_MIGRATIONS=1`

#### Scenario: Worker has no port mapping

- **WHEN** the `worker` service definition is inspected
- **THEN** it SHALL NOT define any `ports` mapping

### Requirement: Service healthchecks

Each service in Docker Compose SHALL define a `healthcheck` configuration that verifies the service is operational.

#### Scenario: PostgreSQL healthcheck

- **WHEN** the PostgreSQL container is running
- **THEN** the healthcheck SHALL execute a command that verifies the database accepts connections (e.g., `pg_isready`)

#### Scenario: Redis healthcheck

- **WHEN** the Redis container is running
- **THEN** the healthcheck SHALL execute a command that verifies Redis responds to PING

#### Scenario: Qdrant healthcheck

- **WHEN** the Qdrant container is running
- **THEN** the healthcheck SHALL verify the Qdrant service is responsive

#### Scenario: MinIO healthcheck

- **WHEN** the MinIO container is running
- **THEN** the healthcheck SHALL verify the MinIO service is responsive

#### Scenario: API service healthcheck

- **WHEN** the API container is running
- **THEN** the healthcheck SHALL use the `/ready` endpoint to verify the API and all its store dependencies are operational

### Requirement: Service dependency ordering

The `api` service SHALL declare `depends_on` with `condition: service_healthy` for all four store services: `postgres`, `qdrant`, `minio`, and `redis`.

#### Scenario: API waits for healthy stores

- **WHEN** `docker-compose up` is executed
- **THEN** the `api` service SHALL NOT start until all four store services report healthy status

### Requirement: Persistent volumes

Docker Compose SHALL define named volumes for services that require data persistence across container restarts.

#### Scenario: Store data persists across restarts

- **WHEN** `docker-compose down` followed by `docker-compose up` is executed (without `-v` flag)
- **THEN** PostgreSQL, Qdrant, MinIO, and Redis data SHALL be preserved

### Requirement: Three .env files strategy

The project SHALL use three separate `.env` files with distinct responsibilities: root `.env` for infrastructure primitives, `backend/.env` for application config, and `frontend/.env` for client config. Store connection parameters SHALL be stored as primitives (individual host, port, user, password, db fields) in the root `.env` — not as pre-built DSNs. DSN construction SHALL happen in application code.

#### Scenario: Root .env contains only infrastructure primitives

- **WHEN** inspecting the root `.env.example`
- **THEN** it SHALL contain primitive variables for all four stores (e.g., `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `REDIS_HOST`, `REDIS_PORT`, `QDRANT_HOST`, `QDRANT_PORT`, `MINIO_HOST`, `MINIO_PORT`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`) and SHALL NOT contain any pre-built DSN or connection URL strings

#### Scenario: Backend .env contains application-only config

- **WHEN** inspecting `backend/.env.example`
- **THEN** it SHALL contain application-level variables (e.g., `LOG_LEVEL`) and SHALL NOT duplicate store primitives from the root `.env`

#### Scenario: Frontend .env contains client config

- **WHEN** inspecting `frontend/.env.example`
- **THEN** it SHALL contain `VITE_API_URL` and SHALL NOT contain any backend or infrastructure variables

#### Scenario: API service receives both root and backend env files

- **WHEN** inspecting the `api` service definition in docker-compose.yml
- **THEN** it SHALL declare `env_file` that includes both the root `.env` and `backend/.env`

### Requirement: .env.example files committed to git

Each of the three `.env` files SHALL have a corresponding `.env.example` file committed to the repository with safe development defaults. The actual `.env` files SHALL be listed in `.gitignore`.

#### Scenario: Example files exist with safe defaults

- **WHEN** cloning the repository
- **THEN** `.env.example`, `backend/.env.example`, and `frontend/.env.example` SHALL exist and contain working default values for local development

#### Scenario: Actual .env files are gitignored

- **WHEN** inspecting `.gitignore`
- **THEN** `.env` files SHALL be excluded from version control

### Requirement: Caddyfile scaffold

The repository SHALL contain a `Caddyfile` at the project root that is a syntactically valid Caddy configuration. Caddy SHALL NOT be run as a service at this stage.

#### Scenario: Caddyfile is valid Caddy syntax

- **WHEN** inspecting the Caddyfile
- **THEN** it SHALL contain a valid configuration that reverse-proxies `/api/*` to the backend and serves the frontend as a file server with SPA fallback

#### Scenario: Caddy is not a runtime service

- **WHEN** inspecting docker-compose.yml
- **THEN** there SHALL be no Caddy service defined

### Requirement: .editorconfig

The repository SHALL contain an `.editorconfig` file at the project root that defines consistent coding styles across editors.

#### Scenario: EditorConfig defines baseline formatting

- **WHEN** inspecting `.editorconfig`
- **THEN** it SHALL define at minimum: charset, end-of-line style, indent style, indent size, and trailing whitespace rules

### Requirement: .gitignore

The repository SHALL contain a `.gitignore` file that excludes generated files, dependencies, environment files, and IDE-specific files from version control.

#### Scenario: Common artifacts are excluded

- **WHEN** inspecting `.gitignore`
- **THEN** it SHALL exclude at minimum: `.env` files, `node_modules/`, `__pycache__/`, `.venv/`, `dist/`, and IDE directories

### Requirement: FastAPI lifespan startup additions

The FastAPI lifespan SHALL initialize the following additional resources during startup: (1) a MinIO client instance configured from settings (host, port, access key, secret key, `secure=False` for local Docker development in S2-01), (2) a `StorageService` wrapping the MinIO client with bucket auto-creation via `ensure_bucket()`, stored in `app.state.storage_service`, using the bucket name from `MINIO_BUCKET_SOURCES`, (3) an arq Redis pool via `create_pool(RedisSettings(...))`, stored in `app.state.arq_pool`. During shutdown, `app.state.arq_pool.close()` SHALL be awaited. Existing shutdown steps (engine disposal, etc.) SHALL continue to execute even if the arq pool close fails.

#### Scenario: MinIO client initialized at startup

- **WHEN** the application completes startup
- **THEN** `app.state.storage_service` SHALL be an active `StorageService` instance

#### Scenario: arq pool initialized at startup

- **WHEN** the application completes startup
- **THEN** `app.state.arq_pool` SHALL be an active arq Redis pool

#### Scenario: arq pool closed on shutdown

- **WHEN** the application shuts down
- **THEN** `await app.state.arq_pool.close()` SHALL be called
- **AND** subsequent shutdown steps (engine disposal) SHALL still execute

#### Scenario: Admin router mounted

- **WHEN** the application starts
- **THEN** the admin router SHALL be included with routes for `POST /api/admin/sources` and `GET /api/admin/tasks/{task_id}`
