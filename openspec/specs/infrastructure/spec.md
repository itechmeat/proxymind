## ADDED Requirements

### Requirement: Docker Compose services

**[Modified by S7-02]** Docker Compose SHALL define nine runtime services: `postgres`, `qdrant`, `seaweedfs`, `redis`, `api`, `worker`, `prometheus`, `grafana`, and `tempo` (excluding `backend-test` which is a test-only container). Each service SHALL use image versions at or above the minimums specified in `docs/spec.md`. The `api` service SHALL build from `./backend` and expose port 8000. The `worker` service SHALL build from `./backend` with the command `python -m app.workers.run`. The `worker` service SHALL use the same Docker image as `api` but with a different startup command. The `worker` service SHALL set `SKIP_MIGRATIONS=1` so the worker does not race the API container during Alembic startup. The `worker` service SHALL NOT expose any ports and SHALL NOT require a healthcheck.

The `prometheus` service SHALL define a healthcheck using `wget --spider -q http://127.0.0.1:9090/-/healthy`. The `grafana` service SHALL define a healthcheck using `wget --spider -q http://127.0.0.1:3000/api/health`. The `tempo` service SHALL define a healthcheck using `test: ["CMD", "/tempo", "-health"]` so the distroless Tempo image is checked via its native readiness command.

The `seaweedfs` service SHALL use the `chrislusf/seaweedfs:latest` image and run `weed server -filer -dir=/data -master.port=9333 -filer.port=8888 -volume.port=9340` as the command. It SHALL expose port `8888` (Filer HTTP API) and port `9333` (Master). Port `9340` (volume server) SHALL NOT be exposed -- the Filer communicates with it internally. The service SHALL use the `seaweedfs-data` named volume mounted at `/data`.

The `prometheus` service SHALL use image `prom/prometheus:v3.10.0`, expose port `9090`, and mount `monitoring/prometheus/prometheus.yml` at `/etc/prometheus/prometheus.yml`. The `grafana` service SHALL use image `grafana/grafana:12.4.1`, expose port `3000`, and mount provisioning and dashboard files from `monitoring/grafana/`. The `tempo` service SHALL use image `grafana/tempo:2.10.3`, expose port `3200` (HTTP API) to the host, keep OTLP gRPC port `4317` internal to the Compose network, and mount `monitoring/tempo/tempo.yml`.

#### Scenario: All services start successfully

- **WHEN** `docker-compose up` is executed after the one-time local setup (copying `.env.example` files)
- **THEN** all nine runtime services SHALL reach a running state without errors

#### Scenario: Image versions meet spec minimums

- **WHEN** inspecting docker-compose.yml service definitions
- **THEN** PostgreSQL SHALL use image tag `18` or higher, Qdrant SHALL use `qdrant/qdrant` at 1.17+, Redis SHALL use image tag `8` or higher, SeaweedFS SHALL use `chrislusf/seaweedfs:latest`, Prometheus SHALL use `prom/prometheus:v3.10.0` or higher, Grafana SHALL use `grafana/grafana:12.4.1` or higher, Tempo SHALL use `grafana/tempo:2.10.3` or higher, and the `api` service SHALL build from `./backend`

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

#### Scenario: API and worker enable OTel tracing via environment

- **WHEN** the `api` and `worker` service definitions are inspected in `docker-compose.yml`
- **THEN** both SHALL set `OTEL_ENABLED=true` in their `environment` section
- **AND** this SHALL override the application default of `False`, enabling tracing only when the full monitoring stack is running

#### Scenario: Worker has no port mapping

- **WHEN** the `worker` service definition is inspected
- **THEN** it SHALL NOT define any `ports` mapping

#### Scenario: SeaweedFS runs all-in-one topology

- **WHEN** the `seaweedfs` service definition is inspected in `docker-compose.yml`
- **THEN** it SHALL run `weed server -filer` with master, volume, and filer in a single process
- **AND** it SHALL use LevelDB (the built-in default) for Filer metadata storage

#### Scenario: Monitoring services exist in Docker Compose

