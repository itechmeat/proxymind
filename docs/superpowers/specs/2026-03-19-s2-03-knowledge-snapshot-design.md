# S2-03: Knowledge Snapshot (Minimal) — Design

## Story

> Draft → publish → active lifecycle. On source upload, chunks are linked to a draft snapshot.
> Publish makes the snapshot active. Retrieval only from active.

**Outcome:** knowledge can be published and search works only against published content.

**Verification:** create draft → upload source → publish → vector search against active snapshot works; chunks from draft are not visible.

### Scope refinement vs plan.md

Plan.md S2-03 states: "Publish makes the snapshot active." This design refines the publish operation into two explicit steps: `publish` (draft → published) and `activate` (published → active). The convenience parameter `?activate=true` on the publish endpoint preserves the original one-call behavior described in the plan.

**Why refine now, not in S3-05:** architecture.md already defines 4 states (draft/published/active/archived). Implementing a two-step model now costs approximately the same as a single-step, but avoids a semantic rewrite when S3-05 adds rollback. The plan.md acceptance criteria ("publish → active snapshot works") is satisfied by `POST /snapshots/:id/publish?activate=true`.

**Action required:** update plan.md S2-03 tasks to reflect the refined semantics: `snapshot CRUD API, snapshot_id in Qdrant payload, publish/activate logic, state machine with concurrency guards`.

This design also includes `GET /snapshots` (list) and `GET /snapshots/:id` (detail) endpoints. Plan.md mentions "GET list snapshots" under S3-05, but these are essential for the minimal story: without list/detail, the owner cannot discover which snapshot to publish. **Action required:** update plan.md to move list/detail from S3-05 scope note into S2-03 tasks.

## Design Decisions

### D1: Publish semantics — two-step (publish + activate separately)

**Decision:** publish and activate are separate operations.

- `POST /snapshots/:id/publish` transitions `draft → published` (finalized, immutable).
- `POST /snapshots/:id/activate` transitions `published → active` (used by retrieval).
- Convenience: `POST /snapshots/:id/publish?activate=true` performs both in one transaction.

**Why:** architecture.md defines 4 distinct states (draft → published → active → archived). A two-step model maps directly to this contract. S3-05 (rollback, draft testing) adds transitions to the same state machine without refactoring. The cost of two separate transitions is approximately the same as one combined transition.

**Rejected alternative:** single-step publish (draft → active directly). Simpler for minimal story, but conflates two distinct lifecycle events and requires semantic changes when S3-05 adds rollback.

### D2: Deactivated snapshot returns to published pool — domain model change

**Decision:** when a new snapshot is activated, the previously active snapshot transitions back to `published` status.

**What changes in the domain model:** this design intentionally revises the snapshot lifecycle from architecture.md. The current architecture.md has an internal contradiction:
- Line 120: `active → archived: new snapshot became active`
- Line 136: `Rollback: switching active_snapshot_id to the snapshot_id of another published snapshot`

These are incompatible: if deactivated snapshots go to `archived`, there are no `published` snapshots left for rollback. This design resolves the contradiction by choosing `active → published` on deactivation. The consequences:
- **Published pool = rollback set.** All previously active snapshots remain in published status, ready for re-activation.
- **Archived is a terminal state.** It is reached only by explicit owner action (future S3-05), never automatically.
- **Rollback (S3-05) becomes trivial:** just `activate` a different published snapshot.

**Note:** architecture.md MUST be updated as part of this story to reflect the revised state diagram and remove the contradiction (see Files to Modify).

`activated_at` represents the **most recent** activation timestamp. It is overwritten on each activation (e.g., if a snapshot is activated, deactivated back to published, then activated again, `activated_at` reflects the second activation). `archived_at` records explicit removal from the pool.

**Rejected alternatives:**
- Active → archived automatically (current architecture.md): creates contradiction with rollback, makes `archived` non-terminal.
- Require explicit deactivate before activate: non-atomic, creates window with no active snapshot.

### D3: Draft creation — automatic only

**Decision:** no manual `POST /api/admin/snapshots` endpoint. Drafts are created automatically by `get_or_create_draft()` during ingestion (existing behavior from S2-02).

**Why:** YAGNI for minimal story. Plan.md confirms: "On source upload, chunks are linked to a draft snapshot." Naming can be added later via `PATCH /snapshots/:id`. The `GET /snapshots` endpoint for listing is needed, but creation is not.

