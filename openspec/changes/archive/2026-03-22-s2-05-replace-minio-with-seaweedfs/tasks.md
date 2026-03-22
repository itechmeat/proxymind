## 1. Infrastructure

- [x] 1.1 Replace `minio` service with `seaweedfs` in `docker-compose.yml` (`chrislusf/seaweedfs:latest`, `weed server -filer`, ports 8888/9333, volume `seaweedfs-data`, healthcheck on `/cluster/healthz`)
- [x] 1.2 Update `depends_on` in `api` and `worker` services: `minio` → `seaweedfs`
- [x] 1.3 Remove `minio-data` from volumes section, add `seaweedfs-data`
- [x] 1.4 Update `.env.example`: replace `MINIO_*` vars with `SEAWEEDFS_HOST=seaweedfs` and `SEAWEEDFS_FILER_PORT=8888`, remove `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD`

## 2. Dependencies

- [x] 2.1 Remove `minio` from `backend/pyproject.toml` dependencies
- [x] 2.2 Run `uv lock` to regenerate `uv.lock`

## 3. Configuration

- [x] 3.1 Replace `minio_*` fields in `config.py` with `seaweedfs_host`, `seaweedfs_filer_port` (default 8888), `seaweedfs_sources_path` (default `/sources`)
- [x] 3.2 Remove `minio_root_user` and `minio_root_password` fields
- [x] 3.3 Replace computed property `minio_url` with `seaweedfs_filer_url` (`http://{host}:{port}`)

## 4. StorageService Rewrite

- [x] 4.1 Rewrite `StorageService.__init__` to accept `httpx.AsyncClient` + `base_path: str` instead of `Minio` client + `bucket_name`
- [x] 4.2 Add `_build_url(object_key)` private helper with path normalization (canonical form: leading slash, no trailing slash)
- [x] 4.3 Rename `ensure_bucket()` → `ensure_storage_root()`: implementation as `POST {base_path}/`
- [x] 4.4 Rewrite `upload()`: `POST {base_path}/{key}` with multipart file, forward `content_type`
- [x] 4.5 Rewrite `download()`: `GET {base_path}/{key}`, return `resp.content`
- [x] 4.6 Rewrite `delete()`: `DELETE {base_path}/{key}`
- [x] 4.7 Remove `minio` and `asyncio.to_thread` imports from `storage.py`

## 5. API Lifecycle (main.py)

- [x] 5.1 Create dedicated `storage_http_client = httpx.AsyncClient(base_url=settings.seaweedfs_filer_url, timeout=30.0)` in lifespan startup
- [x] 5.2 Store `storage_http_client` in `app.state.storage_http_client`
- [x] 5.3 Update `StorageService` construction: pass `storage_http_client` + `settings.seaweedfs_sources_path`
- [x] 5.4 Update `ensure_bucket()` call to `ensure_storage_root()`
- [x] 5.5 Add `("storage_http_client", "aclose", "app.shutdown.storage_http_client_close_failed")` to `_close_app_resources`
- [x] 5.6 Remove `Minio` import from `main.py`

## 6. Worker Lifecycle (workers/main.py)

- [x] 6.1 Create `storage_http_client = httpx.AsyncClient(base_url=..., timeout=30.0)` in `on_startup`
- [x] 6.2 Store `storage_http_client` in `ctx["storage_http_client"]`
- [x] 6.3 Update `StorageService` construction: pass `storage_http_client` + `settings.seaweedfs_sources_path`
- [x] 6.4 Call `ensure_storage_root()` in `on_startup` (required by ingestion-pipeline spec)
- [x] 6.5 Add `storage_http_client.aclose()` to `on_shutdown`
- [x] 6.6 Remove `Minio` import from `workers/main.py`

## 7. Health Check (health.py)

- [x] 7.1 Replace `"minio"` key with `"seaweedfs"` in readiness checks dict
- [x] 7.2 Replace `settings.minio_url + "/minio/health/live"` with `settings.seaweedfs_filer_url + "/"`
- [x] 7.3 Verify the readiness check uses the generic `http_client`, not the storage client

## 8. Tests

- [x] 8.1 Rewrite `test_storage_download.py` → `test_storage.py`: use `httpx.MockTransport` for all StorageService methods (upload POST, download GET, delete DELETE, ensure_storage_root POST, path normalization edge cases, error propagation)
- [x] 8.2 Update `test_config.py`: replace `MINIO_*` env vars with `SEAWEEDFS_*`, remove `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`
- [x] 8.3 Update `test_app_main.py`: replace `minio_*` settings, replace `Minio` monkeypatch with httpx mock, update `StorageService` constructor mock, add `storage_http_client.aclose()` shutdown assertion
- [x] 8.4 Update `test_health.py`: `minio_url` → `seaweedfs_filer_url` in settings, `"minio"` → `"seaweedfs"` in readiness response assertions
- [x] 8.5 Update `conftest.py`: `mock_storage_service` fixture (`ensure_bucket` → `ensure_storage_root`), `admin_app` settings (`minio_bucket_sources` → `seaweedfs_sources_path`)
- [x] 8.6 Update `test_source_validation.py`: rename `ensure_bucket` references to `ensure_storage_root`, update any MinIO-specific assertions
- [x] 8.7 Update source-upload integration tests: verify upload flow works with new StorageService contract (mock via `httpx.MockTransport`), verify enqueue-failure path with updated storage mock
- [x] 8.8 Add worker shutdown test: verify `storage_http_client.aclose()` is called in `on_shutdown`

## 9. Documentation

- [x] 9.1 Update `docs/spec.md`: Data stores table (MinIO → SeaweedFS), Backend table (remove `minio` row)
- [x] 9.2 Update `docs/architecture.md`: all MinIO references → SeaweedFS in mermaid diagrams, Docker Compose table, data stores section, backup/recovery section
- [x] 9.3 Update `docs/rag.md`: "reference to the file in MinIO" → "reference to the file in SeaweedFS"
- [x] 9.4 Update `CLAUDE.md`: Tech Stack (MinIO → SeaweedFS)
- [x] 9.5 Update `AGENTS.md`: replace MinIO references if present
- [x] 9.6 Update `README.md`: replace MinIO references if present

## 10. Verification

- [x] 10.1 Run `uv run pytest` — all tests pass
- [x] 10.2 Run `uv run ruff check` — no lint errors
- [ ] 10.3 Run `docker-compose up` — SeaweedFS service healthy, API ready
- [ ] 10.4 Upload a source via `POST /api/admin/sources` — file stored in SeaweedFS
- [x] 10.5 Run `grep -ri minio backend/ docs/ CLAUDE.md AGENTS.md README.md docker-compose.yml .env.example` — zero matches in runtime code and canonical docs (openspec change artifacts are excluded from this check as they document the migration itself)
