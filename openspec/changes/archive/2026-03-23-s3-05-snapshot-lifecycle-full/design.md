# S3-05: Snapshot Lifecycle (Full) — Design

## Story

> Rollback to previous published, draft testing via Admin API, soft delete source considering published snapshots.

**Outcome:** owners can undo activations, verify draft retrieval quality, and clean up sources without corrupting published data.

**Verification:** Publish then rollback — twin responds from the old snapshot; test draft — only draft chunks visible; delete source — draft chunks removed, published chunks preserved.

## Context

S2-03 delivered the core snapshot state machine: draft, published, active statuses with publish and activate transitions. The existing lifecycle has three gaps that block confident knowledge management:

1. **No rollback.** An owner who activates a bad snapshot has no undo. The only recovery is to manually find and re-activate the previous snapshot via the `activate` endpoint.
2. **No draft testing.** There is no way to verify retrieval quality before publishing. The owner must publish and activate a snapshot to see what the twin retrieves — making publishing a one-way bet.
3. **No source deletion.** Deleting a source leaves ghost chunks in draft snapshots. There is no cascade, no ingestion guard, and no warning about chunks persisting in published snapshots.

S3-05 closes all three gaps with three independent features. All changes are within the knowledge circuit; the dialogue circuit is unchanged.

## Goals / Non-Goals

### Goals

- Rollback the active snapshot to the previously activated published snapshot via `POST /api/admin/snapshots/{snapshot_id}/rollback`.
- Test retrieval against a draft snapshot (retrieval-only, no LLM) via `POST /api/admin/snapshots/{snapshot_id}/test` with support for hybrid, dense, and sparse modes.
- Soft delete a source via `DELETE /api/admin/sources/{source_id}` with cascade removal of chunks in draft snapshots, preservation of chunks in published/active snapshots, and warnings in the response.
- Guard the ingestion worker against processing tasks for deleted sources.

### Non-Goals

- **Archive endpoint** — the `ARCHIVED` enum exists but no endpoint is implemented (YAGNI, deferred).
- **Hard delete of sources** — separate operation per architecture.md.
- **Snapshot diff/comparison** — not required by the plan.
- **Rollback with explicit target** — use the existing `activate` endpoint for manual selection.
- **Test endpoint for published/active snapshots** — use the chat endpoint for active snapshots.

## Decisions

### D1: Draft test is retrieval-only (no LLM pass)

The test endpoint performs hybrid search against the draft snapshot and returns raw chunks with scores and metadata. No LLM generation.

**Rationale:** SSE streaming, citation builder, and persona loader are not yet fully implemented. The owner's goal is to verify that the right chunks are found and ranked correctly. Retrieval-only results are deterministic and testable in CI. A full chat-over-draft can be added later without changing this endpoint.

### D2: Rollback auto-selects previous; scope derived from locked current snapshot

`POST /api/admin/snapshots/{snapshot_id}/rollback` where `{snapshot_id}` is the currently ACTIVE snapshot. The system selects the rollback target: the PUBLISHED snapshot with the most recent `activated_at` in the same scope (`agent_id`, `knowledge_base_id`). Scope is derived from the locked current snapshot, not from query parameters alone, to prevent cross-scope rollback.

**Toggle behavior:** Because the rolled-back-to snapshot gets a new `activated_at = now()`, a second rollback re-selects the snapshot that was just demoted. This creates a toggle between the two most recent snapshots. Deeper history traversal uses the existing `activate` endpoint.

**Rejected:** `:id` = target PUBLISHED snapshot (identical to `activate`). `:id` = active + optional `target_snapshot_id` in body (overcomplicates the API).

### D3: Soft delete returns warnings, not blocking

`DELETE /api/admin/sources/{source_id}` always succeeds. If the source has chunks in published/active snapshots, the response includes a `warnings` array. No confirmation flag required.

**Rationale:** Soft delete is inherently safe and reversible. Blocking adds UX friction without real protection. Silent deletion hides consequences. Warnings provide transparency without blocking the workflow.

### D4: Draft chunk cascade with dual-field contract

When a source is soft-deleted, its chunks in DRAFT snapshots are removed from both Qdrant and PostgreSQL, and the draft's `chunk_count` is decremented. Chunks in PUBLISHED/ACTIVE snapshots remain untouched.

**Dual-field contract:** Both `status = DELETED` and `deleted_at = now()` MUST be set together. The authoritative signal for queries is `status == DELETED`. The `deleted_at` field records the timestamp for audit. Code MUST NOT check only one field without the other.

**Rationale:** Architecture.md states chunks from a deleted source are excluded from future snapshots but remain in already published ones. Draft snapshots represent future content. Published/active snapshots are immutable.

### D5: Archive endpoint deferred (YAGNI)

The `ARCHIVED` status enum already exists. No archive endpoint is implemented in S3-05. The published pool is sufficient for rollback. Archiving is a cleanup operation that can be added when needed.

### Data store ordering: Qdrant first, then PG commit

Draft chunk cascade deletes from Qdrant before committing the PostgreSQL transaction. If Qdrant succeeds but PG fails, chunks remain in PostgreSQL without vectors — orphaned but safe (not served to users). If PG is committed first and Qdrant fails, stale vectors remain searchable in draft. Qdrant-first is the safer failure mode.

### Ingestion guard placement

The source status check is placed in the ingestion worker at task start (`_process_task`), before any processing begins. Tasks for deleted sources are marked FAILED with a descriptive reason. No changes to the processing path itself.

## Architecture

### Rollback flow

