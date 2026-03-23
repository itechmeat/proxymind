# S3-05: Snapshot Lifecycle (Full) — Design Spec

## Overview

Complete the snapshot lifecycle with three independent additions: rollback to a previous snapshot, draft testing via hybrid retrieval, and source soft delete with cascade to draft chunks. Each feature extends the existing `SnapshotService` and admin API without refactoring stable code.

### Scope

| Feature | Endpoint | Purpose |
|---------|----------|---------|
| Rollback | `POST /api/admin/snapshots/{id}/rollback` | Undo last activation — auto-select previous published |
| Draft test | `POST /api/admin/snapshots/{id}/test` | Retrieval-only search scoped to a draft snapshot |
| Source soft delete | `DELETE /api/admin/sources/{id}` | Soft delete with cascade to draft chunks, warnings for published |

### Out of Scope (YAGNI)

- Archive endpoint (enum exists, endpoint deferred)
- Hard delete of sources (separate operation per architecture.md)
- Snapshot diff/comparison
- Rollback with explicit target (use existing `activate` endpoint)
- Test endpoint for published/active snapshots (use chat for active)

---

## Decision Log

All decisions were made during brainstorming with rationale captured below.

### D1: Draft test — Retrieval-only (no LLM pass)

**Chosen:** The test endpoint performs hybrid search against the draft snapshot and returns raw retrieval results (chunks with scores and metadata). No LLM generation.

**Why:**
- YAGNI: at this stage, SSE streaming, citation builder, and persona loader are not yet fully implemented — a full chat pass is not available.
- The owner's goal is to verify that the right chunks are found and ranked correctly. LLM generation adds cost and non-determinism without helping with that goal.
- Retrieval-only results are deterministic and testable in CI.
- A full chat-over-draft can be added later on top of the same scoped retrieval without changing this endpoint.

**Rejected alternative:**
- (B) Full chat pass — would require assembling prompt layers that don't exist yet, adds LLM cost per test query, and makes test results non-deterministic.

### D2: Rollback semantics — `:id` is the active snapshot, auto-select previous

**Chosen:** `POST /api/admin/snapshots/{id}/rollback` where `{id}` is the currently ACTIVE snapshot. The system automatically selects the rollback target: the PUBLISHED snapshot with the most recent `activated_at` in the same scope.

**Why:**
- The plan says "rollback to **previous** published" — the word "previous" implies auto-selection, not manual target specification.
- The `activate` endpoint already covers manual selection: `POST /api/admin/snapshots/{id}/activate` where `{id}` is a specific PUBLISHED snapshot. Rollback adds value only as a convenience "undo".
- `activated_at` is a reliable ordering key: when snapshot A is active and B is activated, A is demoted to PUBLISHED but retains its `activated_at` timestamp. Among PUBLISHED snapshots, the one with the freshest `activated_at` is the most recently demoted — the natural rollback target.

**Toggle behavior on repeated rollback:** Because the rolled-back-to snapshot gets a new `activated_at = now()`, a second rollback will select the snapshot that was just demoted — creating a toggle between the two most recent snapshots. This is intentional: rollback is an "undo last activation" operation, not a history traversal. To reach an older snapshot (beyond the previous one), the owner uses the `activate` endpoint with an explicit snapshot ID.

**Rejected alternatives:**
- (B) `:id` = target PUBLISHED snapshot to make active — functionally identical to `activate`, adds no value.
- (C) `:id` = active snapshot + optional `target_snapshot_id` in body — overcomplicates the API; use `activate` for explicit targeting.

### D3: Soft delete — Warnings in response, not blocking

**Chosen:** `DELETE /api/admin/sources/{id}` always succeeds (soft delete is safe and reversible). If the source has chunks in published/active snapshots, the response includes a `warnings` array explaining that chunks remain visible.