**Rejected alternative:** manual + automatic creation. Two creation paths create potential confusion about scope matching and empty snapshots.

### D4: Publishing empty snapshots is forbidden

**Decision:** `publish` returns 422 if the snapshot has no indexed chunks or if any chunks are still processing.

**Why:** publish means "finalized, immutable" (architecture.md). An empty immutable snapshot is a meaningless entity. The guard protects against a real error: publishing before ingestion completes. If "disabling" the knowledge base is needed, that is separate functionality, not an empty snapshot.

**Guard implementation:** both checks use **live SQL queries** against the `chunks` table, not the `chunk_count` counter. The counter is advisory (for display in API responses) and may be stale during concurrent ingestion:
- Indexed count: `SELECT count(*) FROM chunks WHERE snapshot_id = :id AND status = 'indexed'` → must be > 0
- Pending count: `SELECT count(*) FROM chunks WHERE snapshot_id = :id AND status != 'indexed'` → must be 0

### D5: Verification via integration tests, no search endpoint

**Decision:** snapshot isolation is verified through integration tests that query Qdrant directly with payload filters. No search/retrieval endpoint is added in S2-03.

**Why:** S2-04 defines the retrieval service and search endpoint. Adding a test search endpoint in S2-03 would duplicate S2-04 scope. Integration tests can call the Qdrant client with `snapshot_id` filter and prove isolation. For manual verification: `curl` to Qdrant REST API (`POST /collections/{name}/points/scroll` with filter).

### D6: List/detail endpoints included in S2-03

**Decision:** `GET /api/admin/snapshots` and `GET /api/admin/snapshots/:id` are part of S2-03, not deferred to S3-05.

**Why:** without list/detail, the owner cannot discover which snapshot exists or what its status is before calling publish/activate. These endpoints are a prerequisite for a usable publish flow, not optional UX sugar. Plan.md S3-05 mentions "GET list snapshots" alongside rollback and draft testing — the list endpoint is pulled forward because publish/activate depend on it.

## State Machine

### States and transitions

```
DRAFT ──publish──→ PUBLISHED ──activate──→ ACTIVE
                       ↑                      │
                       └──────deactivate──────┘

DRAFT/PUBLISHED/ACTIVE ──archive──→ ARCHIVED (future, S3-05)
```

### Transition table

| Current   | Action              | Next      | Guards                                                              | Side effects                                                                                              |
| --------- | ------------------- | --------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| DRAFT     | publish             | PUBLISHED | live query: indexed chunks > 0; live query: pending chunks == 0     | `published_at = now()`; snapshot row locked (SELECT FOR UPDATE)                                           |
| PUBLISHED | activate            | ACTIVE    | —                                                                   | `activated_at = now()`; old ACTIVE → PUBLISHED; `Agent.active_snapshot_id = this.id`; partial unique index enforces single ACTIVE per scope |
| ACTIVE    | deactivate (internal) | PUBLISHED | only called internally during activate of another snapshot          | `activated_at` preserved (records last activation time)                                                   |
| DRAFT     | publish+activate    | ACTIVE    | same guards as publish                                              | both transitions in one transaction                                                                       |

### Invalid transitions

Any transition not in the table returns `409 Conflict` with a message describing the current status and allowed actions.

Examples:
- publish PUBLISHED → 409 "Snapshot is already published"
- activate DRAFT → 409 "Cannot activate a draft snapshot, publish first"
- activate ARCHIVED → 409 "Cannot activate an archived snapshot"

## Concurrency and Atomicity

### Problem: three race conditions

1. **Parallel activate:** two concurrent activate calls could both read "no current ACTIVE" and both set themselves to ACTIVE, violating the single-active invariant.
2. **Publish during ingestion:** ingestion worker writes PENDING chunks to a draft while publish checks "all chunks INDEXED" — the check passes, then new PENDING chunks arrive in a now-published snapshot.
3. **Parallel publish:** two concurrent publish calls on the same draft could both pass guards and both transition.

### Solution: three mechanisms

**Mechanism 1: Partial unique index on ACTIVE per scope (DB-level invariant)**

```sql
CREATE UNIQUE INDEX uq_one_active_per_scope
    ON knowledge_snapshots (agent_id, knowledge_base_id)
    WHERE status = 'active';
```

