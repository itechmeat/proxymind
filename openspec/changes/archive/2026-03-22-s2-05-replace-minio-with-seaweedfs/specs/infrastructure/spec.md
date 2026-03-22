## MODIFIED Requirements

### Requirement: Docker Compose services

Docker Compose SHALL define six services: `postgres`, `qdrant`, `seaweedfs`, `redis`, `api`, and `worker`. Each service SHALL use image versions at or above the minimums specified in `docs/spec.md`. The `api` service SHALL build from `./backend` and expose port 8000. The `worker` service SHALL build from `./backend` with the command `python -m app.workers.run`. The `worker` service SHALL use the same Docker image as `api` but with a different startup command. The `worker` service SHALL set `SKIP_MIGRATIONS=1` so the worker does not race the API container during Alembic startup. The `worker` service SHALL NOT expose any ports and SHALL NOT require a healthcheck.

The `seaweedfs` service SHALL use the `chrislusf/seaweedfs:latest` image and run `server -filer -dir=/data -master.port=9333 -filer.port=8888 -volume.port=9340` as the command. It SHALL expose port `8888` (Filer HTTP API) and port `9333` (Master). Port `9340` (volume server) SHALL NOT be exposed — the Filer communicates with it internally. The service SHALL use the `seaweedfs-data` named volume mounted at `/data`.

#### Scenario: All services start successfully

- **WHEN** `docker-compose up` is executed after the one-time local setup (copying `.env.example` files)
- **THEN** all six services SHALL reach a running state without errors

#### Scenario: Image versions meet spec minimums

- **WHEN** inspecting docker-compose.yml service definitions
- **THEN** PostgreSQL SHALL use image tag `18` or higher, Qdrant SHALL use `qdrant/qdrant` at 1.17+, Redis SHALL use image tag `8` or higher, SeaweedFS SHALL use `chrislusf/seaweedfs:latest`, and the `api` service SHALL build from `./backend`

#### Scenario: Worker service exists in Docker Compose

- **WHEN** `docker compose config --services` is executed
- **THEN** the output SHALL include `worker`

#### Scenario: Worker uses same image as API

- **WHEN** the `worker` service definition is inspected in `docker-compose.yml`
- **THEN** it SHALL use the same `build` configuration as the `api` service (`./backend`)
- **AND** its command SHALL be `python -m app.workers.run`

#### Scenario: Worker depends on healthy stores

- **WHEN** the `worker` service `depends_on` is inspected
- **THEN** it SHALL declare dependencies on `postgres`, `redis`, and `seaweedfs` with `condition: service_healthy`

#### Scenario: Worker receives env files

- **WHEN** the `worker` service definition is inspected
- **THEN** it SHALL declare `env_file` that includes both the root `.env` and `backend/.env`
- **AND** it SHALL set `SKIP_MIGRATIONS=1`

#### Scenario: Worker has no port mapping

- **WHEN** the `worker` service definition is inspected
- **THEN** it SHALL NOT define any `ports` mapping

#### Scenario: SeaweedFS runs all-in-one topology

- **WHEN** the `seaweedfs` service definition is inspected in `docker-compose.yml`
- **THEN** it SHALL run `weed server -filer` with master, volume, and filer in a single process
- **AND** it SHALL use LevelDB (the built-in default) for Filer metadata storage

---

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

#### Scenario: SeaweedFS healthcheck

- **WHEN** the SeaweedFS container is running
- **THEN** the healthcheck SHALL use `GET /cluster/healthz` on the master port (9333) to verify the `weed server` process is running
- **AND** the healthcheck SHALL use `wget -qO- http://localhost:9333/cluster/healthz || exit 1`
- **AND** it SHALL use `interval: 15s`, `timeout: 10s`, `retries: 10`, `start_period: 20s`

#### Scenario: API service healthcheck

- **WHEN** the API container is running
- **THEN** the healthcheck SHALL use the `/ready` endpoint to verify the API and all its store dependencies are operational

---

### Requirement: Service dependency ordering

The `api` service SHALL declare `depends_on` with `condition: service_healthy` for all four store services: `postgres`, `qdrant`, `seaweedfs`, and `redis`.

#### Scenario: API waits for healthy stores

- **WHEN** `docker-compose up` is executed
- **THEN** the `api` service SHALL NOT start until all four store services report healthy status

---

### Requirement: Persistent volumes

Docker Compose SHALL define named volumes for services that require data persistence across container restarts. The volume `seaweedfs-data` SHALL replace the former `minio-data` volume.

#### Scenario: Store data persists across restarts

- **WHEN** `docker-compose down` followed by `docker-compose up` is executed (without `-v` flag)
- **THEN** PostgreSQL, Qdrant, SeaweedFS, and Redis data SHALL be preserved

