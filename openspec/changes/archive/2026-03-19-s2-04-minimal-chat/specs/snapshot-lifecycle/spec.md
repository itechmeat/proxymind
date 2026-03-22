## MODIFIED Requirements

### Requirement: SnapshotService with get_or_create_draft and get_active_snapshot

The system SHALL provide a `SnapshotService` at `app/services/snapshot.py` with a `get_or_create_draft(session, agent_id, knowledge_base_id) -> KnowledgeSnapshot` method. The method SHALL return the persisted `KnowledgeSnapshot` row for the given `(agent_id, knowledge_base_id)` scope. If no draft exists, it SHALL create one with `status=DRAFT`, implementation-defined ingestion defaults for `name` and `description`, `owner_id=NULL`, and timestamps populated by the model mixins.

**[ADDED by S2-04]** The `SnapshotService` SHALL additionally provide a `get_active_snapshot(agent_id, knowledge_base_id) -> KnowledgeSnapshot | None` method. The method SHALL query the `knowledge_snapshots` table for a snapshot with `status='active'` matching the given `(agent_id, knowledge_base_id)` scope. If an active snapshot exists, it SHALL be returned. If no active snapshot exists for the scope, the method SHALL return `None`. The method SHALL NOT raise an exception when no active snapshot is found — callers are responsible for handling the `None` case.

#### Scenario: First ingestion creates a new draft snapshot

- **WHEN** `get_or_create_draft()` is called and no DRAFT snapshot exists for the given scope
- **THEN** a new `KnowledgeSnapshot` record SHALL be created with `status=DRAFT`, the given `agent_id`, and the given `knowledge_base_id`
- **AND** the method SHALL return the newly created snapshot

#### Scenario: Subsequent ingestion reuses the existing draft

- **WHEN** `get_or_create_draft()` is called and a DRAFT snapshot already exists for the given scope
- **THEN** the method SHALL return the existing snapshot
- **AND** no new snapshot record SHALL be created

#### Scenario: Get active snapshot returns the active snapshot

- **WHEN** `get_active_snapshot(agent_id, knowledge_base_id)` is called and an ACTIVE snapshot exists for the scope
- **THEN** the method SHALL return the active `KnowledgeSnapshot` record

#### Scenario: Get active snapshot returns None when no active snapshot

- **WHEN** `get_active_snapshot(agent_id, knowledge_base_id)` is called and no ACTIVE snapshot exists for the scope
- **THEN** the method SHALL return `None`
- **AND** no exception SHALL be raised

#### Scenario: Get active snapshot returns correct snapshot for scope

- **WHEN** multiple snapshots exist across different scopes with different statuses
- **AND** `get_active_snapshot(agent_id, knowledge_base_id)` is called for a specific scope
- **THEN** the method SHALL return only the ACTIVE snapshot matching the given `(agent_id, knowledge_base_id)` scope
- **AND** snapshots from other scopes or with non-ACTIVE status SHALL NOT be returned

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

The following stable behavior MUST be covered by CI tests before archive (in addition to existing SnapshotService tests):

- **get_active_snapshot integration tests with real PG**: verify method returns the ACTIVE snapshot when one exists for the scope. Verify method returns `None` when no ACTIVE snapshot exists. Verify method returns the correct snapshot when multiple scopes have different active snapshots. Verify method does not return DRAFT, PUBLISHED, or ARCHIVED snapshots.
- **ensure_draft_or_rebind tests with real PG** [from S2-03]: verify method returns locked DRAFT when snapshot is still draft. Verify method rebinds to new draft when snapshot status is PUBLISHED. Verify the returned snapshot is always FOR UPDATE-locked. Verify serialization with concurrent publish.