This is analogous to the existing `uq_one_draft_per_scope` index. It makes it physically impossible to have two ACTIVE snapshots in the same scope, regardless of application-level bugs or race conditions. If a concurrent activate violates this, PostgreSQL raises a unique constraint error → the service retries or returns 409.

**This requires a new Alembic migration** (see Database Changes).

**Mechanism 2: SELECT FOR UPDATE on snapshot row**

Both `publish` and `activate` acquire a row-level lock on the snapshot before checking guards and transitioning:

- **publish:** `SELECT ... FROM knowledge_snapshots WHERE id = :id FOR UPDATE` → locks the draft row, serializes concurrent publish calls on the same snapshot. Guard queries run inside the same transaction and see a consistent view of chunks at that point in time.
- **activate:** `SELECT ... FROM knowledge_snapshots WHERE id = :id FOR UPDATE` on the target snapshot, then `SELECT ... FOR UPDATE` on the current ACTIVE snapshot (if any). This serializes concurrent activate calls.

**Important limitation:** locking the snapshot row does **not** block chunk inserts. `Chunk.snapshot_id` is a plain UUID (not a FK to `knowledge_snapshots`) by design — see `backend/app/db/models/knowledge.py`. This means an ingestion worker that already holds a `snapshot_id` can continue inserting chunks even while publish holds the row lock, and even after publish commits. The snapshot row lock serializes publish operations and ensures guard queries see a consistent state at check time, but it does not enforce immutability alone. Mechanism 3 is required for that.

**Mechanism 3: Ingestion-side locking (serialized immutability)**

Since `Chunk.snapshot_id` is not a FK, immutability of published snapshots cannot be enforced purely by the publish side. The ingestion worker MUST serialize with publish by locking the same row:

1. **Before persisting chunks:** the ingestion worker acquires `SELECT ... FROM knowledge_snapshots WHERE id = :snapshot_id FOR UPDATE`. This is the same lock that publish acquires. Only one of them can hold it at a time.

2. **While holding the lock:** the worker checks `status == 'draft'`. If `status != 'draft'`, the worker MUST NOT write chunks to this snapshot. Instead, it calls `get_or_create_draft()` to obtain or create a new draft, then acquires `FOR UPDATE` on the new draft as well. The method always returns a locked DRAFT snapshot — never an unlocked one.

3. **If status is DRAFT (original or rebound):** the worker inserts chunks within the same transaction that holds the lock. The lock is released when the transaction commits. During this time, publish cannot acquire the lock and therefore cannot transition the snapshot.

4. **Why this is correct:** publish and chunk insert are serialized on the same row lock. There is no window between re-check and insert — they happen under the same lock. Either:
   - Ingestion holds the lock first → inserts chunks → commits → publish acquires lock → sees PENDING chunks → returns 422.
   - Publish holds the lock first → transitions DRAFT → PUBLISHED → commits → ingestion acquires lock → sees PUBLISHED → rebinds to new draft.

5. **Change to ingestion worker:** the existing `ingestion.py` task must be modified to acquire FOR UPDATE on the snapshot row before chunk persistence, check status, and keep the lock through commit. The `ensure_draft_or_rebind` method on SnapshotService encapsulates this logic.

### Publish-ingestion race: detailed sequence

**Scenario A: Ingestion acquires lock first**

1. Ingestion worker calls `get_or_create_draft` → gets draft snapshot, holds `snapshot_id`.
2. Ingestion acquires `SELECT ... FOR UPDATE` on snapshot row → lock held.
3. Ingestion checks status → DRAFT → proceeds.
4. Ingestion inserts chunks with status=PENDING (still holding lock).
5. **Meanwhile**, admin calls `POST /snapshots/:id/publish`.
6. Publish tries `SELECT ... FOR UPDATE` on the same row → **blocks** (ingestion holds lock).
7. Ingestion commits (chunks written, progress updated) → lock released.
8. Publish acquires lock → runs guard query → finds PENDING chunks → returns 422.
9. Admin waits for chunks → INDEXED, retries publish → succeeds.

**Scenario B: Publish acquires lock first**

1. Ingestion worker calls `get_or_create_draft` → gets draft snapshot, holds `snapshot_id`.
2. Admin calls publish → acquires `SELECT ... FOR UPDATE` → no PENDING chunks → publish succeeds → DRAFT → PUBLISHED → commits → lock released.
3. Ingestion acquires `SELECT ... FOR UPDATE` → reads status → sees PUBLISHED.
4. Ingestion calls `get_or_create_draft()` → gets/creates a new draft → inserts chunks into new draft.
5. Published snapshot untouched.

