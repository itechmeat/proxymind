# S2-05: Replace MinIO with SeaweedFS

## Motivation

MinIO is deprecated and MUST be fully removed from the project. All references to the MinIO server, the `minio` Python SDK, and MinIO-specific configuration MUST be replaced.

SeaweedFS is chosen as the replacement object storage backend. It is actively maintained, lightweight, and provides a simple Filer HTTP API that fits ProxyMind's needs.

## Position in Plan

S2-05 is inserted between S2-04 (Minimal chat) and S3-01 (More formats). It is a prerequisite-free infrastructure swap — all existing functionality (upload, download, delete, ensure storage) is preserved with no behavioral changes for consumers.

## Decisions

### Decision 1: Python Client — httpx + SeaweedFS Filer HTTP API

**Chosen:** Use `httpx` (already a project dependency) to call the SeaweedFS Filer HTTP API directly.

**Rejected alternatives:**

- **(A) Keep `minio` Python SDK as S3 client:** MinIO is deprecated; keeping the SDK contradicts the removal mandate even though it is technically an S3-compatible client.
- **(B) `boto3` / `aioboto3` via S3 Gateway:** Heavy dependency (~70 MB with `botocore`), requires S3 Gateway configuration, overkill for four operations (upload, download, delete, ensure directory).
- **(C) `aiobotocore` via S3 Gateway:** Lighter than `boto3` but still pulls `botocore` (~50 MB) and requires S3 Gateway.

**Rationale:**
- Zero new dependencies — `httpx` is already in `pyproject.toml`.
- Native async — no `asyncio.to_thread` wrappers needed (the current MinIO SDK is synchronous and wrapped).
- KISS/YAGNI — SeaweedFS Filer API for four operations is simple HTTP: POST (upload), GET (download), DELETE (delete), POST (ensure directory).
- S3 portability is not a requirement — self-hosted project with a single storage backend. `StorageService` already abstracts the storage interface; swapping the implementation later changes only one file.

**Technical note:** SeaweedFS Filer uses POST for file uploads (not PUT). The upload sends multipart form data to `POST /path/to/file`.

### Decision 2: Topology — `weed server -filer` (all-in-one)

**Chosen:** Run master + volume + filer in a single process via `weed server -filer`.

**Rejected alternatives:**

- **(B) Separate containers for master + volume + filer:** Production-grade horizontal scaling, but 3 containers instead of 1. ProxyMind architecture is "one instance = one twin" — horizontal storage scaling is not in scope.
- **(C) `weed server` + separate filer:** A compromise that provides no real advantage over (A) at ProxyMind's scale.

**Rationale:**
- Single container, single healthcheck, single Docker volume.
- Sufficient for the expected data volumes (books, PDFs, markdown files — not video hosting).
- Migration to separate containers is trivial if needed — same data on the same volume, only topology changes.

### Decision 3: Filer Metadata Backend — LevelDB (default)

**Chosen:** Use the built-in LevelDB store for Filer metadata.

**Rejected alternative:** PostgreSQL as the Filer metadata backend (reduces backup targets to one).

**Rationale:**
- Minimal coupling — SeaweedFS manages its own metadata independently.
- No additional load on PostgreSQL.
- LevelDB data lives inside the same Docker volume as volume server data — one volume to back up.
- Migration to PostgreSQL backend is possible later via `filer.toml` without data loss.

### Decision 4: Config Naming — `SEAWEEDFS_*`

**Chosen:** Environment variables named `SEAWEEDFS_HOST`, `SEAWEEDFS_FILER_PORT`, `SEAWEEDFS_SOURCES_PATH`.

**Rejected alternatives:**

- **(B) `STORAGE_*`:** Too abstract — at debug time it is unclear which service `STORAGE_HOST` refers to.
- **(C) `S3_*`:** Misleading — the project uses Filer API, not S3 API.

**Rationale:** Consistent with existing naming pattern: `POSTGRES_*`, `REDIS_*`, `QDRANT_*` — all named after the specific tool. Self-hosted project; storage replacement is a rare event warranting its own story.

