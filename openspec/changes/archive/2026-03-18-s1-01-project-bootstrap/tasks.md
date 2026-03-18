## 1. Infrastructure Foundation

- [x] 1.1 Create root `.env.example` with store primitives (POSTGRES_HOST/PORT/USER/PASSWORD/DB, REDIS_HOST/PORT, QDRANT_HOST/PORT, MINIO_HOST/PORT/ROOT_USER/ROOT_PASSWORD) and safe dev defaults
- [x] 1.2 Create `docker-compose.yml` with five services (postgres:18, qdrant/qdrant:v1.17, minio/minio, redis:8, api from ./backend), healthchecks, depends_on with service_healthy, named volumes, env_file referencing root .env and backend/.env
- [x] 1.3 Create `.editorconfig` with charset, EOL, indent, trailing whitespace rules for Python and TypeScript
- [x] 1.4 Create `.gitignore` covering .env, node_modules, **pycache**, .venv, dist, IDE dirs, .DS_Store
- [x] 1.5 Create `Caddyfile` as a valid Caddy config (reverse proxy /api/\* to localhost:8000, file_server for frontend/dist with SPA fallback) — not a runtime service

## 2. Backend Skeleton

- [x] 2.1 Create `backend/pyproject.toml` with requires-python >=3.14, dependencies (fastapi, uvicorn, pydantic-settings, structlog, asyncpg, redis, httpx), dev dependencies (ruff, pytest, pytest-asyncio), and ruff config section
- [x] 2.2 Run `uv lock` to generate `backend/uv.lock`
- [x] 2.3 Create `backend/app/core/config.py` — pydantic-settings `Settings` class with store primitives as fields and computed DSN properties (database_url, redis_url, qdrant_url, minio_url); model_config with env_file loading from root and backend .env
- [x] 2.4 Create `backend/app/core/logging.py` — structlog configuration with JSON renderer
- [x] 2.5 Create `backend/app/api/health.py` — router with GET /health (unconditional 200 {"status": "ok"}) and GET /ready (parallel asyncio.gather checks: PG SELECT 1, Redis PING, Qdrant GET /readyz, MinIO GET /minio/health/live; 200 if all pass, 503 with details on failure)
- [x] 2.6 Create `backend/app/main.py` — FastAPI app with lifespan (init/close store connections), structlog setup, include_router from health.py
- [x] 2.7 Create `backend/app/__init__.py`, `backend/app/core/__init__.py`, `backend/app/api/__init__.py`
- [x] 2.8 Create `backend/.env.example` with app-only config (LOG_LEVEL=debug)
- [x] 2.9 Create `backend/Dockerfile` — multi-stage build: builder from ghcr.io/astral-sh/uv:python3.14-bookworm-slim (copy pyproject.toml + uv.lock, uv sync), runtime from python:3.14-slim-bookworm (copy installed deps + app code, entrypoint uvicorn)
- [x] 2.10 Create `backend/tests/conftest.py` with pytest-asyncio configuration

## 3. Frontend Skeleton

- [x] 3.1 Initialize frontend with `bun create vite frontend --template react-ts`
- [x] 3.2 Remove ESLint config files and eslint dependencies from package.json
- [x] 3.3 Install Biome (`bun add -D @biomejs/biome`), create `biome.json` with lint + format config
- [x] 3.4 Verify and pin versions per spec.md: React 19.2.4+, Vite 8.0.0+, Biome 2.4.7+
- [x] 3.5 Update App.tsx to a minimal placeholder component
- [x] 3.6 Create `frontend/.env.example` with `VITE_API_URL=http://localhost:8000`
- [x] 3.7 Add package.json scripts: `dev` (vite), `lint` (biome check .), `format` (biome format --write .)

## 4. Persona and Config Templates

- [x] 4.1 Create `persona/IDENTITY.md` — template with heading, purpose description, placeholder fields (role, background, public bio)
- [x] 4.2 Create `persona/SOUL.md` — template with heading, placeholder fields (speech style, tone, values)
- [x] 4.3 Create `persona/BEHAVIOR.md` — template with heading, placeholder fields (topic reactions, boundaries, dialogue manner)
- [x] 4.4 Create `config/PROMOTIONS.md` — template with heading, format description (product, priority, dates, context hints)

## 5. CI Pipeline

- [x] 5.1 Create `.github/workflows/ci.yml` with trigger on push and pull_request to master, two parallel jobs: lint-backend (uv sync, ruff check, ruff format --check) and lint-frontend (bun install, biome check)

## 6. Documentation Updates

- [x] 6.1 Update `docs/architecture.md` — reflect three .env files strategy in Repository Structure section
- [x] 6.2 Update `docs/plan.md` — update S1-01 tasks to specify "CI lint (Biome + Ruff)"

## 7. Verification

- [x] 7.1 Run `docker-compose up` — verify all 5 services start and healthchecks pass
- [x] 7.2 Run `curl http://localhost:8000/health` — verify 200 {"status": "ok"}
- [x] 7.3 Run `curl http://localhost:8000/ready` — verify 200 {"status": "ready"}
- [x] 7.4 Run `cd frontend && bun install && bun run dev` — verify dev server starts on localhost:5173
- [x] 7.5 Run `bun run lint` in frontend — verify passes clean
- [x] 7.6 Run `ruff check && ruff format --check` in backend — verify passes clean
- [ ] 7.7 Verify all dependency versions meet or exceed docs/spec.md minimums
  - Review result: Python 3.14.3, FastAPI 0.135.1, React 19.2.4, Vite 8.0.0, PostgreSQL 18.3, Qdrant 1.17.0, and Redis 8.6.1 meet spec minimums.
  - Remaining external gaps: local Bun is 1.3.5 (< 1.3.10 minimum), local Docker is 29.2.1 (< 29.3.0 minimum), and the exact MinIO release line from docs/spec.md is not available from the official registries tested, so compose uses the latest official Quay image instead.

## 8. Test Coverage Review

- [x] 8.1 Review test coverage for S1-01: Phase 1 bootstrap has no functional behavior to test beyond lint. Confirm that pytest scaffolding (conftest.py) is in place for S1-02. Document that functional test coverage starts with S1-02 when testable behavior (DB models, CRUD) is introduced.
