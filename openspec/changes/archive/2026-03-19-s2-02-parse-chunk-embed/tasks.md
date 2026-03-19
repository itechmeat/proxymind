# S2-02: Parse + Chunk + Embed — Tasks

> Full implementation plan: `docs/superpowers/plans/2026-03-18-s2-02-parse-chunk-embed.md`
> Design spec: `docs/superpowers/specs/2026-03-18-s2-02-parse-chunk-embed-design.md`

## 1. Dependencies and Configuration

- [x] 1.1 Add `docling>=2.80.0`, `google-genai>=1.14.0`, `qdrant-client>=1.14.0` to `backend/pyproject.toml` and run `uv sync`
- [x] 1.2 Add Settings fields to `backend/app/core/config.py`: `gemini_api_key`, `embedding_model`, `embedding_dimensions`, `embedding_batch_size`, `chunk_max_tokens`, `qdrant_collection`, `bm25_language`
- [x] 1.3 Verify settings load correctly: `python -c "from app.core.config import get_settings; s = get_settings(); print(s.embedding_dimensions, s.qdrant_collection)"`

## 2. Database Migration

- [x] 2.1 Add `language: Mapped[str | None]` column to Source model in `backend/app/db/models/knowledge.py`
- [x] 2.2 Create Alembic migration: `language` column on `sources` + partial unique index `uq_one_draft_per_scope` on `knowledge_snapshots`
- [x] 2.3 Run migration and verify: `alembic upgrade head && alembic check`

## 3. StorageService.download()

- [x] 3.1 Write failing test for `StorageService.download()` in `backend/tests/unit/services/test_storage_download.py`
- [x] 3.2 Implement `download(object_key: str) -> bytes` in `backend/app/services/storage.py` using `asyncio.to_thread`
- [x] 3.3 Run test and verify it passes

## 4. DoclingParser Service

- [x] 4.1 Create test fixtures: `backend/tests/fixtures/sample.md`, `sample_small.md`, `sample.txt`
- [x] 4.2 Write failing tests for DoclingParser in `backend/tests/unit/services/test_docling_parser.py` (parse MD/TXT, anchor extraction, empty content, sequential indices)
- [x] 4.3 Implement `DoclingParser` with `ChunkData` dataclass in `backend/app/services/docling_parser.py` — verify Docling API against installed version
- [x] 4.4 Run tests and verify they pass

## 5. EmbeddingService

- [x] 5.1 Write failing tests for EmbeddingService in `backend/tests/unit/services/test_embedding.py` (single text, batching, empty input, retry on transient error)
- [x] 5.2 Implement `EmbeddingService` in `backend/app/services/embedding.py` with batch embedding + tenacity retry — verify Google GenAI SDK API against installed version
- [x] 5.3 Run tests and verify they pass

## 6. QdrantService

- [x] 6.1 Write failing unit tests in `backend/tests/unit/services/test_qdrant.py` (create collection, idempotent ensure, dimension mismatch, upsert)
- [x] 6.2 Implement `QdrantService` with `CollectionSchemaMismatchError` in `backend/app/services/qdrant.py` — named dense vector, payload indexes, dimension validation
- [x] 6.3 Run unit tests and verify they pass

## 7. SnapshotService

- [x] 7.1 Write failing tests in `backend/tests/integration/test_snapshot.py` (create draft, reuse existing, separate scopes)
- [x] 7.2 Implement `SnapshotService.get_or_create_draft()` in `backend/app/services/snapshot.py` using INSERT ON CONFLICT DO NOTHING
- [x] 7.3 Run tests and verify they pass

## 8. Source Language Persistence

- [x] 8.1 Write failing test in `backend/tests/integration/test_source_upload.py` verifying `source.language` is persisted
- [x] 8.2 Fix `SourceService.create_source_and_task()` in `backend/app/services/source.py` to pass `language=metadata.language` to Source constructor
- [x] 8.3 Run test and verify it passes

## 9. Worker Ingestion Pipeline

- [x] 9.1 Update existing tests in `backend/tests/integration/test_ingestion_worker.py` to provide mocked services in worker context
- [x] 9.2 Write pipeline success test: verify Document, DocumentVersion, Chunks created, progress=100, result_metadata populated
- [x] 9.3 Write pipeline failure test: mock embedding_service to raise, verify all records marked FAILED, Qdrant not called
- [x] 9.4 Implement `_run_ingestion_pipeline()` in `backend/app/workers/tasks/ingestion.py` replacing `_run_noop_ingestion` — two transaction boundaries (Tx 1: persist, Tx 2: finalize)
- [x] 9.5 Run all ingestion worker tests and verify they pass

## 10. Worker Startup

- [x] 10.1 Add service initialization in `backend/app/workers/main.py` `on_startup()`: StorageService, QdrantService (with ensure_collection), EmbeddingService, settings
- [x] 10.2 Add `close()` method to QdrantService and call it in `on_shutdown()`
- [x] 10.3 Update `backend/app/services/__init__.py` to export new services
- [x] 10.4 Add `knowledge_snapshots` to `TRUNCATE_TEST_DATA_SQL` in `backend/tests/conftest.py`

## 11. Integration Tests — Qdrant Round-Trip

- [x] 11.1 Add Qdrant testcontainer fixture to `backend/tests/conftest.py` (real Qdrant container, not in-memory — validates named vectors, payload indexes, and filter behavior at the actual server level)
- [x] 11.2 Write round-trip test in `backend/tests/integration/test_qdrant_roundtrip.py`: create collection → upsert points → filtered search by snapshot_id → verify payload
- [x] 11.3 Write dimension mismatch test: create with 3072 → ensure with 1024 → verify error
- [x] 11.4 Write idempotent ensure test: call ensure_collection twice → no error

## 12. Final Verification

- [x] 12.1 Run full test suite: `cd backend && python -m pytest tests/ -v --tb=short`
- [x] 12.2 Run linters: `ruff check . && ruff format --check .`
- [x] 12.3 Re-read `docs/development.md` and self-review the change against it
- [x] 12.4 Verify all installed package versions are ≥ minimums in `docs/spec.md`
- [ ] 12.5 Docker-compose smoke test (manual): upload MD → verify chunks in PG + Qdrant