---

### Requirement: Three .env files strategy

The project SHALL use three separate `.env` files with distinct responsibilities: root `.env` for infrastructure primitives, `backend/.env` for application config, and `frontend/.env` for client config. Store connection parameters SHALL be stored as primitives (individual host, port fields) in the root `.env` — not as pre-built DSNs. DSN construction SHALL happen in application code.

#### Scenario: Root .env contains only infrastructure primitives

- **WHEN** inspecting the root `.env.example`
- **THEN** it SHALL contain primitive variables for all four stores (e.g., `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `REDIS_HOST`, `REDIS_PORT`, `QDRANT_HOST`, `QDRANT_PORT`, `SEAWEEDFS_HOST`, `SEAWEEDFS_FILER_PORT`) and SHALL NOT contain any pre-built DSN or connection URL strings
- **AND** it SHALL NOT contain `MINIO_ROOT_USER` or `MINIO_ROOT_PASSWORD` (SeaweedFS Filer has no authentication in v1)

#### Scenario: Backend .env contains application-only config

- **WHEN** inspecting `backend/.env.example`
- **THEN** it SHALL contain application-level variables (e.g., `LOG_LEVEL`) and SHALL NOT duplicate store primitives from the root `.env`

#### Scenario: Frontend .env contains client config

- **WHEN** inspecting `frontend/.env.example`
- **THEN** it SHALL contain `VITE_API_URL` and SHALL NOT contain any backend or infrastructure variables

#### Scenario: API service receives both root and backend env files

- **WHEN** inspecting the `api` service definition in docker-compose.yml
- **THEN** it SHALL declare `env_file` that includes both the root `.env` and `backend/.env`

---

### Requirement: FastAPI lifespan startup additions

The FastAPI lifespan SHALL initialize the following additional resources during startup: (1) a dedicated `storage_http_client` (`httpx.AsyncClient` with `base_url=settings.seaweedfs_filer_url` and `timeout=30.0`) stored in `app.state.storage_http_client`, (2) a `StorageService` wrapping the storage HTTP client with storage root auto-creation via `ensure_storage_root()`, stored in `app.state.storage_service`, using the sources path from `SEAWEEDFS_SOURCES_PATH`, (3) an arq Redis pool via `create_pool(RedisSettings(...))`, stored in `app.state.arq_pool`. During shutdown, `app.state.arq_pool.close()` SHALL be awaited, and `app.state.storage_http_client.aclose()` SHALL be awaited. The `storage_http_client` SHALL be added to the `_close_app_resources` shutdown list with the key `("storage_http_client", "aclose", "app.shutdown.storage_http_client_close_failed")`. Existing shutdown steps (engine disposal, etc.) SHALL continue to execute even if one close operation fails.

The `storage_http_client` is a **separate** client from the generic `app.state.http_client` (timeout=5s, no base_url) used for health probes. See Decision 8 in design spec for rationale: different timeout and base_url requirements.

#### Scenario: Storage HTTP client initialized at startup

- **WHEN** the application completes startup
- **THEN** `app.state.storage_http_client` SHALL be an active `httpx.AsyncClient` with `base_url` set to `settings.seaweedfs_filer_url` and `timeout=30.0`

#### Scenario: StorageService initialized at startup

- **WHEN** the application completes startup
- **THEN** `app.state.storage_service` SHALL be an active `StorageService` instance wrapping `app.state.storage_http_client`

#### Scenario: arq pool initialized at startup

- **WHEN** the application completes startup
- **THEN** `app.state.arq_pool` SHALL be an active arq Redis pool

#### Scenario: Storage HTTP client closed on shutdown

- **WHEN** the application shuts down
- **THEN** `await app.state.storage_http_client.aclose()` SHALL be called
- **AND** subsequent shutdown steps (engine disposal) SHALL still execute

#### Scenario: arq pool closed on shutdown

- **WHEN** the application shuts down
- **THEN** `await app.state.arq_pool.close()` SHALL be called
- **AND** subsequent shutdown steps (engine disposal) SHALL still execute

#### Scenario: Admin router mounted

- **WHEN** the application starts
- **THEN** the admin router SHALL be included with routes for `POST /api/admin/sources` and `GET /api/admin/tasks/{task_id}`

---

## REMOVED Requirements

### Requirement: MinIO client initialization in lifespan

- **Reason:** MinIO Python SDK (`minio`) is fully removed. The `Minio` client constructor, `secure=False` parameter, and `asyncio.to_thread()` wrappers are replaced by a dedicated `httpx.AsyncClient` with `base_url` and native async calls.
- **Migration:** Replaced by `storage_http_client` creation in the modified "FastAPI lifespan startup additions" requirement above.