**Why:**
- Soft delete is inherently safe — both `status` and `deleted_at` are set (see D4 note on dual-field contract), but no data is destroyed.
- Blocking deletion (requiring `?force=true`) adds UX friction without real protection since the operation is reversible.
- Silent deletion hides consequences — the owner should know their published data is still being served.
- Warnings provide transparency without blocking the workflow.

**Rejected alternatives:**
- (A) Silent delete — owner doesn't learn that chunks remain in published snapshots.
- (C) Confirmation flag (`?force=true`) — adds complexity without real safety benefit since soft delete is reversible.

### D4: Draft chunk cascade on soft delete

**Chosen:** When a source is soft-deleted, its chunks in DRAFT snapshots are removed from both Qdrant and PostgreSQL, and the draft's `chunk_count` is decremented. Chunks in PUBLISHED/ACTIVE snapshots remain untouched.

**Why:**
- Architecture.md states: "Chunks from a deleted source are excluded from **future** snapshots but remain in already published ones."
- Draft snapshots represent future content — deleted source chunks should not be published.
- Published/active snapshots are immutable — removing chunks would break the snapshot contract and potentially affect live retrieval.
- Qdrant cleanup for draft chunks prevents stale vectors from accumulating.

**Dual-field contract:** The `Source` model has both `status` (enum: DELETED) and `deleted_at` (timestamp from `SoftDeleteMixin`). Both MUST be set together on soft delete. The authoritative signal for queries is `status == DELETED` — this is what the ingestion guard, source listing, and all business logic check. The `deleted_at` field records the precise timestamp for audit and potential future undo. Code MUST NOT check only one field without the other.

### D5: Archive endpoint — Deferred

**Chosen:** The `ARCHIVED` status enum already exists in the codebase. No archive endpoint is implemented in S3-05.

**Why:**
- The plan does not mention archiving as a task for S3-05.
- YAGNI: the published pool is sufficient for rollback. Archiving is a cleanup operation that can be added when the owner accumulates many published snapshots.
- The state transition (PUBLISHED → ARCHIVED) is trivial to add later.

---

## Detailed Design

### 1. Rollback

#### Endpoint

```
POST /api/admin/snapshots/{snapshot_id}/rollback
Query params: agent_id (default), knowledge_base_id (default)
```

#### Service Method: `SnapshotService.rollback(snapshot_id, agent_id, knowledge_base_id)`

```
1. SELECT snapshot WHERE id = snapshot_id FOR UPDATE
2. Assert status == ACTIVE → else SnapshotConflictError("Only the active snapshot can be rolled back")
3. Derive scope from the locked current snapshot: agent_id = current.agent_id, knowledge_base_id = current.knowledge_base_id
   (never from query params alone — prevents cross-scope rollback)
4. SELECT target FROM knowledge_snapshots
   WHERE status = 'published'
     AND agent_id = current.agent_id
     AND knowledge_base_id = current.knowledge_base_id
     AND activated_at IS NOT NULL
   ORDER BY activated_at DESC
   LIMIT 1
   FOR UPDATE
5. If no target → SnapshotConflictError("No previously activated snapshot available for rollback")
6. current.status = PUBLISHED (keep activated_at for history)
7. target.status = ACTIVE, target.activated_at = now()
8. UPDATE agents SET active_snapshot_id = target.id WHERE id = agent_id
9. COMMIT
10. Return (rolled_back_from=current, rolled_back_to=target)
```

#### Response Schema

```json
{
  "rolled_back_from": {
    "id": "uuid",
    "name": "string",
    "status": "published",
    "published_at": "datetime",
    "activated_at": "datetime"
  },
  "rolled_back_to": {
    "id": "uuid",
    "name": "string",
    "status": "active",
    "published_at": "datetime",
    "activated_at": "datetime"
  }
}
```

#### Error Cases

| Condition | HTTP | Error |
|-----------|------|-------|
| Snapshot not found | 404 | SnapshotNotFoundError |
| Snapshot is not ACTIVE | 409 | SnapshotConflictError |
| No previously activated published snapshot | 409 | SnapshotConflictError |

