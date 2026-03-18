# S1-01: Project Bootstrap — Design Spec

**Story:** S1-01 from `docs/plan.md`
**Date:** 2026-03-17
**Status:** Draft

## Goal

Bootstrap the ProxyMind monorepo: directory structure, Docker infrastructure, FastAPI skeleton with health endpoints, frontend init, CI lint pipeline. After this story, the project starts with a single command and the API responds.

## One-Time Local Setup

Before running for the first time (fresh clone), copy example env files:

```bash
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

The `.env.example` files contain safe dev defaults. No manual editing required for local development. This is a one-time step, not part of the daily workflow.

## Acceptance Criteria

1. After one-time local setup: `docker-compose up` — all 5 services start, healthchecks green
2. `curl http://localhost:8000/health` — 200 `{"status": "ok"}`
3. `curl http://localhost:8000/ready` — 200 `{"status": "ready"}` (all 4 stores reachable)
4. `cd frontend && bun install && bun run dev` — dev server starts on localhost:5173
5. `bun run lint` (frontend) — passes clean
6. `ruff check` + `ruff format --check` (backend) — passes clean
7. CI workflow on push — both lint jobs green

## Out of Scope

- Worker process (S2-01)
- Caddy runtime (separate story; Caddyfile included as a scaffold artifact)
- SQLAlchemy models and Alembic migrations (S1-02)
- Any functional code beyond health/ready
- Tests (S1-02, when there is something meaningful to test)

## Implementation Approach

**Bottom-up (infrastructure -> application):**

1. Docker Compose + .env files — verify stores start
2. Backend: pyproject.toml + uv + Dockerfile — FastAPI skeleton — /health, /ready
3. Frontend: Vite scaffold + Biome
4. Configs: Caddyfile, .editorconfig, .gitignore, persona/, config/
5. CI: GitHub Actions

### Rationale

Each step is independently verifiable: compose up -> stores running, add backend -> curl /health -> 200. This matches S1-01 acceptance criteria and follows the natural dependency order (backend depends on stores for /ready, Dockerfile depends on pyproject.toml). Alternative "outside-in" (create all structure first, fill in later) delays the first working check. Alternative "parallel tracks" adds coordination overhead with no real gain for a single-agent execution.

---

## Design Decisions

### D1: Python version — 3.14.3+ as specified in spec.md

Use the version mandated by `docs/spec.md`. The spec is the authority for all tool versions.

**Docker base image:** Multi-stage Dockerfile uses `ghcr.io/astral-sh/uv:python3.14-bookworm-slim` as the builder stage (uv + Python in one image) and `python:3.14-slim-bookworm` as the runtime stage.

**No downgrade policy:** If compiled dependencies (asyncpg, etc.) do not support Python 3.14, the story goes to BLOCKED status. Resolution path: find compatible dependency versions or open a spec review to reconsider the Python version in `docs/spec.md`. Falling below the minimum version specified in spec.md is not permitted per repository version policy.

### D2: Caddy — no runtime in S1-01, Caddyfile as scaffold

**Decision:** Include a valid Caddyfile in the repository but do not run Caddy at bootstrap.

**Rationale:**

- S1-01 acceptance criteria from `docs/plan.md` verify API via direct access (`curl /health -> 200`) and frontend via `bun dev`. Neither requires a reverse proxy.
- Adding Caddy runtime increases the bootstrap surface area (port routing, static serving, CORS/dev proxy, macOS host specifics) without verifiable benefit at this stage.
- `docs/architecture.md` describes Caddy on the host as target architecture, not as a bootstrap requirement.
- Including the Caddyfile as a scaffold communicates the target topology without introducing runtime complexity.
- Caddyfile must be a syntactically valid Caddy config (not a commented-out stub) so it can be validated with `caddy validate` and tested when Caddy is eventually introduced. Reference snippet:

```caddyfile
localhost {
	handle /api/* {
		reverse_proxy localhost:8000
	}
	handle {
		root * frontend/dist
		file_server
		try_files {path} /index.html
	}
}
```

**Alternatives rejected:**

- _Caddy in docker-compose (A):_ Creates a temporary topology (Caddy in Docker) that diverges from the target architecture (Caddy on host). Will be removed or rewritten later — wasted effort.
- _Caddy on host (B):_ Adds an external prerequisite (installed Caddy) that undermines the "single command start" promise of S1-01.

### D3: Docker Compose worker — only api, no worker

**Decision:** Docker Compose includes only the `api` service for backend. Worker service is added in S2-01 alongside arq task definitions.

**Rationale:**

