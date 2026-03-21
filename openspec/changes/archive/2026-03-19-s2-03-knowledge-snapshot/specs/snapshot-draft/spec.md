## MODIFIED Requirements

### Requirement: SnapshotService with get_or_create_draft

The system SHALL provide a `SnapshotService` at `app/services/snapshot.py` with a `get_or_create_draft(session, agent_id, knowledge_base_id) -> KnowledgeSnapshot` method. The method SHALL return the persisted `KnowledgeSnapshot` row for the given `(agent_id, knowledge_base_id)` scope. If no draft exists, it SHALL create one with `status=DRAFT`, implementation-defined ingestion defaults for `name` and `description`, `owner_id=NULL`, and timestamps populated by the model mixins.

#### Scenario: First ingestion creates a new draft snapshot

- **WHEN** `get_or_create_draft()` is called and no DRAFT snapshot exists for the given scope
- **THEN** a new `KnowledgeSnapshot` record SHALL be created with `status=DRAFT`, the given `agent_id`, and the given `knowledge_base_id`
- **AND** the method SHALL return the newly created snapshot

#### Scenario: Subsequent ingestion reuses the existing draft

- **WHEN** `get_or_create_draft()` is called and a DRAFT snapshot already exists for the given scope
- **THEN** the method SHALL return the existing snapshot
- **AND** no new snapshot record SHALL be created

---

### Requirement: Snapshot status terminology

The snapshot lifecycle SHALL use the canonical status names `DRAFT`, `PUBLISHED`, `ACTIVE`, and `ARCHIVED` in prose. When the spec shows raw SQL predicates or partial-index definitions, it SHALL use the corresponding stored enum labels `'draft'`, `'published'`, `'active'`, and `'archived'`.

- `DRAFT`: mutable working snapshot created by ingestion and not visible to retrieval.
- `PUBLISHED`: finalized snapshot version that has been published but is not necessarily selected for retrieval yet.
- `ACTIVE`: published snapshot currently selected for retrieval.
- `ARCHIVED`: historical snapshot kept for audit/rollback purposes.

S2-02 only creates `DRAFT` snapshots; `PUBLISHED`, `ACTIVE`, and `ARCHIVED` transitions are introduced by S2-03.

---

### Requirement: Race-condition safety via partial unique index

The `knowledge_snapshots` table SHALL have a partial unique index `uq_one_draft_per_scope` on `(agent_id, knowledge_base_id) WHERE status = 'draft'`. The lowercase literal is the database representation of the `DRAFT` enum value. This index guarantees at most one `DRAFT` snapshot per scope at the database level, preventing race conditions when multiple workers run concurrently.

#### Scenario: Concurrent draft creation resolves to one snapshot

- **WHEN** two concurrent workers both call `get_or_create_draft()` for the same scope simultaneously
- **THEN** exactly one DRAFT snapshot SHALL exist in the database after both calls complete
- **AND** both workers SHALL receive the same snapshot (same `id`)

#### Scenario: Partial index only constrains DRAFT status

- **WHEN** a DRAFT snapshot and a PUBLISHED snapshot both exist for the same `(agent_id, knowledge_base_id)` scope
- **THEN** the unique index SHALL NOT raise a constraint violation (it only applies to DRAFT rows)

---

### Requirement: INSERT ON CONFLICT DO NOTHING + SELECT pattern

The `get_or_create_draft()` implementation SHALL use the SQLAlchemy Core equivalent of:

```sql
INSERT INTO knowledge_snapshots (...)
VALUES (...)
ON CONFLICT (agent_id, knowledge_base_id)
WHERE status = 'draft'
DO NOTHING;

SELECT *
FROM knowledge_snapshots
WHERE agent_id = :agent_id
  AND knowledge_base_id = :knowledge_base_id
  AND status = 'draft';
```

The INSERT conflicts only on the partial unique index for draft rows. If the INSERT conflicts because another worker already created the same draft, the SELECT SHALL return the existing row. This pattern is atomic at the database level and does not require advisory locks or application-level mutex. Implementations SHALL use `insert(...).on_conflict_do_nothing(index_elements=[...], index_where=...)` or an equivalent raw SQL statement.

#### Scenario: INSERT succeeds when no draft exists

- **WHEN** `get_or_create_draft()` is called and no DRAFT snapshot exists
- **THEN** the INSERT SHALL succeed and the SELECT SHALL return the newly inserted row

#### Scenario: INSERT conflicts when draft already exists

- **WHEN** `get_or_create_draft()` is called and a DRAFT snapshot already exists due to a concurrent insert
- **THEN** the INSERT SHALL be a no-op (ON CONFLICT DO NOTHING)
- **AND** the SELECT SHALL return the existing draft snapshot

---

### Requirement: Alembic migration for partial unique index

An Alembic migration SHALL create the partial unique index `uq_one_draft_per_scope` on the `knowledge_snapshots` table with columns `(agent_id, knowledge_base_id)` and condition `WHERE status = 'draft'`. The `owner_id` column is intentionally excluded from the index because auto-created drafts in S2-02 keep `owner_id=NULL`, and PostgreSQL treats `NULL` values as distinct in unique indexes. Including `owner_id` would therefore fail to enforce one draft per scope. The downgrade SHALL drop the index.