#### Concurrency

Row-level locks (`FOR UPDATE`) on both the current active and the rollback target prevent race conditions from concurrent rollback/activate requests. Same pattern as existing `activate()` method.

---

### 2. Draft Test

#### Endpoint

```
POST /api/admin/snapshots/{snapshot_id}/test
Query params: agent_id (default), knowledge_base_id (default)
Body: JSON
```

#### Request Schema

```json
{
  "query": "string",                          // required
  "top_n": 5,                                 // optional, default from retrieval config
  "mode": "hybrid"                            // optional: "hybrid" | "dense" | "sparse"
}
```

#### Service Method

Draft testing calls `QdrantService` search methods directly based on the requested mode. The current `RetrievalService.search()` always performs hybrid search and looks up the active snapshot — neither is appropriate for draft testing. Rather than adding a `mode` parameter to `RetrievalService` (which would complicate the production retrieval path for a testing-only concern), the draft test handler calls `QdrantService.hybrid_search()`, `QdrantService.dense_search()`, or `QdrantService.keyword_search()` directly. The `EmbeddingService` is used for generating the query embedding when dense or hybrid mode is requested.

```
1. Load snapshot by id, assert status == DRAFT → else 422
2. Count INDEXED chunks for this snapshot → if 0, 422
3. Based on mode:
   - "hybrid" (default): embed query via EmbeddingService → call QdrantService.hybrid_search(snapshot_id=draft)
   - "dense": embed query via EmbeddingService → call QdrantService.dense_search(snapshot_id=draft)
   - "sparse": call QdrantService.keyword_search(snapshot_id=draft, query=query)
4. Enrich results with source titles from PostgreSQL
5. Return results
```

#### Response Schema

```json
{
  "snapshot_id": "uuid",
  "snapshot_name": "string",
  "query": "string",
  "mode": "hybrid",
  "results": [
    {
      "chunk_id": "uuid",
      "source_id": "uuid",
      "source_title": "string",
      "text_content": "string (first 500 chars)",
      "score": 0.85,
      "anchor": {
        "page": 3,
        "chapter": "Chapter 1",
        "section": "Introduction",
        "timecode": null
      }
    }
  ],
  "total_chunks_in_draft": 42
}
```

#### Error Cases

| Condition | HTTP | Error |
|-----------|------|-------|
| Snapshot not found | 404 | SnapshotNotFoundError |
| Snapshot is not DRAFT | 422 | SnapshotValidationError |
| Draft has 0 indexed chunks | 422 | SnapshotValidationError |

#### text_content truncation

The response truncates `text_content` to the first 500 Unicode characters (not bytes). Full text is available in the Qdrant payload and PostgreSQL but is not needed for a test overview. This keeps response sizes predictable for both Latin and CJK content.

---

### 3. Source Soft Delete

#### Endpoint

```
DELETE /api/admin/sources/{source_id}
Query params: agent_id (default), knowledge_base_id (default)
```

#### Service Method

Soft delete logic is implemented as a new method in a dedicated module (e.g., `source_delete.py` or added to an existing `SourceService`). The method requires a database session and `QdrantService` for draft chunk cleanup. The current `SourceService` constructor takes `(session, task_enqueuer)` and has no `QdrantService` dependency — the implementer should choose whichever approach (extend constructor, new service, or standalone function) best fits the existing patterns without over-engineering.

**`soft_delete(source_id, agent_id, knowledge_base_id)`**

```
1. Load source by id + scope
2. If not found → 404
3. If source.status == DELETED → return idempotent 200 (no warnings)
4. Set source.status = DELETED, source.deleted_at = now()
5. Find all chunks for this source_id grouped by snapshot status:
   a. DRAFT snapshot chunks:
      - Collect chunk_ids
      - Delete from Qdrant (batch delete by chunk_ids)
      - Delete from PostgreSQL
      - Decrement KnowledgeSnapshot.chunk_count for affected draft(s)
   b. PUBLISHED/ACTIVE snapshot chunks:
      - Count them for warnings
      - Do NOT modify
6. Build warnings:
   - If published/active chunk count > 0:
     "Source is referenced in N published/active snapshot(s). Chunks will remain visible until a new snapshot replaces them."
7. COMMIT
8. Return source + warnings
```