### Decision 5: No Authentication for Filer (v1)

SeaweedFS Filer runs without JWT authentication in v1. Access is restricted by Docker network isolation — only `api` and `worker` containers reach the Filer endpoint. This matches the current MinIO setup (root credentials in `.env`, no TLS, Docker-internal access).

If JWT is needed later, it requires one new config field (`SEAWEEDFS_JWT_SECRET`) and an `Authorization: Bearer` header in `StorageService`.

### Decision 6: No S3 Gateway

The S3 Gateway is not deployed. While SeaweedFS supports `weed filer -s3` (S3 embedded in the same process), it is unnecessary overhead when the Filer HTTP API covers all required operations. This also means no IAM configuration, no bucket-to-directory mapping concerns, and no S3 request signing.

**Note from user review:** The "S3 Gateway requires a separate process" argument is not universally true — `weed filer -s3` runs S3 within the filer process. However, even embedded S3 adds configuration surface (IAM, bucket mapping) that is not justified for four HTTP operations.

### Decision 7: Rename `ensure_bucket` → `ensure_storage_root`

In MinIO, `ensure_bucket` creates an S3 bucket. In SeaweedFS Filer, there are no buckets — "bucket = directory in Filer namespace." Keeping the name `ensure_bucket` would be false S3 terminology in a project that no longer uses S3.

The method is renamed to `ensure_storage_root()` — a storage-agnostic name that accurately describes the operation: "ensure the root path for file storage exists and is accessible." The implementation becomes a `POST` to the base path directory, which creates the directory if it does not exist. Filer also auto-creates intermediate directories on file upload, but the explicit ensure at startup validates Filer availability.

All call sites (`main.py`, `workers/main.py`, tests) update from `ensure_bucket()` to `ensure_storage_root()`.

This is a tighter coupling to SeaweedFS semantics than S3 bucket API, which is an accepted trade-off for a self-hosted project with the storage interface abstracted behind `StorageService`.

### Decision 8: Separate httpx.AsyncClient for Storage

The application already has a generic `app.state.http_client` (timeout=5s, no base_url) used for health checks (`/ready` probes to Qdrant, SeaweedFS). StorageService needs a **separate** `httpx.AsyncClient` with:

- `base_url=settings.seaweedfs_filer_url` — so StorageService methods use relative paths
- `timeout=30.0` — large file uploads (up to 50 MB) need more than 5s

Reusing the generic client would require passing full URLs everywhere and would constrain timeout for either health checks (too long) or uploads (too short).

Both clients MUST be properly managed:
- **API process (`main.py`):** `storage_http_client` stored in `app.state`, added to `_close_app_resources` shutdown list with `aclose`.
- **Worker process (`workers/main.py`):** `storage_http_client` stored in worker `ctx` dict, `aclose()` called in `on_shutdown`. This is a new resource for the worker — the current MinIO SDK is synchronous and does not require async lifecycle management.

### Decision 9: Two-Layer Health Checks

The Docker Compose healthcheck and the application readiness check (`/ready`) serve different purposes and MUST check different things:

- **Docker Compose healthcheck** — coarse liveness of the SeaweedFS process. Uses `GET /cluster/healthz` on master port (9333). This gates `depends_on` — ensures the container is running before `api`/`worker` start.
- **Application readiness (`/ready` in `health.py`)** — verifies the actual Filer HTTP API is reachable. The current check calls `GET {minio_url}/minio/health/live`; this changes to `GET {seaweedfs_filer_url}/` (Filer root directory listing — lightweight, confirms Filer is serving requests). This uses the generic `app.state.http_client`, not the storage client.

The `"minio"` key in readiness results changes to `"seaweedfs"`. Settings reference changes from `settings.minio_url` to `settings.seaweedfs_filer_url`.

## Scope

### In scope

