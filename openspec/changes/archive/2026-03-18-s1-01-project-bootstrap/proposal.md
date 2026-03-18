## Story

**ID:** S1-01 (Phase 1: Bootstrap)
**Verification:** `docker-compose up` → all services start; `curl /health` → 200; `cd frontend && bun dev` → dev server starts

## Why

The ProxyMind repository currently contains only documentation. No code, infrastructure, or tooling exists. Every subsequent story depends on a working monorepo with running services, a responsive API, and a buildable frontend. This is the foundation — nothing else can start until bootstrap is complete.

## What Changes

- Create monorepo directory structure: `backend/`, `frontend/`, `persona/`, `config/`
- Add `docker-compose.yml` with PostgreSQL 18, Qdrant 1.17, MinIO, Redis 8, and FastAPI API service
- Create backend: Python 3.14 + FastAPI + structlog skeleton with `/health` and `/ready` endpoints
- Create Dockerfile for backend using uv package manager (multi-stage build)
- Initialize frontend: Bun + Vite + React + Biome (replacing ESLint)
- Add `.env` file strategy (three files: root infra, backend app, frontend client)
- Add persona file templates (`IDENTITY.md`, `SOUL.md`, `BEHAVIOR.md`) and config template (`PROMOTIONS.md`)
- Add Caddyfile as a valid but not-yet-active scaffold
- Add `.editorconfig`, `.gitignore`
- Add CI workflow: GitHub Actions with Biome check + Ruff check

## Capabilities

### New Capabilities
- `infrastructure`: Docker Compose services, .env strategy, Caddyfile scaffold, editorconfig, gitignore
- `backend-skeleton`: FastAPI app structure, health/ready endpoints, structlog, pydantic-settings, uv packaging
- `frontend-skeleton`: Bun + Vite + React + Biome initialization, dev server config
- `ci-lint`: GitHub Actions lint pipeline (Ruff for backend, Biome for frontend)

### Modified Capabilities
<!-- None — greenfield project, no existing specs -->

## Impact

- **Code:** Creates `backend/`, `frontend/`, `persona/`, `config/`, `.github/` directories with initial files
- **Infrastructure:** Introduces Docker Compose with 5 services (postgres, qdrant, minio, redis, api)
- **Dependencies:** Python 3.14.3+, FastAPI 0.135.1+, Pydantic 2.12.5+, structlog 25.5.0+, React 19.2.4+, Vite 8.0.0+, Biome 2.4.7+ (all per docs/spec.md)
- **CI:** New GitHub Actions workflow on master branch
- **Docs:** `docs/architecture.md` must be updated to reflect three .env files (synchronized with implementation)
