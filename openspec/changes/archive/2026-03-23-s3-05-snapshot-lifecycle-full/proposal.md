## Story

**S3-05: Snapshot lifecycle (full)** — Rollback to previous published, draft testing via Admin API, soft delete source considering published snapshots.

**Verification:** Publish → rollback → the twin (the assistant instance) responds from the old snapshot; test draft → only draft chunks visible; delete source → draft chunks removed, published chunks preserved.

**Stable behavior requiring test coverage:** Snapshot state machine transitions (S2-03), publish guards, activate/deactivate logic, hybrid retrieval scoped by snapshot_id, ingestion pipeline source status handling.

## Why

The snapshot lifecycle is incomplete. Owners can publish and activate snapshots but cannot undo an activation, cannot verify draft content before publishing, and cannot remove sources without leaving stale data in drafts. These gaps block confident knowledge management — an owner who activates a bad snapshot has no rollback, an owner who wants to preview retrieval quality must publish first, and an owner who deletes a source leaves ghost chunks in the next snapshot. S3-05 closes all three gaps.

## What Changes

- New `rollback()` method on `SnapshotService`: demotes the active snapshot to published and re-activates the most recently demoted published snapshot (by `activated_at`). If no previously activated published snapshot exists in the same scope, rollback fails with `409 Conflict`. Repeated rollback toggles between the two most recent snapshots; deeper history traversal uses the existing `activate` endpoint.
- New `POST /api/admin/snapshots/{snapshot_id}/test` endpoint: retrieval-only search (no LLM pass) scoped to a draft snapshot. Supports hybrid, dense, and sparse modes. Returns raw chunks with scores and metadata for quality verification.
- New `DELETE /api/admin/sources/{source_id}` endpoint: soft delete (sets `status=DELETED` + `deleted_at`). Cascades chunk removal to draft snapshots (both Qdrant and PostgreSQL). Published/active snapshot chunks remain untouched. Returns warnings in the JSON response body as a top-level `warnings: string[]` array when chunks persist in published/active snapshots.
- Ingestion worker gains a source status guard: tasks for deleted sources are failed immediately instead of processing stale data.

## Capabilities

### New Capabilities

- `snapshot-rollback`: Undo last activation by auto-selecting the previous published snapshot. Row-level locking on both active and target rows. Toggle semantics on repeated rollback.
- `draft-testing`: Retrieval-only search against draft snapshots via Admin API. Calls `QdrantService` search methods directly (bypasses `RetrievalService`). Supports hybrid/dense/sparse modes. Truncated text_content in response (500 chars).
- `source-soft-delete`: Soft delete with dual-field contract (`status=DELETED` + `deleted_at`). Draft chunk cascade (Qdrant + PostgreSQL). Published chunk preservation. Idempotent on already-deleted sources. Warning-based transparency via a non-blocking `warnings` array in the success response; no confirmation or force flag.

### Modified Capabilities

- `snapshot-lifecycle`: Add `ACTIVE -> PUBLISHED` rollback transition with auto-target selection. Existing state machine unchanged — rollback is a new entry point that reuses the deactivation pattern.
- `ingestion-pipeline`: Add source status check at task start. Tasks for deleted sources fail immediately with descriptive reason. No changes to the processing path itself.

## Impact

- **New files:** `app/services/source_delete.py`, `app/api/source_schemas.py`, `tests/integration/test_source_soft_delete.py`
- **Modified files:** `app/services/snapshot.py`, `app/api/admin.py`, `app/api/snapshot_schemas.py`, `app/api/dependencies.py`, `app/workers/tasks/ingestion.py`, `tests/integration/test_snapshot_lifecycle.py`, `tests/integration/test_snapshot_api.py`
- **API:** Three new endpoints (rollback, draft test, source delete). No changes to existing endpoints.
- **Database:** No migrations. Uses existing `status` enum values and `deleted_at` column from `SoftDeleteMixin`.
- **Qdrant:** Uses existing `delete_chunks()` for draft cascade. No schema changes.