1. Remove `minio` Python SDK from dependencies.
2. Replace Docker Compose service `minio` with `seaweedfs`.
3. Rewrite `StorageService` implementation using `httpx` + Filer HTTP API.
4. Rename `ensure_bucket()` → `ensure_storage_root()` across codebase.
5. Replace configuration: `MINIO_*` env vars and config fields with `SEAWEEDFS_*`.
6. Update initialization and lifecycle in `main.py` (separate storage httpx client, shutdown).
7. Update initialization and lifecycle in `workers/main.py` (new httpx client creation and shutdown).
8. Update readiness check in `health.py` (`"minio"` → `"seaweedfs"`, Filer-level probe).
9. Update all tests (unit tests, conftest, config tests, health tests, lifespan tests).
10. Update documentation: `spec.md`, `architecture.md`, `plan.md`, `rag.md`, `CLAUDE.md`, `AGENTS.md`, `README.md`.

### Out of scope

- S3 Gateway deployment.
- Data migration (Phase 2 dev environment — data is recreated via upload).
- JWT/security for Filer (v1 uses Docker network isolation).
- Retry decorators on storage operations (documented as future TODO for production-readiness).

## Infrastructure

### Docker Compose

```yaml
seaweedfs:
  image: chrislusf/seaweedfs:latest
  command: server -filer -dir=/data -master.port=9333 -filer.port=8888 -volume.port=9340
  ports:
    - "8888:8888"   # Filer HTTP API (primary — StorageService connects here)
    - "9333:9333"   # Master (healthcheck + diagnostics)
  volumes:
    - seaweedfs-data:/data
  healthcheck:
    test: ["CMD-SHELL", "wget -qO- http://localhost:9333/cluster/healthz || exit 1"]
    interval: 15s
    timeout: 10s
    retries: 10
    start_period: 20s
```

Port `9340` (volume server) is not exposed — Filer communicates with it internally.

**Docker Compose healthcheck** uses `GET /cluster/healthz` on the master endpoint (port 9333). This is a coarse liveness check confirming the `weed server` process is running. It gates `depends_on` for `api` and `worker` containers.

**Application readiness** (`/ready` in `health.py`) performs a separate Filer-level check: `GET {seaweedfs_filer_url}/` via the generic `http_client`. This verifies the Filer HTTP API is actually serving requests — not just that the master is alive. See Decision 9.

Services `api` and `worker` change dependency from `minio: condition: service_healthy` to `seaweedfs: condition: service_healthy`.

Volume `minio-data` is replaced by `seaweedfs-data`.

## StorageService

### Interface

The interface changes in one place: `ensure_bucket()` is renamed to `ensure_storage_root()` to remove false S3 terminology (see Decision 7). All other method signatures remain the same. Consumers (`admin.py`, `workers/tasks.py`) update the single call site.

```python
class StorageService:
    def __init__(self, http_client: httpx.AsyncClient, base_path: str) -> None: ...

    @staticmethod
    def generate_object_key(agent_id: UUID, source_id: UUID, filename: str) -> str: ...

    async def ensure_storage_root(self) -> None: ...
    async def upload(self, object_key: str, content: bytes, content_type: str | None = None) -> None: ...
    async def download(self, object_key: str) -> bytes: ...
    async def delete(self, object_key: str) -> None: ...
```

### Implementation mapping

| Method | MinIO SDK (before) | Filer HTTP API (after) |
|--------|-------------------|----------------------|
| `ensure_storage_root` (was `ensure_bucket`) | `client.make_bucket(name)` via `asyncio.to_thread` | `POST {base_path}/` — creates directory, validates Filer availability |
| `upload` | `client.put_object(bucket, key, stream, length)` via `asyncio.to_thread` | `POST {base_path}/{key}` with multipart file |
| `download` | `client.get_object(bucket, key).read()` via `asyncio.to_thread` | `GET {base_path}/{key}` — returns bytes |
| `delete` | `client.remove_object(bucket, key)` via `asyncio.to_thread` | `DELETE {base_path}/{key}` |

All methods become natively async (no `asyncio.to_thread` wrappers).

### Constructor and lifecycle