#### Scenario: Migration creates the partial unique index

- **WHEN** the migration is applied
- **THEN** the `uq_one_draft_per_scope` index SHALL exist on the `knowledge_snapshots` table
- **AND** inserting two DRAFT snapshots with the same `(agent_id, knowledge_base_id)` SHALL raise a unique violation

#### Scenario: Migration downgrade removes the index

- **WHEN** the migration is downgraded
- **THEN** the `uq_one_draft_per_scope` index SHALL no longer exist

---

### Requirement: Draft snapshot as foundation for snapshot lifecycle

The auto-created `DRAFT` snapshot SHALL serve as the target for chunk tagging during ingestion. All chunks created during ingestion SHALL reference this snapshot via `snapshot_id`. `DRAFT` snapshots are not visible to chat retrieval; only `ACTIVE` snapshots are queried. The publish/activate lifecycle (S2-03) builds on top of these `DRAFT` snapshots.

#### Scenario: Chunks reference the draft snapshot

- **WHEN** the ingestion pipeline creates chunks
- **THEN** every Chunk record in PostgreSQL SHALL have `snapshot_id` matching the draft snapshot's `id`
- **AND** every Qdrant point payload SHALL have `snapshot_id` matching the draft snapshot's `id`

#### Scenario: Draft snapshot is not visible to retrieval

- **WHEN** a retrieval query filters by snapshot status (future S2-04)
- **THEN** DRAFT snapshots SHALL NOT be included in the search scope (only ACTIVE snapshots are queried)

---

### Requirement: ensure_draft_or_rebind method with FOR UPDATE locking

**[ADDED by S2-03]** The `SnapshotService` SHALL provide an `ensure_draft_or_rebind(session, snapshot_id, agent_id, knowledge_base_id) -> KnowledgeSnapshot` method. This method SHALL always return a FOR UPDATE-locked DRAFT snapshot. The method SHALL:

1. Acquire `SELECT ... FROM knowledge_snapshots WHERE id = :snapshot_id FOR UPDATE` on the given snapshot row.
2. Check the locked snapshot's status:
   - If `status == 'draft'`: return the locked snapshot directly. The caller proceeds to insert chunks under this lock.
   - If `status != 'draft'` (snapshot was published or otherwise transitioned concurrently): call `get_or_create_draft(session, agent_id, knowledge_base_id)` to obtain or create a new draft snapshot, then acquire `SELECT ... FOR UPDATE` on the new draft row before returning it.
3. The method SHALL never return an unlocked snapshot. The FOR UPDATE lock MUST be held on the returned snapshot row when the method returns.

This method is the serialization mechanism between the ingestion worker and the publish operation. Both publish and ingestion acquire FOR UPDATE on the same snapshot row, ensuring they cannot run concurrently. The ingestion worker MUST call `ensure_draft_or_rebind` before persisting any chunks and MUST hold the lock through the chunk insert and commit.

#### Scenario: Snapshot is still DRAFT, returns locked snapshot

- **WHEN** `ensure_draft_or_rebind()` is called with a snapshot_id that is still in DRAFT status
- **THEN** the method SHALL return the same snapshot, locked with FOR UPDATE
- **AND** the caller can insert chunks under this lock

#### Scenario: Snapshot was published concurrently, rebinds to new draft

- **WHEN** `ensure_draft_or_rebind()` is called with a snapshot_id that has been published (status is PUBLISHED or ACTIVE)
- **THEN** the method SHALL call `get_or_create_draft()` to obtain a new DRAFT snapshot
- **AND** the method SHALL acquire FOR UPDATE on the new draft row
- **AND** the method SHALL return the new locked DRAFT snapshot

#### Scenario: Returned snapshot is always locked

- **WHEN** `ensure_draft_or_rebind()` returns a snapshot (whether original or rebound)
- **THEN** a FOR UPDATE lock SHALL be held on that snapshot's row in the current transaction
- **AND** no other transaction can modify or lock that row until the current transaction commits or rolls back

#### Scenario: Lock serializes with publish operation

- **WHEN** the ingestion worker holds a FOR UPDATE lock on a DRAFT snapshot via `ensure_draft_or_rebind()`
- **AND** a concurrent publish call attempts to lock the same snapshot row
- **THEN** the publish call SHALL block until the ingestion transaction commits
- **AND** publish SHALL then see the chunks inserted by the ingestion worker

---

## Test Coverage

### CI tests (deterministic)

The following stable behavior MUST be covered by CI tests before archive:

- **SnapshotService integration tests with real PG**: verify first call creates a DRAFT snapshot, second call returns the same snapshot (reuse), snapshot has correct `agent_id` and `knowledge_base_id`, snapshot status is DRAFT.
- **Partial unique index test**: verify that inserting two DRAFT snapshots with the same scope raises `IntegrityError`, while DRAFT + PUBLISHED for the same scope does not conflict.
- **Migration test**: verify migration applies cleanly and the index exists.
- **ensure_draft_or_rebind tests with real PG** [ADDED by S2-03]: verify method returns locked DRAFT when snapshot is still draft. Verify method rebinds to new draft when snapshot status is PUBLISHED. Verify the returned snapshot is always FOR UPDATE-locked. Verify serialization with concurrent publish (publish blocks while ingestion holds lock).