#### Response Schema

```json
{
  "id": "uuid",
  "title": "string",
  "source_type": "pdf",
  "status": "deleted",
  "deleted_at": "2026-03-23T12:00:00Z",
  "warnings": [
    "Source is referenced in 2 published/active snapshot(s). Chunks will remain visible until a new snapshot replaces them."
  ]
}
```

#### Error Cases

| Condition | HTTP | Error |
|-----------|------|-------|
| Source not found | 404 | SourceNotFoundError |
| Already deleted | 200 | Idempotent success (empty warnings) |

#### Ingestion guard

The ingestion worker MUST check source status before processing. If a source is DELETED when the worker picks up its task, the task should be marked FAILED with reason "Source was deleted before processing completed." This prevents race conditions where a source is deleted while its ingestion task is in the queue.

#### Qdrant batch delete

Draft chunk cleanup uses Qdrant's point deletion by IDs (existing `QdrantService` capability). Chunks are identified by their `chunk_id` which maps to Qdrant point IDs. This is a batch operation — all draft chunks for the source are deleted in a single Qdrant call.

---

## Files to Modify

| File | Change |
|------|--------|
| `backend/app/services/snapshot.py` | Add `rollback()` method |
| `backend/app/services/source_delete.py` | New file — `SourceDeleteService.soft_delete()` method |
| `backend/app/api/admin.py` | Add rollback endpoint, test endpoint, delete source endpoint |
| `backend/app/api/snapshot_schemas.py` | Add `RollbackResponse`, `DraftTestRequest`, `DraftTestResponse` schemas |
| `backend/app/api/source_schemas.py` | **New file** — `SourceDeleteResponse` Pydantic schema |
| `backend/app/services/qdrant.py` | Uses existing `delete_chunks()` — no changes needed |
| `backend/app/workers/tasks/ingestion.py` | Add source status check at task start |
| `backend/tests/integration/test_snapshot_lifecycle.py` | Add rollback tests |
| `backend/tests/integration/test_snapshot_api.py` | Add rollback + test endpoint API tests |
| `backend/tests/integration/test_source_soft_delete.py` | New test file for soft delete |

## Testing Strategy

### CI Tests (deterministic, no external providers)

**Rollback:**
- Publish A → activate A → publish B → activate B → rollback → A is active, B is published
- Rollback with no previously activated snapshot → 409
- Rollback on non-active snapshot → 409
- Rollback on non-existent snapshot → 404
- Concurrent rollback (if feasible) → one succeeds, one gets 409

**Draft test:**
- Create draft → ingest sources → test query (hybrid) → verify chunks returned with scores
- Test query (dense only) → results from dense search
- Test query (sparse only) → results from BM25 search
- Test on non-draft snapshot → 422
- Test on draft with 0 indexed chunks → 422
- Test on non-existent snapshot → 404

**Source soft delete:**
- Delete source with chunks only in draft → chunks removed from PG + Qdrant, chunk_count decremented
- Delete source with chunks in published snapshot → source DELETED, published chunks untouched, warnings returned
- Delete source with chunks in both draft and published → draft cleaned up, published preserved, warnings
- Delete already-deleted source → idempotent 200
- Delete non-existent source → 404
- Ingestion worker picks up task for deleted source → task FAILED

### Integration points

- Rollback → chat retrieval returns chunks from rolled-back-to snapshot
- Draft test → Qdrant hybrid search scoped to draft snapshot_id
- Soft delete → Qdrant vectors for draft chunks actually removed (verify via search)