`http_client` is injected from outside (Dependency Inversion). A **dedicated** `httpx.AsyncClient` is created for storage in both `main.py` and `workers/main.py` with `base_url=settings.seaweedfs_filer_url` and `timeout=30.0` (for large file uploads up to 50 MB). This is separate from the generic `app.state.http_client` (timeout=5s, no base_url) used for health checks. See Decision 8 for rationale.

**API process (`main.py`):**
- `storage_http_client` stored in `app.state.storage_http_client`.
- Added to `_close_app_resources` shutdown list: `("storage_http_client", "aclose", "app.shutdown.storage_http_client_close_failed")`.

**Worker process (`workers/main.py`):**
- `storage_http_client` stored in `ctx["storage_http_client"]`.
- `aclose()` called in `on_shutdown`. This is a **new lifecycle responsibility** — the current MinIO SDK is synchronous and does not require async cleanup in the worker.

### Path normalization

`seaweedfs_sources_path` has a canonical form: **leading slash, no trailing slash** (e.g., `/sources`). The `StorageService` constructor normalizes the input: strips trailing slashes, ensures leading slash.

URL construction uses a private helper `_build_url(object_key: str) -> str` that joins `base_path` and `object_key` with a single `/` separator. This prevents double-slash or missing-slash issues with httpx URL resolution.

Tests MUST cover edge cases: `base_path` with/without trailing slash, `object_key` with/without leading slash.

### Error handling

`resp.raise_for_status()` raises `httpx.HTTPStatusError` on non-2xx responses. Calling code already handles storage errors via generic `except Exception`. Specific handling (e.g., 404 on download) can be refined in a future story.

### Helpers

`generate_object_key` and filename sanitization functions (`sanitize_filename`, `validate_file_extension`, `determine_source_type`) remain unchanged — they are storage-agnostic.

## Configuration

### Config fields

| Removed | Added | Default | Description |
|---------|-------|---------|-------------|
| `minio_host` | `seaweedfs_host` | — (required) | SeaweedFS hostname |
| `minio_port` | `seaweedfs_filer_port` | `8888` | Filer HTTP API port |
| `minio_root_user` | — | — | Not needed (no auth in v1) |
| `minio_root_password` | — | — | Not needed |
| `minio_bucket_sources` | `seaweedfs_sources_path` | `/sources` | Root path in Filer namespace |
| `minio_url` (computed) | `seaweedfs_filer_url` (computed) | — | `http://{host}:{port}` |

### .env.example

```env
SEAWEEDFS_HOST=seaweedfs
SEAWEEDFS_FILER_PORT=8888
```

## Tests

### Unit tests for StorageService (`test_storage_download.py` → rename to `test_storage.py`)

Full rewrite. Tests use `httpx.MockTransport` (built into httpx) to mock HTTP responses. Each test verifies:

- Correct HTTP method (POST for upload/ensure, GET for download, DELETE for delete)
- Correct URL path construction via `_build_url` helper
- Path normalization edge cases: `base_path` with/without trailing slash, `object_key` with/without leading slash
- `ensure_storage_root` sends POST to base path directory
- Correct `content_type` forwarding in multipart upload
- Correct handling of response body (download returns bytes)
- Correct error propagation (non-2xx raises `httpx.HTTPStatusError`)

### Lifespan tests (`test_app_main.py`)

Updates required:
- Replace `minio_*` settings fields with `seaweedfs_*` in `_settings()` fixture.
- Replace `monkeypatch.setattr(app_main, "Minio", ...)` with httpx client mock.
- Replace `StorageService` monkeypatch: constructor signature changes from `(client, bucket_name)` to `(http_client, base_path)`.
- Add assertion that `storage_http_client.aclose()` is called on startup failure cleanup.

### Health tests (`test_health.py`)

Updates required:
- `_build_health_app` settings: `minio_url` → `seaweedfs_filer_url`.
- Readiness key in degraded response: `"minio"` → `"seaweedfs"`.
- Timeout test assertion: `["postgres", "redis", "qdrant", "minio"]` → `["postgres", "redis", "qdrant", "seaweedfs"]`.

