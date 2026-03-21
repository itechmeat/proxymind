## 1. Database Migration

- [x] 1.1 Add `uq_one_active_per_scope` partial unique index to `KnowledgeSnapshot` model in `backend/app/db/models/knowledge.py`
- [x] 1.2 Generate Alembic migration `005_add_active_snapshot_unique_index.py`
- [x] 1.3 Run migration and verify existing tests pass

## 2. SnapshotService — State Machine

- [x] 2.1 Write failing integration tests for publish (valid draft, empty draft 422, pending chunks 422, non-draft 409)
- [x] 2.2 Write failing integration tests for activate (published→active, draft→409, active→409, archived→409, deactivate previous active)
- [x] 2.3 Write failing integration tests for publish+activate convenience, list_snapshots, ensure_draft_or_rebind
- [x] 2.4 Add `get_snapshot`, `list_snapshots`, `publish`, `activate`, `_do_activate`, `ensure_draft_or_rebind` methods to `backend/app/services/snapshot.py`
- [x] 2.5 Run all lifecycle tests and verify they pass

## 3. Pydantic Schemas

- [x] 3.1 Create `backend/app/api/snapshot_schemas.py` with `SnapshotResponse` model

## 4. Admin API Endpoints

- [x] 4.1 Write failing API tests for list, get, publish, publish+activate, activate, error codes (404, 409, 422)
- [x] 4.2 Add `get_snapshot_service` dependency to `backend/app/api/dependencies.py`
- [x] 4.3 Add 4 snapshot endpoints to `backend/app/api/admin.py` (GET list, GET detail, POST publish, POST activate)
- [x] 4.4 Run API tests and verify they pass

## 5. Ingestion Worker — Serialized Snapshot Locking

- [x] 5.1 Replace direct chunk insert in `backend/app/workers/tasks/ingestion.py` with `ensure_draft_or_rebind` (FOR UPDATE lock held through commit)
- [x] 5.2 Run existing ingestion tests and verify no regression

## 6. Documentation Updates

- [x] 6.1 Update `docs/architecture.md`: fix snapshot lifecycle diagram (active→published on deactivation), update state descriptions, remove contradiction
- [x] 6.2 Update `docs/plan.md`: refine S2-03 tasks, move list/detail from S3-05

## 7. Final Verification

- [ ] 7.1 Run full test suite (`uv run pytest tests/ -v --timeout=180`)
- [x] 7.2 Run linter (`uv run ruff check app/ tests/`)
- [ ] 7.3 Verify migration applies cleanly (disposable test DB only)