```
POST /api/admin/snapshots/{snapshot_id}/rollback
  1. SELECT snapshot WHERE id = {id} FOR UPDATE
  2. Assert status == ACTIVE
  3. Derive scope from locked snapshot (agent_id, knowledge_base_id)
  4. SELECT target: PUBLISHED + same scope + most recent activated_at, FOR UPDATE
  5. current.status = PUBLISHED (keep activated_at for history)
  6. target.status = ACTIVE, target.activated_at = now()
  7. UPDATE agents SET active_snapshot_id = target.id
  8. COMMIT
```

Row-level locks (`FOR UPDATE`) on both rows prevent concurrent rollback/activate races. Same pattern as existing `activate()`.

### Draft test flow

The test handler calls `QdrantService` search methods directly (hybrid, dense, or keyword) rather than going through `RetrievalService`. `RetrievalService` always performs hybrid search scoped to the active snapshot — neither behavior is appropriate for draft testing. `EmbeddingService` generates the query embedding for dense and hybrid modes.

### Source soft delete flow

```
DELETE /api/admin/sources/{source_id}
  1. Load source by id + scope
  2. If already DELETED → idempotent 200
  3. Set status = DELETED, deleted_at = now()
  4. Draft chunks: delete from Qdrant (batch by chunk_ids), delete from PG, decrement chunk_count
  5. Published/active chunks: count distinct affected snapshots for warnings, do not modify chunks
  6. COMMIT
  7. Return source + warnings
```

### New and modified components

| Component | Location | Responsibility |
|-----------|----------|---------------|
| **SnapshotService.rollback()** | `app/services/snapshot.py` | Demote active, re-activate previous published |
| **SourceDeleteService** | `app/services/source_delete.py` | Soft delete with draft cascade and warnings |
| **Rollback endpoint** | `app/api/admin.py` | `POST /api/admin/snapshots/{snapshot_id}/rollback` |
| **Draft test endpoint** | `app/api/admin.py` | `POST /api/admin/snapshots/{snapshot_id}/test` |
| **Source delete endpoint** | `app/api/admin.py` | `DELETE /api/admin/sources/{source_id}` |
| **Pydantic schemas** | `app/api/snapshot_schemas.py`, `app/api/source_schemas.py` | Request/response models |
| **Ingestion guard** | `app/workers/tasks/ingestion.py` | Source status check at task start |

### Configuration

No new configuration settings. No database migrations. Uses existing `status` enum values and `deleted_at` column from `SoftDeleteMixin`.

## Risks / Trade-offs

### Rollback toggle behavior

Repeated rollback alternates between two snapshots because each activation updates `activated_at`. This is intentional — rollback is "undo last activation," not history traversal. To reach older snapshots, the owner uses the `activate` endpoint with an explicit ID. The toggle behavior could surprise an owner who expects rollback to go further back each time, but it matches the "undo" mental model.

### Qdrant-first ordering on draft cascade

If Qdrant deletion succeeds but the PostgreSQL transaction fails, chunk rows remain in PostgreSQL without corresponding vectors. These are orphaned but safe — they are not served to users because retrieval goes through Qdrant. The reverse (PG committed, Qdrant vectors still present) would leave stale vectors searchable in drafts, which is worse.

### Draft test CI testing requires dependency overrides

The draft test handler calls `QdrantService` and `EmbeddingService` directly (not through `RetrievalService`). Integration tests need to wire these dependencies into the test endpoint. This is manageable through FastAPI dependency overrides but adds test setup complexity compared to endpoints that use standard service injection.

### No LLM pass in draft test

Draft testing returns raw retrieval results. An owner cannot verify how the LLM would synthesize an answer from draft chunks. This is acceptable because SSE streaming and citation building are not yet fully wired, and retrieval quality is the primary concern at this stage. A full chat-over-draft endpoint can be layered on later.

## Testing strategy

### CI tests (deterministic, no external providers)

**Rollback:**
- Publish A, activate A, publish B, activate B, rollback — A is active, B is published
- Rollback with no previously activated snapshot — 409
- Rollback on non-active snapshot — 409
- Rollback on non-existent snapshot — 404

**Draft test:**
- Create draft, ingest sources, test query (hybrid) — verify chunks returned with scores
- Test query (dense only) — results from dense search
- Test query (sparse only) — results from BM25 search
- Test on non-draft snapshot — 422
- Test on draft with 0 indexed chunks — 422
- Test on non-existent snapshot — 404

**Source soft delete:**
- Delete source with chunks only in draft — chunks removed from PG + Qdrant, chunk_count decremented
- Delete source with chunks in published snapshot — source DELETED, published chunks untouched, warnings returned
- Delete source with chunks in both draft and published — draft cleaned up, published preserved, warnings
- Delete already-deleted source — idempotent 200
- Delete non-existent source — 404
- Ingestion worker picks up task for deleted source — task FAILED

## Files changed

| File | Change |
|------|--------|
| `backend/app/services/snapshot.py` | Add `rollback()` method |
| `backend/app/services/source_delete.py` | **New** — soft delete with draft cascade |
| `backend/app/api/admin.py` | Add rollback, test, and delete source endpoints |
| `backend/app/api/snapshot_schemas.py` | Add `RollbackResponse`, `DraftTestRequest`, `DraftTestResponse` |
| `backend/app/api/source_schemas.py` | **New** — `SourceDeleteResponse` schema |
| `backend/app/api/dependencies.py` | Wire new service dependencies |
| `backend/app/workers/tasks/ingestion.py` | Add source status guard at task start |
| `backend/tests/integration/test_snapshot_lifecycle.py` | Add rollback tests |
| `backend/tests/integration/test_snapshot_api.py` | Add rollback + draft test API tests |
| `backend/tests/integration/test_source_soft_delete.py` | **New** test file |

**Not affected:** Chat API, retrieval service, citation builder, ingestion processing path, frontend.