- **WHEN** `docker compose config --services` is executed
- **THEN** the output SHALL include `prometheus`, `grafana`, and `tempo`

#### Scenario: Prometheus service configuration

- **WHEN** the `prometheus` service definition is inspected
- **THEN** it SHALL use image `prom/prometheus:v3.10.0`
- **AND** it SHALL expose port `9090`
- **AND** it SHALL mount `monitoring/prometheus/prometheus.yml` as a volume

#### Scenario: Grafana service configuration

- **WHEN** the `grafana` service definition is inspected
- **THEN** it SHALL use image `grafana/grafana:12.4.1`
- **AND** it SHALL expose port `3000`
- **AND** it SHALL mount provisioning files from `monitoring/grafana/provisioning/`
- **AND** it SHALL mount dashboards from `monitoring/grafana/dashboards/`
- **AND** it SHALL depend on `prometheus` and `tempo`

#### Scenario: Tempo service configuration

- **WHEN** the `tempo` service definition is inspected
- **THEN** it SHALL use image `grafana/tempo:2.10.3`
- **AND** it SHALL expose port `3200` to the host while keeping OTLP gRPC internal to the Compose network
- **AND** it SHALL mount `monitoring/tempo/tempo.yml` as a volume

#### Scenario: Prometheus health check is configured

- **WHEN** the `prometheus` service healthcheck is inspected in `docker-compose.yml`
- **THEN** it SHALL define a healthcheck with test `wget --spider -q http://127.0.0.1:9090/-/healthy`

#### Scenario: Grafana health check is configured

- **WHEN** the `grafana` service healthcheck is inspected in `docker-compose.yml`
- **THEN** it SHALL define a healthcheck with test `wget --spider -q http://127.0.0.1:3000/api/health`

#### Scenario: Tempo health check is configured

- **WHEN** the `tempo` service healthcheck is inspected in `docker-compose.yml`
- **THEN** it SHALL define a healthcheck with test `test: ["CMD", "/tempo", "-health"]`

---

### Requirement: Service healthchecks

Each long-running Docker Compose service except `worker` SHALL define a `healthcheck` configuration that verifies the service is operational.

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

**[Modified by S7-02]** Docker Compose SHALL define named volumes for services that require data persistence across container restarts. The volume `seaweedfs-data` SHALL replace the former `minio-data` volume. Three additional named volumes SHALL be defined for monitoring services: `prometheus-data`, `grafana-data`, and `tempo-data`.

#### Scenario: Store data persists across restarts

- **WHEN** `docker-compose down` followed by `docker-compose up` is executed (without `-v` flag)
- **THEN** PostgreSQL, Qdrant, SeaweedFS, and Redis data SHALL be preserved

#### Scenario: Monitoring data persists across restarts

- **WHEN** `docker-compose down` followed by `docker-compose up` is executed (without `-v` flag)
- **THEN** Prometheus metrics history, Grafana settings, and Tempo traces SHALL be preserved

#### Scenario: All named volumes defined

- **WHEN** the `volumes` section of `docker-compose.yml` is inspected
- **THEN** it SHALL include: `postgres-data`, `qdrant-data`, `seaweedfs-data`, `redis-data`, `prometheus-data`, `grafana-data`, `tempo-data`

---

### Requirement: Monitoring configuration directories

**[Added by S7-02]** The repository SHALL contain monitoring configuration files in a `monitoring/` directory at the project root with the following structure:

```
monitoring/
	prometheus/
		prometheus.yml
	tempo/
		tempo.yml
	grafana/
		provisioning/
			datasources/
				datasources.yml
			dashboards/
				dashboards.yml
		dashboards/
			proxymind-overview.json
```

#### Scenario: Configuration directory structure exists

- **WHEN** the repository is inspected
- **THEN** all five configuration files SHALL exist at the specified paths under `monitoring/`

#### Scenario: Configuration files are valid

- **WHEN** the YAML configuration files are parsed
- **THEN** `prometheus.yml`, `tempo.yml`, `datasources.yml`, and `dashboards.yml` SHALL be valid YAML
- **AND** `proxymind-overview.json` SHALL be valid JSON

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
