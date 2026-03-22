## Story

**ID:** S2-05
**Title:** Replace MinIO with SeaweedFS
**Verification:** `docker-compose up` → SeaweedFS healthy; upload source → file in SeaweedFS; existing tests pass; `grep -ri minio backend/ docs/ CLAUDE.md AGENTS.md README.md docker-compose.yml .env.example` returns zero matches in runtime code and canonical docs (openspec change artifacts excluded — they document the migration itself).

## Why

MinIO is deprecated and MUST be fully removed from the project. All references to the MinIO server, the `minio` Python SDK, and MinIO-specific configuration must be replaced with SeaweedFS — an actively maintained, lightweight object storage with a simple Filer HTTP API.

## What Changes

- **BREAKING**: Remove `minio` Python SDK dependency entirely
- **BREAKING**: Replace Docker Compose `minio` service with `seaweedfs` (`weed server -filer`, all-in-one)
- **BREAKING**: Rename all `MINIO_*` environment variables to `SEAWEEDFS_*`
- **BREAKING**: Remove `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` (Filer API has no auth in v1)
- Rewrite `StorageService` to use `httpx` + SeaweedFS Filer HTTP API (POST/GET/DELETE) instead of `minio` SDK
- Rename `ensure_bucket()` → `ensure_storage_root()` to remove false S3 terminology
- Add dedicated `storage_http_client` (separate from generic `http_client`) with proper lifecycle in both API and worker
- Update `/ready` health check: replace MinIO HTTP probe with SeaweedFS Filer-level probe
- Update all documentation referencing MinIO

## Capabilities

### New Capabilities

None. This change replaces the storage backend without introducing new capabilities.

### Modified Capabilities

- `source-upload`: StorageService abstraction changes from `minio` SDK to `httpx` + Filer API. `ensure_bucket` renamed to `ensure_storage_root`. Constructor accepts `httpx.AsyncClient` + `base_path` instead of `Minio` client + `bucket_name`. File storage references change from MinIO to SeaweedFS.
- `infrastructure`: Docker Compose replaces `minio` service with `seaweedfs`. Healthcheck changes. `.env` variables rename from `MINIO_*` to `SEAWEEDFS_*`. FastAPI lifespan creates dedicated `storage_http_client` with proper shutdown.
- `backend-skeleton`: `/ready` endpoint replaces MinIO health probe with SeaweedFS Filer probe. Config fields change from `minio_*` to `seaweedfs_*`. `minio` removed from pyproject.toml dependencies.
- `ingestion-pipeline`: Worker initialization creates `httpx.AsyncClient` for storage (new lifecycle responsibility). `StorageService` constructor signature changes.

## Impact

- **Dependencies:** `minio >= 7.2.0` removed from `pyproject.toml`. Zero new dependencies (`httpx` already present).
- **Configuration:** All `MINIO_*` env vars replaced with `SEAWEEDFS_*`. Two fields removed (`MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`).
- **Docker:** `minio` service replaced by `seaweedfs`. Volume `minio-data` replaced by `seaweedfs-data`.
- **API:** `/ready` endpoint response key changes from `"minio"` to `"seaweedfs"`.
- **Tests:** All tests referencing MinIO must be updated (config, health, lifespan, storage, conftest, source-upload validation, source-upload integration, worker shutdown).
- **Documentation:** `spec.md`, `architecture.md`, `plan.md`, `rag.md`, `CLAUDE.md`, `AGENTS.md`, `README.md`.
