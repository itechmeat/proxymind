## MODIFIED Requirements

### Requirement: /health liveness endpoint

The API SHALL expose a `GET /health` endpoint that returns an unconditional liveness response. This endpoint SHALL NOT check any external dependencies.

#### Scenario: Health endpoint returns 200

- **WHEN** a GET request is sent to `/health`
- **THEN** the response status SHALL be 200 and the body SHALL be `{"status": "ok"}`

#### Scenario: Health endpoint does not check stores

- **WHEN** all store services (postgres, qdrant, seaweedfs, redis) are unreachable
- **THEN** `GET /health` SHALL still return 200 `{"status": "ok"}`

---

### Requirement: /ready readiness endpoint

The API SHALL expose a `GET /ready` endpoint that checks connectivity to all four stores (PostgreSQL, Qdrant, SeaweedFS, Redis) in parallel. The endpoint SHALL return 200 only when all stores are reachable, and 503 when any store is unreachable.

#### Scenario: All stores reachable

- **WHEN** a GET request is sent to `/ready` and all four stores are healthy
- **THEN** the response status SHALL be 200 and the body SHALL be `{"status": "ready"}`

#### Scenario: One or more stores unreachable

- **WHEN** a GET request is sent to `/ready` and at least one store is unreachable
- **THEN** the response status SHALL be 503 and the body SHALL include `status`, a `failed` array naming the unreachable stores, and a `failures` object keyed by store name with structured error details

#### Scenario: 503 response shape is explicit

- **WHEN** `/ready` returns 503
- **THEN** the JSON response SHALL follow this shape: `{"status":"degraded","failed":["postgres"],"failures":{"postgres":{"error_type":"TimeoutError","message":"Health check failed"}}}` where `status`, `failed`, and `failures` are required, and each failure entry SHALL include `error_type` and `message`

#### Scenario: Store checks run in parallel

- **WHEN** the `/ready` endpoint is invoked
- **THEN** all four store checks SHALL execute concurrently (e.g., via `asyncio.gather`), not sequentially

#### Scenario: Store checks fail fast on timeout

- **WHEN** a store check exceeds its per-store timeout or the overall readiness deadline
- **THEN** the timed-out store SHALL be treated as unreachable and `/ready` SHALL return 503 instead of hanging

#### Scenario: Qdrant check uses HTTP readiness probe

- **WHEN** checking Qdrant connectivity
- **THEN** the check SHALL use the Qdrant HTTP readiness endpoint (`/readyz`) via an HTTP client, not the Qdrant Python SDK

#### Scenario: SeaweedFS check uses Filer-level probe

- **WHEN** checking SeaweedFS connectivity
- **THEN** the check SHALL use `GET {seaweedfs_filer_url}/` (Filer root directory listing) via the generic `app.state.http_client`, not the storage-dedicated client
- **AND** the result SHALL be reported under the key `"seaweedfs"` in the readiness response

---

### Requirement: pydantic-settings configuration

Application configuration SHALL use `pydantic-settings` with a `Settings` class that reads environment variables. Store connection URLs SHALL be computed from primitive environment variables (host, port, user, password, db) using computed fields — not read from pre-built DSN environment variables.

SeaweedFS configuration SHALL use the following fields: `seaweedfs_host` (str, required), `seaweedfs_filer_port` (int, default 8888), `seaweedfs_sources_path` (str, default "/sources"), and a computed field `seaweedfs_filer_url` that constructs `http://{seaweedfs_host}:{seaweedfs_filer_port}`. The fields `minio_root_user` and `minio_root_password` SHALL NOT exist (SeaweedFS Filer has no authentication in v1).

#### Scenario: Settings class computes DSNs from primitives

- **WHEN** inspecting `backend/app/core/config.py`
- **THEN** the `Settings` class SHALL define computed fields (e.g., `database_url`, `seaweedfs_filer_url`) that construct connection strings from individual primitive fields (`postgres_host`, `postgres_port`, `seaweedfs_host`, `seaweedfs_filer_port`, etc.)

#### Scenario: Credentials are URL-encoded in DSNs

- **WHEN** computed DSNs are assembled from username and password fields
- **THEN** reserved URI characters in credentials SHALL be percent-encoded before the DSN string is returned

#### Scenario: Primitive fields are validated

- **WHEN** inspecting `backend/app/core/config.py`
- **THEN** store host fields SHALL be non-empty strings and port fields SHALL be validated as integers in the TCP port range

#### Scenario: Settings loads from env files

- **WHEN** the application starts outside Docker
- **THEN** the `Settings` class SHALL load variables from both the root `.env` and `backend/.env` via `SettingsConfigDict`

#### Scenario: SeaweedFS config fields replace MinIO fields

- **WHEN** inspecting the `Settings` class
- **THEN** it SHALL define `seaweedfs_host`, `seaweedfs_filer_port` (default 8888), `seaweedfs_sources_path` (default "/sources"), and computed `seaweedfs_filer_url`
- **AND** it SHALL NOT define `minio_host`, `minio_port`, `minio_root_user`, `minio_root_password`, `minio_bucket_sources`, or `minio_url`

---

### Requirement: Backend dependencies in pyproject.toml

The `pyproject.toml` SHALL declare all runtime dependencies needed for the backend: FastAPI, uvicorn, pydantic-settings, structlog, asyncpg, redis (async client), and httpx. Versions SHALL meet or exceed the minimums in `docs/spec.md` where specified. The `minio` package SHALL NOT be listed as a dependency.

#### Scenario: Core dependencies declared

- **WHEN** inspecting `backend/pyproject.toml` dependencies
- **THEN** FastAPI, uvicorn, pydantic-settings, structlog, asyncpg, redis, and httpx SHALL be listed as dependencies
- **AND** `minio` SHALL NOT be listed as a dependency

---

## REMOVED Requirements

### Requirement: MinIO health check via /minio/health/live

- **Reason:** MinIO is fully removed. The MinIO HTTP health endpoint (`/minio/health/live`) no longer exists.
- **Migration:** Replaced by SeaweedFS Filer-level probe (`GET {seaweedfs_filer_url}/`) in the modified "/ready readiness endpoint" requirement. The readiness response key changes from `"minio"` to `"seaweedfs"`.