- Worker without tasks is a dead process. arq `WorkerSettings` do not exist yet — the worker would either crash at startup or require a stub just to stay alive.
- S1-01 acceptance criteria say "all services start". A crashing or stub-only worker is noise in the first verification.
- Adding the worker in S2-01 is a 5-6 line diff in compose, introduced alongside `WorkerSettings` and the first task — the natural moment.

**Alternatives rejected:**

- _Worker running idle (A):_ Requires a stub `WorkerSettings` with no tasks. Code that exists only to make another thing not crash.
- _Worker commented out (C):_ Documentation inside a config file. Better to describe it in the design doc and keep compose clean and runnable.

### D4: Three .env files

**Decision:** Three separate .env files with different responsibilities:

| File            | Contents                                                   | Consumed by                              |
| --------------- | ---------------------------------------------------------- | ---------------------------------------- |
| `.env` (root)   | Infrastructure primitives: store credentials, hosts, ports | docker-compose + passed to api container |
| `backend/.env`  | Application-only config: LLM provider, API keys, log level | FastAPI (pydantic-settings)              |
| `frontend/.env` | Client config: `VITE_API_URL`                              | Vite (only VITE\_\* prefix exposed)      |

Each has a corresponding `.env.example` committed to git with safe dev defaults. `.env` files are in `.gitignore`.

**No DSN duplication — primitives only:**

Store connection parameters are stored as **primitives** in the root `.env` (e.g., `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`). The `backend/.env` does **not** contain pre-built DSNs like `DATABASE_URL`. Instead, the pydantic-settings `Settings` class constructs connection URLs from the primitives at runtime:

```python
@computed_field
@property
def database_url(self) -> str:
	quoted_user = quote_plus(self.postgres_user)
	quoted_password = quote_plus(self.postgres_password)
	return f"postgresql+asyncpg://{quoted_user}:{quoted_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
```

This eliminates drift: store credentials exist in exactly one place (root `.env`), and changing a password or port automatically propagates to all connection URLs. The `api` service in docker-compose receives root primitives via `env_file: [.env, ./backend/.env]`.

**Precedence and source of truth:**

| Variable category                                                                                                        | Defined in      | Notes                                                                                                                         |
| ------------------------------------------------------------------------------------------------------------------------ | --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Store primitives (POSTGRES_HOST/PORT/USER/PASSWORD/DB, REDIS_HOST/PORT, QDRANT_HOST/PORT, MINIO_HOST/PORT/USER/PASSWORD) | `.env` (root)   | Single source of truth for all store access. Compose uses them for service config; backend Settings constructs DSNs from them |
| App config (LOG_LEVEL, LLM_PROVIDER, API keys)                                                                           | `backend/.env`  | Only in `backend/.env` — not needed by compose                                                                                |
| Client config (VITE_API_URL)                                                                                             | `frontend/.env` | Only in `frontend/.env` — never touches backend                                                                               |

**Rationale:**

- Separation of concerns: infrastructure variables (Postgres password) and application variables (LiteLLM API key) have different lifecycles and security profiles.
- No DSN duplication: primitives in one file, DSNs computed in code. Changing `POSTGRES_PASSWORD` in root `.env` is sufficient — no need to update a second file.
- Frontend `.env` goes into the Vite bundle (client-side) — must be isolated from server secrets.
- Local development without Docker: `Settings` class declares `model_config = SettingsConfigDict(env_file=("../.env", ".env"))` to load root primitives and app config in one step. Docker Compose passes the same files via `env_file: [.env, ./backend/.env]`.

**Alternatives rejected:**

- _Two files as in architecture.md (B):_ Mixes infrastructure and application variables in `backend/.env`. Postgres password and LiteLLM API key are different security levels.
- _One file for compose + backend (C):_ Works initially but becomes a dumping ground as the project grows. Better to establish separation from the start.

**Note:** This deviates from `docs/architecture.md` which shows two .env files. `docs/architecture.md` must be updated to reflect the three-file strategy as part of S1-01 implementation (synchronized doc update, not deferred).

### D5: Frontend — Vite scaffold + Biome replacement

**Decision:** Initialize with `bun create vite frontend --template react-ts`, then remove ESLint config and replace with Biome as the sole linter/formatter.

**Rationale:**

- Vite scaffold provides a working structure in seconds (index.html, main.tsx, vite.config.ts, tsconfig). No need to write from scratch.
- Biome replaces both ESLint and Prettier with a single tool. Removing ESLint config immediately prevents two linters from coexisting.
- After scaffold: verify and pin versions per spec.md (React 19.2.4+, Vite 8.0.0+, Biome 2.4.7+).

