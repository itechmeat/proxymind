## 1. Rollback — Service Method

- [x] 1.1 Fix `_create_snapshot` helper to preserve `activated_at` for PUBLISHED status in both `test_snapshot_lifecycle.py` and `test_snapshot_api.py`
- [x] 1.2 Write rollback service tests: happy path, non-active error, no previous error, not found, toggle behavior (rollback twice alternates between same two snapshots), scope isolation (target selected only within current snapshot's agent_id/knowledge_base_id)
- [x] 1.3 Implement `SnapshotService.rollback()` with scope derived from locked current snapshot and auto-target selection by `activated_at`
- [x] 1.4 Run all snapshot lifecycle tests — verify pass

## 2. Rollback — API Endpoint

- [x] 2.1 Add `RollbackResponse` schema to `snapshot_schemas.py`
- [x] 2.2 Write rollback API tests (200, 404, 409 non-active, 409 no previous, concurrent race)
- [x] 2.3 Implement `POST /api/admin/snapshots/{snapshot_id}/rollback` endpoint with error mapping via `_raise_snapshot_http_error`
- [x] 2.4 Run all snapshot API tests — verify pass

## 3. Draft Test — Schemas + Endpoint

- [x] 3.1 Add `DraftTestRequest` (with whitespace-trim validation), `DraftTestResponse`, `DraftTestResult`, `DraftTestAnchor`, and `RetrievalMode` schemas to `snapshot_schemas.py`
- [x] 3.2 Add `get_embedding_service` dependency factory to `dependencies.py`; register mock `embedding_service` in test conftest
- [x] 3.3 Write validation tests (422 non-draft, 422 empty draft with zero indexed chunks, 404 unknown)
- [x] 3.4 Write happy-path unit tests with dependency overrides: hybrid mode, dense mode, sparse mode (skips embedding), text_content truncation to 500 Unicode characters
- [x] 3.5 Implement `POST /api/admin/snapshots/{snapshot_id}/test` endpoint calling `QdrantService` directly (bypassing `RetrievalService`), with mode-based dispatch and source title enrichment
- [x] 3.6 Run all draft test tests — verify pass

## 4. Source Soft Delete — Service

- [x] 4.1 Create `_create_source`, `_create_doc_version`, and `_create_chunk_in_snapshot` test helpers with proper FK setup in `test_source_soft_delete.py`
- [x] 4.2 Write soft delete service tests: draft-only cascade, published warnings, mixed draft+published (draft cleaned, published preserved, warnings returned), idempotent re-delete, not found, dual-field contract (both status=DELETED and deleted_at set), scoped lookup (404 for source in different scope)
- [x] 4.3 Implement `SourceDeleteService` in `source_delete.py` with scope-aware lookup, dual-field contract (`status` + `deleted_at`), Qdrant-first cascade for draft chunks, and published/active chunk warnings
- [x] 4.4 Run all soft delete tests — verify pass

## 5. Source Soft Delete — API Endpoint

- [x] 5.1 Create `SourceDeleteResponse` schema in `source_schemas.py`
- [x] 5.2 Write API tests: 200 with response body validation, 404 for unknown source, idempotent delete (200 with empty warnings for already-deleted source)
- [x] 5.3 Implement `DELETE /api/admin/sources/{source_id}` endpoint wiring `SourceDeleteService` with `QdrantService`
- [x] 5.4 Run all soft delete API tests — verify pass

## 6. Ingestion Guard

- [x] 6.1 Write ingestion guard tests: deleted source → task FAILED with descriptive message; non-deleted source passes guard normally; verify guard fires before `_load_pipeline_services()` (services not initialized for deleted sources)
- [x] 6.2 Add source status guard in `_process_task()` before `_load_pipeline_services()` — return early for `DELETED` sources
- [x] 6.3 Run full test suite — verify pass

## 7. Final Verification

- [x] 7.1 Run full test suite (`python -m pytest tests/ -v`)
- [x] 7.2 Run linter (`ruff check .`)
- [x] 7.3 Verify no regressions in existing snapshot lifecycle and API endpoints
- [x] 7.4 Re-read `docs/development.md` and self-review against standards
- [x] 7.5 Verify all installed package versions at or above `docs/spec.md` minimums