**Scenario C: Ingestion skips locking (bug)**

If the worker bypasses the FOR UPDATE lock and writes chunks directly, the chunks could land in a published snapshot. This is why the lock-based protocol is mandatory — `ensure_draft_or_rebind` with FOR UPDATE is a required correctness mechanism, not a defense-in-depth nicety.

### Summary of guarantees

| Invariant | Enforcement |
|-----------|------------|
| At most one ACTIVE per scope | Partial unique index `uq_one_active_per_scope` (DB-level) |
| At most one DRAFT per scope | Existing partial unique index `uq_one_draft_per_scope` (DB-level) |
| Published snapshot is immutable | Serialized: both publish and ingestion acquire FOR UPDATE on the same snapshot row — they cannot run concurrently. Ingestion checks status under lock and rebinds if no longer DRAFT |
| Guards see consistent chunk state | Guard queries run inside the same transaction as the row lock |
| Concurrent publishes serialized | SELECT FOR UPDATE on snapshot row |
| Concurrent activates serialized | SELECT FOR UPDATE + unique index as safety net |

## API Endpoints

### New endpoints (Admin API)

| Method | Path                                | Description       | Request                                | Response           | Status          |
| ------ | ----------------------------------- | ----------------- | -------------------------------------- | ------------------ | --------------- |
| GET    | `/api/admin/snapshots`              | List snapshots    | query: `?status=draft&status=published` (optional, multiple) | `[SnapshotResponse]` | 200             |
| GET    | `/api/admin/snapshots/:id`          | Snapshot details  | —                                      | `SnapshotResponse` | 200 / 404       |
| POST   | `/api/admin/snapshots/:id/publish`  | Publish draft     | query: `?activate=true` (optional)     | `SnapshotResponse` | 200 / 409 / 422 |
| POST   | `/api/admin/snapshots/:id/activate` | Activate published | —                                      | `SnapshotResponse` | 200 / 409       |

### Response schema: SnapshotResponse

```json
{
  "id": "uuid",
  "agent_id": "uuid",
  "knowledge_base_id": "uuid",
  "name": "Auto draft",
  "description": null,
  "status": "draft | published | active | archived",
  "chunk_count": 42,
  "created_at": "2026-03-19T...",
  "published_at": null,
  "activated_at": null,
  "archived_at": null
}
```

Note: `chunk_count` in the response is the advisory counter from the model, used for display purposes. It is NOT used for publish guards (see D4).

### Filtering

`GET /snapshots?status=draft&status=active` returns snapshots in draft OR active status. Without parameters: all except archived. To include archived: `?include_archived=true`.

If `status=archived` is explicitly passed as a filter, archived snapshots are returned regardless of `include_archived`. The `include_archived` flag is a convenience for "show everything including archived" without listing all statuses.

Archived snapshots are hidden by default because they accumulate over time. Explicit access comes in S3-05.

### Error responses

| Status | When                    | Body                                                                        |
| ------ | ----------------------- | --------------------------------------------------------------------------- |
| 404    | Snapshot not found      | `{"detail": "Snapshot not found"}`                                          |
| 409    | Invalid state transition | `{"detail": "Cannot publish: snapshot status is 'published', expected 'draft'"}` |
| 409    | Concurrent activate conflict | `{"detail": "Another snapshot is being activated concurrently, retry"}` |
| 422    | Guard failed            | `{"detail": "Cannot publish: snapshot has no indexed chunks"}` or `{"detail": "Cannot publish: 3 chunks are still processing"}` |

### Not included in S2-03 (YAGNI)

- `POST /api/admin/snapshots` — manual creation (listed in architecture.md Admin API table, consciously deferred)
- `PATCH /api/admin/snapshots/:id` — update name/description
- `DELETE /api/admin/snapshots/:id` — deletion/archival (S3-05)
- `POST /api/admin/snapshots/:id/test` — draft testing (S3-05)
- `POST /api/admin/snapshots/:id/rollback` — rollback (S3-05)

## Service Layer

### Structure

All snapshot lifecycle business logic lives in `backend/app/services/snapshot.py`, extending the existing `SnapshotService`.

