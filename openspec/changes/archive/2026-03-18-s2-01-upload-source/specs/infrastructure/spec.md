## MODIFIED Requirements

### Requirement: Docker Compose services

Docker Compose SHALL define six services: `postgres`, `qdrant`, `minio`, `redis`, `api`, and `worker`. The `worker` service SHALL build from `./backend` with the command `python -m app.workers.run`. The `worker` service SHALL use the same Docker image as `api` but with a different startup command. The `worker` service SHALL set `SKIP_MIGRATIONS=1` so the worker does not race the API container during Alembic startup. The `worker` service SHALL NOT expose any ports and SHALL NOT require a healthcheck.

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
