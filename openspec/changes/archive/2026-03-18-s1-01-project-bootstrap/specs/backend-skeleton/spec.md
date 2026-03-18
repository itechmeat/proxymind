## ADDED Requirements

### Requirement: Python version and package manager

The backend SHALL use Python at or above the minimum version specified in `docs/spec.md`. Dependency management SHALL use `uv` with `pyproject.toml` for declaration and `uv.lock` committed to git for reproducibility.

#### Scenario: pyproject.toml declares Python requirement

- **WHEN** inspecting `backend/pyproject.toml`
- **THEN** the `requires-python` field SHALL specify the minimum Python version from `docs/spec.md`

#### Scenario: Lock file is committed

- **WHEN** cloning the repository
- **THEN** `backend/uv.lock` SHALL exist and be tracked in git

### Requirement: FastAPI application structure

The backend SHALL follow the structure: `backend/app/main.py` as the application entry point, `backend/app/core/` for configuration and logging, and `backend/app/api/` for route handlers. The `main.py` file SHALL create the FastAPI app, configure lifespan hooks, and mount routers. Endpoint handlers SHALL NOT be defined in `main.py`.

#### Scenario: Application entry point exists

- **WHEN** inspecting `backend/app/main.py`
- **THEN** it SHALL create a FastAPI application instance and include routers from `api/`

#### Scenario: Lifespan responsibilities are explicit

- **WHEN** inspecting `backend/app/main.py`
- **THEN** its FastAPI lifespan hooks SHALL load configuration, initialize logging, create shared store clients needed by mounted routes, and close those resources gracefully during shutdown without aborting the remaining cleanup steps if one close operation fails

#### Scenario: Directory structure follows convention

- **WHEN** inspecting the backend directory tree
- **THEN** `backend/app/core/config.py`, `backend/app/core/logging.py`, and `backend/app/api/health.py` SHALL exist as Python modules

### Requirement: /health liveness endpoint

The API SHALL expose a `GET /health` endpoint that returns an unconditional liveness response. This endpoint SHALL NOT check any external dependencies.

#### Scenario: Health endpoint returns 200

- **WHEN** a GET request is sent to `/health`
- **THEN** the response status SHALL be 200 and the body SHALL be `{"status": "ok"}`

#### Scenario: Health endpoint does not check stores

- **WHEN** all store services (postgres, qdrant, minio, redis) are unreachable
- **THEN** `GET /health` SHALL still return 200 `{"status": "ok"}`

### Requirement: /ready readiness endpoint

The API SHALL expose a `GET /ready` endpoint that checks connectivity to all four stores (PostgreSQL, Qdrant, MinIO, Redis) in parallel. The endpoint SHALL return 200 only when all stores are reachable, and 503 when any store is unreachable.

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

#### Scenario: MinIO check uses HTTP health endpoint

- **WHEN** checking MinIO connectivity
- **THEN** the check SHALL use the MinIO HTTP health endpoint (`/minio/health/live`) via an HTTP client, not the MinIO Python SDK

### Requirement: structlog JSON logging

The backend SHALL configure structlog for structured JSON logging. Log output SHALL be in JSON format suitable for machine parsing.

#### Scenario: Logging produces JSON output

- **WHEN** the application emits a log entry
- **THEN** the output SHALL be a valid JSON object containing at minimum: timestamp, log level, and event message

#### Scenario: structlog is configured at startup

- **WHEN** inspecting `backend/app/core/logging.py`
- **THEN** it SHALL configure structlog with JSON rendering and standard processors

#### Scenario: Sensitive fields are redacted

- **WHEN** structured log events contain sensitive keys such as `password`, `token`, `authorization`, `secret`, `cookie`, or `api_key`
- **THEN** the logging pipeline SHALL redact those values before JSON rendering so they are not emitted in plaintext

### Requirement: pydantic-settings configuration

Application configuration SHALL use `pydantic-settings` with a `Settings` class that reads environment variables. Store connection URLs SHALL be computed from primitive environment variables (host, port, user, password, db) using computed fields — not read from pre-built DSN environment variables.

#### Scenario: Settings class computes DSNs from primitives

- **WHEN** inspecting `backend/app/core/config.py`
- **THEN** the `Settings` class SHALL define computed fields (e.g., `database_url`) that construct connection strings from individual primitive fields (`postgres_host`, `postgres_port`, etc.)

#### Scenario: Credentials are URL-encoded in DSNs

- **WHEN** computed DSNs are assembled from username and password fields
- **THEN** reserved URI characters in credentials SHALL be percent-encoded before the DSN string is returned

#### Scenario: Primitive fields are validated

- **WHEN** inspecting `backend/app/core/config.py`
- **THEN** store host fields SHALL be non-empty strings and port fields SHALL be validated as integers in the TCP port range

#### Scenario: Settings loads from env files

- **WHEN** the application starts outside Docker
- **THEN** the `Settings` class SHALL load variables from both the root `.env` and `backend/.env` via `SettingsConfigDict`

### Requirement: Multi-stage Dockerfile

The backend SHALL include a `Dockerfile` using a multi-stage build. The builder stage SHALL use the official uv image with Python to install dependencies. The runtime stage SHALL use a slim Python image. Layer ordering SHALL optimize for Docker cache efficiency.

#### Scenario: Dockerfile uses multi-stage build

- **WHEN** inspecting `backend/Dockerfile`
- **THEN** it SHALL contain at least two stages: a builder stage using a `uv` base image and a runtime stage using a slim Python base image

#### Scenario: Dependencies cached before app code

- **WHEN** inspecting the Dockerfile layer order
- **THEN** `pyproject.toml` and `uv.lock` SHALL be copied and dependencies installed before copying the application source code

#### Scenario: Runtime does not execute as root

- **WHEN** inspecting `backend/Dockerfile`
- **THEN** the runtime stage SHALL create a dedicated non-root user, grant that user ownership of the app directory, and switch to that user before starting the process

### Requirement: Test directory with conftest

The backend SHALL include a `backend/tests/` directory with a `conftest.py` file. The conftest SHALL configure pytest-asyncio for async test support. No functional tests are required at this stage.

#### Scenario: Test directory exists with conftest

- **WHEN** inspecting the backend directory
- **THEN** `backend/tests/conftest.py` SHALL exist and configure pytest-asyncio

### Requirement: Backend dependencies in pyproject.toml

The `pyproject.toml` SHALL declare all runtime dependencies needed for the S1-01 skeleton: FastAPI, uvicorn, pydantic-settings, structlog, asyncpg, redis (async client), and httpx. Versions SHALL meet or exceed the minimums in `docs/spec.md` where specified.

#### Scenario: Core dependencies declared

- **WHEN** inspecting `backend/pyproject.toml` dependencies
- **THEN** FastAPI, uvicorn, pydantic-settings, structlog, asyncpg, redis, and httpx SHALL be listed as dependencies.