### Methods

**Existing (unchanged):**
- `get_or_create_draft(session, agent_id, knowledge_base_id)` — used by ingestion worker

**Existing (modified):**
- `ensure_draft_or_rebind(session, snapshot_id, agent_id, knowledge_base_id)` → **always returns a FOR UPDATE-locked DRAFT snapshot**. Acquires lock on given snapshot; if still DRAFT, returns it. If not DRAFT, obtains/creates a new draft via `get_or_create_draft()`, then acquires FOR UPDATE on the new draft before returning. Caller inserts chunks under this lock. Called by ingestion worker before chunk persistence (see Mechanism 3 in Concurrency section)

**New:**
- `list_snapshots(session, agent_id, knowledge_base_id, statuses?, include_archived?)` → list of snapshots
- `get_snapshot(session, snapshot_id)` → snapshot or None
- `publish(session, snapshot_id, activate=False)` → snapshot
- `activate(session, snapshot_id)` → snapshot

### Key method details

**`publish(session, snapshot_id, activate=False)`**
1. `SELECT ... FROM knowledge_snapshots WHERE id = :id FOR UPDATE` → lock row
2. Check status == DRAFT → else 409
3. Guard (live SQL): `SELECT count(*) FROM chunks WHERE snapshot_id = :id AND status = 'indexed'` → must be > 0, else 422
4. Guard (live SQL): `SELECT count(*) FROM chunks WHERE snapshot_id = :id AND status != 'indexed'` → must be 0, else 422 with count
5. Update status → PUBLISHED, `published_at = now()`
6. If `activate=True` → call `_do_activate(session, snapshot)` in the same transaction
7. Return snapshot

**`activate(session, snapshot_id)`**
1. `SELECT ... FROM knowledge_snapshots WHERE id = :id FOR UPDATE` → lock row
2. Check status == PUBLISHED → else 409
3. Call `_do_activate(session, snapshot)`
4. Return snapshot

**`_do_activate(session, snapshot)` (private)**
1. Find current ACTIVE snapshot for the same (agent_id, knowledge_base_id) with `FOR UPDATE`
2. If found → update status → PUBLISHED (deactivate)
3. Update passed snapshot: status → ACTIVE, `activated_at = now()`
4. Update `Agent.active_snapshot_id = snapshot.id`
5. All within the same transaction (session already passed)
6. On unique constraint violation (`uq_one_active_per_scope`) → catch and return 409

### Separation of concerns

| Layer                  | Responsibility                                                |
| ---------------------- | ------------------------------------------------------------- |
| Router (`admin.py`)    | HTTP parsing, query params, call service, response serialization |
| Service (`snapshot.py`) | State transitions, guards, DB mutations, row locking          |
| Model (`knowledge.py`) | Schema, enum, constraints, partial unique indexes             |

Router contains no business logic. All state checks, guards, and locking are in the service.

### Dependencies

- SnapshotService depends only on SQLAlchemy session — no Qdrant/Redis calls
- Guard queries use live SQL against the `chunks` table

## Database Changes

**One new migration required:** add a partial unique index to enforce single ACTIVE per scope.

```sql
CREATE UNIQUE INDEX uq_one_active_per_scope
    ON knowledge_snapshots (agent_id, knowledge_base_id)
    WHERE status = 'active';
```

This is analogous to the existing `uq_one_draft_per_scope` (migration 004). The index guarantees at the database level that only one snapshot can be ACTIVE per (agent_id, knowledge_base_id) scope, preventing race conditions in concurrent activate calls.

### What already exists (no changes needed)

- `KnowledgeSnapshot` model: `status` (enum), `published_at`, `activated_at`, `archived_at`, `chunk_count`
- Partial unique index `uq_one_draft_per_scope` on DRAFT per scope (migration 004)
- `Agent.active_snapshot_id` FK (migration 001)
- `Chunk.status` enum (PENDING/INDEXED/FAILED) and `Chunk.snapshot_id`

### Migration summary

| Migration | What | Why |
|-----------|------|-----|
| New: `005_add_active_snapshot_unique_index.py` | Partial unique index on ACTIVE per (agent_id, knowledge_base_id) | DB-level enforcement of single-active invariant |

## Testing Strategy

### Unit tests (state machine logic)

**Valid transitions:**
- draft → publish → published
- published → activate → active
- draft → publish(activate=true) → active
- active snapshot deactivated → published when new one activated
- Agent.active_snapshot_id updated on activate