**Alternatives rejected:**

- _Scaffold then "add Biome later" (A):_ Risk of forgetting or leaving conflicting configs.
- _Manual setup from scratch (B):_ More error-prone (tsconfig, vite config) with no benefit. Vite scaffold is already minimal.

### D6: Backend structure — main.py + core/ + api/ routers

**Decision:** Three directories at bootstrap:

```
backend/app/
  main.py          — FastAPI app, lifespan, router mounting
  core/
    config.py      — pydantic-settings Settings
    logging.py     — structlog configuration
  api/
    health.py      — /health and /ready router
```

Other directories from architecture.md (`services/`, `workers/`, `persona/`, `db/`) appear when their corresponding stories are implemented.

**Rationale:**

- Routers separated from `main.py` is the baseline FastAPI pattern. Avoids refactoring when S1-02/S2-01 add more routes.
- `core/` is needed at bootstrap: structlog is explicitly listed in S1-01 tasks, and pydantic-settings reads `backend/.env` for store connection strings (needed by /ready).
- `main.py` contains lifespan (init/close store connections), middleware mounting, and `include_router()` — not endpoint handlers.

**Alternatives rejected:**

- _Everything in main.py (A):_ Endpoints in main.py is an anti-pattern for FastAPI. Already in S1-02 they would need extraction — double work.
- _Full directory tree with empty **init**.py (B):_ Visual noise. Git does not track empty directories, and empty `__init__.py` for structure alone is over-engineering. Directories appear when code needs them.

### D7: /ready checks all 4 stores

**Decision:** `/ready` performs 4 async health checks in parallel (asyncio.gather): PostgreSQL `SELECT 1`, Redis `PING`, Qdrant health endpoint (HTTP), MinIO health endpoint (HTTP). All pass — 200. Any fail — 503 with details of which store is unreachable.

**Implementation notes:**

- Qdrant: `GET /readyz` — Kubernetes-style readiness probe, available since Qdrant v1.5.0. Does not require API key authentication. Returns 200 when ready.
- MinIO: `GET /minio/health/live` via HTTPX instead of requiring the `minio` Python SDK. This avoids an extra dependency at bootstrap. The `minio` SDK is added in S2-01 when file upload is needed.

`/health` is a simple liveness check — always returns 200 `{"status": "ok"}`.

**Rationale:**

- Docker Compose starts all 4 stores. If any store is down, `/ready` surfaces this immediately — not when a later story fails with a cryptic error.
- The `api` service in docker-compose can use `/ready` as its healthcheck. Docker won't mark the service as healthy until all stores are confirmed reachable. This is useful already for S1-01 verification and becomes critical with the worker in S2-01.
- Implementation is minimal: one async call per store, ~30 lines total.
- `/health` and `/ready` check different things (liveness vs readiness). Making both return unconditional 200 defeats the purpose of having two endpoints.

**Alternatives rejected:**

- _Check only PG + Redis (B):_ Arbitrary split. All 4 stores are in compose, all 4 should be verified. Partial checking gives false confidence.
- _/ready = /health at bootstrap (C):_ Two endpoints that do the same thing is pointless. Readiness checks should check readiness from the start.

### D8: CI lint — Biome + Ruff, no type checking

**Decision:** GitHub Actions workflow (`.github/workflows/ci.yml`) with two parallel jobs:

- `lint-backend`: `uv sync` -> `ruff check` -> `ruff format --check`
- `lint-frontend`: `bun install` -> `biome check`

Triggered on push and pull_request to `master` (current branch). No type checking at this stage.

**Rationale:**

- CI from the first commit is a discipline gate. Without it, every subsequent story defers it further.
- Ruff for Python: fast (Rust-based), covers flake8/isort/black rules in one tool. Configured in `pyproject.toml`.
- Biome for frontend: already chosen as the sole linter/formatter. `biome check` covers lint + format.
- Type checking (pyright/mypy) is deferred to S1-02 when SQLAlchemy models, Pydantic schemas, and service interfaces appear. On a bootstrap skeleton with 4 files, type checking adds overhead without value.

**Alternatives rejected:**

- _Full type checking included (A):_ pyright/mypy on an empty skeleton requires stub configuration for FastAPI/structlog without useful feedback. Premature.
- _Local-only tools, no CI (C):_ No enforcement. Someone forgets to lint, broken code hits main. CI is the automatic safety net.

**Note:** `docs/plan.md` S1-01 tasks mention "CI lint" without specifics. This decision pins the scope to Biome + Ruff.

