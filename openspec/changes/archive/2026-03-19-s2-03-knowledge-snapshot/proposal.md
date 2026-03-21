## Story

**S2-03: Knowledge snapshot (minimal)** from `docs/plan.md`.

Verification criteria: create draft → upload source → publish+activate → vector search against active snapshot works; chunks from draft are not visible.

Stable behavior requiring test coverage: snapshot state transitions (publish, activate, deactivate), publish guards (empty snapshot, pending chunks), active snapshot pointer management, ingestion-side locking for immutability.

## Why

S2-02 created the ingestion pipeline that produces chunks linked to auto-created draft snapshots, but there is no way to make those chunks visible to retrieval. Without a publish/activate lifecycle, the twin has no knowledge to answer from. This is the last prerequisite before S2-04 (minimal chat) can wire up retrieval against an active snapshot.

## What Changes

- Snapshot state machine: `draft → published → active`, with `active → published` on deactivation (return to rollback pool)
- Admin API endpoints: list, get, publish (`?activate=true` convenience), activate
- Publish guards: reject empty snapshots, reject snapshots with pending/failed chunks (live SQL queries)
- Concurrency safety: partial unique index for single ACTIVE per scope, FOR UPDATE locking on snapshot row for both publish and ingestion
- Ingestion worker modification: acquire FOR UPDATE lock on snapshot row before chunk insert, rebind to new draft if snapshot was published concurrently
- Architecture.md update: fix contradiction in snapshot lifecycle diagram (`active → published` on deactivation, not `active → archived`)
- Plan.md update: refine S2-03 tasks, move list/detail from S3-05

## Capabilities

### New Capabilities
- `snapshot-lifecycle`: Snapshot publish/activate state machine, Admin API endpoints (list, get, publish, activate), concurrency guards, and publish validation

### Modified Capabilities
- `snapshot-draft`: Add `ensure_draft_or_rebind` method with FOR UPDATE locking; ingestion worker must acquire lock before chunk persistence
- `ingestion-pipeline`: Ingestion worker modified to use serialized snapshot locking before chunk insert

## Impact

- **Backend service**: `app/services/snapshot.py` — new methods (list, get, publish, activate, _do_activate, ensure_draft_or_rebind)
- **Backend API**: `app/api/admin.py` — 4 new endpoints; new `app/api/snapshot_schemas.py`
- **Backend worker**: `app/workers/tasks/ingestion.py` — replace direct chunk insert with locked snapshot protocol
- **Database**: new Alembic migration for `uq_one_active_per_scope` partial unique index
- **Docs**: `docs/architecture.md` (lifecycle diagram fix), `docs/plan.md` (task refinement)
- **No frontend changes**
- **No new dependencies**