**Guards (publish):**
- publish draft with zero indexed chunks → 422
- publish draft with pending chunks → 422 with count
- publish draft with all chunks INDEXED → ok

**Invalid transitions:**
- publish published → 409
- publish active → 409
- activate draft → 409
- activate active → 409
- activate archived → 409

**Edge cases:**
- activate when no current active (first activation) → ok, no deactivate
- publish(activate=true) when active exists → old deactivated, new active

### Integration tests (DB + Qdrant)

**End-to-end snapshot lifecycle:**
1. Upload source → draft auto-created, chunks in Qdrant with `snapshot_id=draft.id`
2. Publish draft → status=PUBLISHED, timestamps correct
3. Activate → status=ACTIVE, `Agent.active_snapshot_id` set
4. Qdrant scroll with filter `snapshot_id=active.id` → chunks found
5. Upload new source → new draft auto-created (separate snapshot)
6. Publish+activate new → new=ACTIVE, old=PUBLISHED (deactivated)
7. `Agent.active_snapshot_id` = new snapshot id

**Isolation proof (key test):**
1. Create two snapshots: one ACTIVE (with chunks), one DRAFT (with chunks)
2. Qdrant scroll filter `snapshot_id=active.id` → chunks of active
3. Qdrant scroll filter `snapshot_id=draft.id` → chunks of draft
4. Assert: `Agent.active_snapshot_id == active.id` — retrieval (S2-04) will use only active

**Concurrency tests:**
- Concurrent activate on two different PUBLISHED snapshots → one succeeds, one gets 409 (unique index violation)
- Publish while ingestion is writing PENDING chunks → publish returns 422
- Concurrent publish on the same draft → one succeeds, one gets 409 (row already PUBLISHED)
- Ingestion re-check after publish: snapshot published between get_or_create_draft and chunk insert → ingestion rebinds to new draft, published snapshot has no new chunks

### API tests (endpoint level)

- `GET /snapshots` — returns list, status filtering works, archived hidden by default
- `GET /snapshots/:id` — 200 for existing, 404 for missing
- `POST /snapshots/:id/publish` — 200 for valid draft, 409 for non-draft, 422 for empty draft
- `POST /snapshots/:id/publish?activate=true` — 200, snapshot in status=ACTIVE
- `POST /snapshots/:id/activate` — 200 for published, 409 for non-published

### Not included (YAGNI)

- Evals — no retrieval yet
- Load testing — scope S7
- Qdrant search quality — scope S2-04+

## Files to Modify

| File | Changes |
|------|---------|
| `backend/app/db/models/knowledge.py` | Add partial unique index `uq_one_active_per_scope` to KnowledgeSnapshot model |
| `backend/migrations/versions/005_*.py` | New migration: add `uq_one_active_per_scope` partial unique index |
| `backend/app/services/snapshot.py` | Add list, get, publish, activate, _do_activate, ensure_draft_or_rebind methods with FOR UPDATE locking |
| `backend/app/workers/tasks/ingestion.py` | Replace `get_or_create_draft` + direct chunk insert with `ensure_draft_or_rebind` (FOR UPDATE lock held through chunk insert); rebind to new draft if snapshot is no longer DRAFT |
| `backend/app/api/admin.py` | Add 4 new endpoints |
| `backend/app/api/schemas.py` (or new `snapshot_schemas.py`) | Add SnapshotResponse, query param models |
| `docs/architecture.md` | Update snapshot lifecycle state diagram: `active → published` on deactivation (not `active → archived`); remove contradiction between lines 120 and 136; update state descriptions |
| `docs/plan.md` | Update S2-03 tasks to reflect refined publish/activate semantics and list/detail endpoints; adjust S3-05 to remove list/detail |
| `backend/tests/unit/test_snapshot_state_machine.py` | New: unit tests for transitions and guards |
| `backend/tests/integration/test_snapshot_lifecycle.py` | New: end-to-end lifecycle + isolation + concurrency tests |
| `backend/tests/integration/test_snapshot_api.py` | New: API endpoint tests |

## Out of Scope

- Manual snapshot creation (auto-draft only)
- Rollback, archive, draft testing (S3-05)
- Search/retrieval endpoint (S2-04)
- Qdrant collection changes (payload already includes snapshot_id)