### D9: Persona and config — placeholder templates

**Decision:** Create all 4 files with minimal template content (heading, description of purpose, placeholder fields):

- `persona/IDENTITY.md`
- `persona/SOUL.md`
- `persona/BEHAVIOR.md`
- `config/PROMOTIONS.md`

Content is English-language instructions for the owner, 5-10 lines per file.

**Rationale:**

- `docs/plan.md` S1-01 explicitly lists "Monorepo structure (`backend/` + `frontend/` + `persona/` + `config/` + `docs/`)". These directories are part of the monorepo structure promise.
- Templates aid onboarding: a fresh clone immediately shows where to put personality files and what format they expect.
- `config_content_hash` (SHA256 of `persona/` + `config/`) is defined in architecture.md for audit. If these files exist from the start, the hash is computable even before S4-01 persona loader.

**Alternatives rejected:**

- _Empty directories with .gitkeep (B):_ `.gitkeep` is a hack. A directory with no files doesn't explain what goes there.
- _Don't create until needed (C):_ Violates the monorepo structure defined in S1-01 scope. `persona/` and `config/` are explicitly listed.

### D10: Package manager — uv

**Decision:** Use `uv` for Python dependency management. `pyproject.toml` for dependency declaration, `uv.lock` for reproducibility (committed to git).

**Rationale:**

- uv is 10-100x faster than pip/poetry on dependency resolution and installation. Significant impact on Docker build times.
- Native `pyproject.toml` support — no proprietary config extensions.
- Docker-friendly: official image (`ghcr.io/astral-sh/uv`), multi-stage builds with efficient layer caching (`COPY pyproject.toml uv.lock -> uv sync -> COPY app/`).
- De facto standard for new Python projects in 2025-2026. The project already has the `uv-package-manager` skill installed.

**Alternatives rejected:**

- _Poetry (B):_ Slower, heavier Docker footprint (separate install step), non-standard pyproject.toml extensions.
- _pip + pip-tools (C):_ Works but uv does the same thing faster with better UX. No reason to choose the legacy approach for a greenfield 2026 project.

---

## Repository Structure After S1-01

```
proxymind/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app, lifespan, router mounting
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── config.py        # pydantic-settings Settings
│   │   │   └── logging.py       # structlog configuration
│   │   └── api/
│   │       ├── __init__.py
│   │       └── health.py        # /health + /ready router
│   ├── Dockerfile               # Multi-stage: uv install -> copy app
│   ├── pyproject.toml           # Dependencies + ruff config
│   ├── uv.lock                  # Committed for reproducibility
│   ├── tests/                   # conftest.py with pytest-asyncio config (S1-02 adds actual tests)
│   ├── .env.example
│   └── .env                     # (gitignored)
├── frontend/
│   ├── src/
│   │   ├── main.tsx
│   │   └── App.tsx              # Placeholder UI
│   ├── index.html
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── biome.json
│   ├── package.json
│   ├── bun.lock
│   ├── .env.example
│   └── .env                     # (gitignored)
├── persona/
│   ├── IDENTITY.md              # Template
│   ├── SOUL.md                  # Template
│   └── BEHAVIOR.md              # Template
├── config/
│   └── PROMOTIONS.md            # Template
├── docs/                        # (already exists)
├── .github/
│   └── workflows/
│       └── ci.yml               # Biome check + Ruff check
├── docker-compose.yml
├── Caddyfile                    # Scaffold (not used at runtime)
├── .editorconfig
├── .gitignore
├── .env.example
└── .env                         # (gitignored)
```

## Documentation Deviations

The following deviations from existing docs are introduced by this design. All must be resolved as part of S1-01 implementation (synchronized doc update), not deferred.

| Document               | Current state                           | This design                              | Required update                                                                                                                                                                                                      |
| ---------------------- | --------------------------------------- | ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs/architecture.md` | Shows 2 .env files (backend + frontend) | 3 .env files (root + backend + frontend) | Update Repository Structure section to reflect three .env files with precedence rules                                                                                                                                |
| `docs/plan.md`         | "CI lint" without specifics             | Biome + Ruff, no type checking           | Update S1-01 tasks to specify "CI lint (Biome + Ruff)"                                                                                                                                                               |
| `docs/architecture.md` | Caddy in runtime topology               | Caddyfile as scaffold only in S1-01      | No update needed — architecture.md correctly describes the target state (Caddy on host). The temporary absence of Caddy runtime is a story-level scope decision tracked in OpenSpec design, not in architecture docs |

---

Skills used: brainstorming