### Updated fixtures (`conftest.py`)

- `mock_storage_service`: `ensure_bucket` → `ensure_storage_root` in `SimpleNamespace`.
- `admin_app`: `minio_bucket_sources="sources"` → `seaweedfs_sources_path="/sources"` in settings.

### Config tests (`test_config.py`)

Update environment variable names from `MINIO_*` to `SEAWEEDFS_*`. Remove `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` (no longer needed).

### Worker shutdown test

Add a test verifying that the worker `on_shutdown` properly closes `storage_http_client` — this is a new lifecycle responsibility that did not exist with the synchronous MinIO SDK.

### No integration test with real SeaweedFS

Consistent with current approach — no MinIO container in CI either. `StorageService` is verified through unit tests with `MockTransport`. Integration with real SeaweedFS is validated manually via `docker-compose up`.

## Documentation Updates

| Document | Changes |
|----------|---------|
| `docs/spec.md` | Data stores table: MinIO → SeaweedFS. Backend table: remove `minio` row. |
| `docs/architecture.md` | All MinIO references → SeaweedFS in: 6 mermaid diagrams, Docker Compose table (image, port), data stores descriptions, backup/recovery section. |
| `docs/plan.md` | Add S2-05 story definition. Update MinIO mentions in S1-01, S2-01, S5-06. |
| `docs/rag.md` | "reference to the file in MinIO" → "reference to the file in SeaweedFS" (2 occurrences). |
| `CLAUDE.md` | Tech Stack: MinIO → SeaweedFS. |
| `AGENTS.md` | Replace MinIO references if present. |
| `README.md` | Replace MinIO references if present. |

### Backup and recovery

Current: `mc mirror / bucket replication` for MinIO.
New: `weed filer.backup` or Docker volume snapshot for SeaweedFS.

Recovery principle unchanged: PostgreSQL is source of truth. SeaweedFS stores files. Qdrant can be reindexed from PostgreSQL + SeaweedFS.

## Dependencies

| Action | Package | Reason |
|--------|---------|--------|
| **Remove** | `minio >= 7.2.0` | Deprecated, fully replaced |
| Keep | `httpx >= 0.28.1` | Already present, now used as SeaweedFS client |
| Keep | `tenacity >= 9.1.4` | Already present, available for future retries |

Net result: zero new dependencies, one dependency removed.

## Files Affected

**Infrastructure:**
- `docker-compose.yml` — replace `minio` service with `seaweedfs`
- `.env.example` — `MINIO_*` → `SEAWEEDFS_*`

**Dependencies:**
- `backend/pyproject.toml` — remove `minio`, run `uv lock`
- `backend/uv.lock` — regenerated

**Application code:**
- `backend/app/core/config.py` — new config fields, remove old
- `backend/app/services/storage.py` — full rewrite, rename `ensure_bucket` → `ensure_storage_root`
- `backend/app/main.py` — new StorageService init, storage_http_client lifecycle, shutdown
- `backend/app/workers/main.py` — new StorageService init, storage_http_client lifecycle, shutdown
- `backend/app/api/health.py` — `"minio"` check → `"seaweedfs"` Filer-level probe

**Tests:**
- `backend/tests/conftest.py` — fixtures: settings, mock_storage_service
- `backend/tests/unit/test_config.py` — env var names
- `backend/tests/unit/test_app_main.py` — lifespan mocks, settings, shutdown assertions
- `backend/tests/unit/services/test_storage_download.py` — full rewrite (rename to `test_storage.py`)
- `backend/tests/test_health.py` — settings, readiness keys

**Documentation:**
- `docs/spec.md`, `docs/architecture.md`, `docs/plan.md`, `docs/rag.md`
- `CLAUDE.md`, `AGENTS.md`, `README.md`

Skills used: superpowers:brainstorming, seaweedfs (skill references)
Docs used: SeaweedFS Filer Core, API Surfaces, Getting Started, Quick Start Mini, Topology and Setup, Configuration (from .agents/skills/seaweedfs/references/)
