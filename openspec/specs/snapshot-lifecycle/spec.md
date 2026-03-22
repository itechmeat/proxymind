## Purpose

Snapshot publish/activate state machine, Admin API endpoints, concurrency guards, and publish validation. Introduced by S2-03.

## Requirements

### Requirement: Snapshot state machine transitions

The system SHALL implement a snapshot state machine with the following valid transitions:

- `DRAFT -> PUBLISHED` via the publish action
- `PUBLISHED -> ACTIVE` via the activate action
- `ACTIVE -> PUBLISHED` via internal deactivation (when another snapshot is activated)
- `DRAFT -> ACTIVE` via publish with `?activate=true` (both transitions in one transaction)

Any transition not listed above SHALL be rejected with HTTP 409 Conflict, including a message describing the current status and allowed actions. The `ARCHIVED` state is a terminal state reached only by explicit owner action (future S3-05), never automatically on deactivation.

#### Scenario: Draft is published successfully

- **WHEN** `POST /api/admin/snapshots/:id/publish` is called on a DRAFT snapshot that passes all guards
- **THEN** the snapshot status SHALL transition to PUBLISHED
- **AND** `published_at` SHALL be set to the current timestamp

#### Scenario: Published snapshot is activated successfully

- **WHEN** `POST /api/admin/snapshots/:id/activate` is called on a PUBLISHED snapshot
- **THEN** the snapshot status SHALL transition to ACTIVE
- **AND** `activated_at` SHALL be set to the current timestamp

#### Scenario: Active snapshot is deactivated when another is activated

- **WHEN** a new snapshot is activated and another snapshot is currently ACTIVE for the same scope
- **THEN** the previously ACTIVE snapshot SHALL transition to PUBLISHED
- **AND** its `activated_at` value SHALL be preserved (records last activation time)

#### Scenario: Draft is published and activated in one call

- **WHEN** `POST /api/admin/snapshots/:id/publish?activate=true` is called on a DRAFT snapshot that passes all guards
- **THEN** the snapshot status SHALL transition to ACTIVE
- **AND** both `published_at` and `activated_at` SHALL be set
- **AND** any previously ACTIVE snapshot in the same scope SHALL transition to PUBLISHED

#### Scenario: Invalid transition returns 409

- **WHEN** `POST /api/admin/snapshots/:id/publish` is called on a PUBLISHED snapshot
- **THEN** the response SHALL be 409 Conflict with detail "Cannot publish: snapshot status is 'published', expected 'draft'"

#### Scenario: Activate a draft returns 409

- **WHEN** `POST /api/admin/snapshots/:id/activate` is called on a DRAFT snapshot
- **THEN** the response SHALL be 409 Conflict indicating the snapshot must be published first

#### Scenario: Activate an archived snapshot returns 409

- **WHEN** `POST /api/admin/snapshots/:id/activate` is called on an ARCHIVED snapshot
- **THEN** the response SHALL be 409 Conflict indicating archived snapshots cannot be activated

#### Scenario: First activation with no current active snapshot

- **WHEN** `POST /api/admin/snapshots/:id/activate` is called on a PUBLISHED snapshot and no ACTIVE snapshot exists for the scope
- **THEN** the snapshot SHALL transition to ACTIVE without deactivating any other snapshot

---

### Requirement: Publish guards via live SQL queries

The publish action SHALL enforce two guards using live SQL queries against the `chunks` table. The advisory `chunk_count` counter on the snapshot model SHALL NOT be used for guard decisions.

- **Indexed count guard:** `SELECT count(*) FROM chunks WHERE snapshot_id = :id AND status = 'indexed'` MUST return a value greater than 0. If zero, the response SHALL be 422 with detail "Cannot publish: snapshot has no indexed chunks".
- **Pending count guard:** `SELECT count(*) FROM chunks WHERE snapshot_id = :id AND status != 'indexed'` MUST return 0. If non-zero, the response SHALL be 422 with detail "Cannot publish: N chunks are still processing" where N is the count.

Both guard queries SHALL execute inside the same transaction that holds the FOR UPDATE lock on the snapshot row, ensuring a consistent view of chunk state at check time.

#### Scenario: Publish draft with no indexed chunks returns 422

- **WHEN** `POST /api/admin/snapshots/:id/publish` is called on a DRAFT snapshot that has zero chunks with status INDEXED
- **THEN** the response SHALL be 422 with detail "Cannot publish: snapshot has no indexed chunks"

#### Scenario: Publish draft with pending chunks returns 422

- **WHEN** `POST /api/admin/snapshots/:id/publish` is called on a DRAFT snapshot that has 3 chunks with status PENDING
- **THEN** the response SHALL be 422 with detail "Cannot publish: 3 chunks are still processing"

#### Scenario: Publish draft with all chunks indexed succeeds

- **WHEN** `POST /api/admin/snapshots/:id/publish` is called on a DRAFT snapshot where all chunks have status INDEXED and at least one chunk exists
- **THEN** the publish SHALL succeed and the snapshot SHALL transition to PUBLISHED

#### Scenario: Guards use live SQL, not advisory counter

- **WHEN** the snapshot model has `chunk_count=10` but the actual count of INDEXED chunks in the `chunks` table is 0
- **THEN** the publish guard SHALL reject the publish based on the live SQL query result, not the advisory counter

---

### Requirement: Activate logic with deactivation and Agent pointer update

The activate action SHALL perform the following steps atomically within a single transaction:

1. Lock the target snapshot row with SELECT FOR UPDATE
2. Verify the target snapshot status is PUBLISHED (else 409)
3. Find the current ACTIVE snapshot for the same `(agent_id, knowledge_base_id)` scope with SELECT FOR UPDATE
4. If a current ACTIVE snapshot exists, transition it to PUBLISHED (deactivation)
5. Transition the target snapshot to ACTIVE and set `activated_at = now()`
6. Update `Agent.active_snapshot_id` to the target snapshot's ID

All steps SHALL execute in the same database transaction.

#### Scenario: Activate updates Agent.active_snapshot_id

- **WHEN** a PUBLISHED snapshot is activated
- **THEN** `Agent.active_snapshot_id` SHALL be set to the activated snapshot's ID

#### Scenario: Activate deactivates the previous active snapshot

- **WHEN** snapshot B is activated and snapshot A is currently ACTIVE for the same scope
- **THEN** snapshot A's status SHALL become PUBLISHED
- **AND** snapshot B's status SHALL become ACTIVE
- **AND** `Agent.active_snapshot_id` SHALL equal snapshot B's ID

#### Scenario: Publish with activate=true updates Agent pointer

- **WHEN** `POST /api/admin/snapshots/:id/publish?activate=true` succeeds
- **THEN** `Agent.active_snapshot_id` SHALL be set to the published-and-activated snapshot's ID

---

### Requirement: Convenience parameter ?activate=true on publish

The `POST /api/admin/snapshots/:id/publish` endpoint SHALL accept an optional query parameter `activate` (boolean, default false). When `activate=true`, the endpoint SHALL perform both publish and activate transitions in a single transaction: `DRAFT -> PUBLISHED -> ACTIVE`. The same publish guards SHALL apply. If any guard or transition fails, the entire operation SHALL be rolled back.

#### Scenario: Publish with activate=true performs both transitions

- **WHEN** `POST /api/admin/snapshots/:id/publish?activate=true` is called on a valid DRAFT snapshot
- **THEN** the snapshot status SHALL be ACTIVE after the call
- **AND** `published_at` and `activated_at` SHALL both be set

#### Scenario: Publish with activate=true rolls back on guard failure

- **WHEN** `POST /api/admin/snapshots/:id/publish?activate=true` is called on a DRAFT snapshot with pending chunks
- **THEN** the response SHALL be 422
- **AND** the snapshot status SHALL remain DRAFT

---

### Requirement: Partial unique index uq_one_active_per_scope

The `knowledge_snapshots` table SHALL have a partial unique index `uq_one_active_per_scope` on `(agent_id, knowledge_base_id) WHERE status = 'active'`. This index guarantees at the database level that at most one snapshot can be ACTIVE per `(agent_id, knowledge_base_id)` scope. A new Alembic migration SHALL create this index. The downgrade SHALL drop the index.

This is analogous to the existing `uq_one_draft_per_scope` partial unique index.

#### Scenario: Database prevents two active snapshots in same scope

- **WHEN** two snapshots in the same `(agent_id, knowledge_base_id)` scope both have status ACTIVE
- **THEN** the database SHALL raise a unique constraint violation

#### Scenario: Active snapshots in different scopes are allowed

- **WHEN** two snapshots in different `(agent_id, knowledge_base_id)` scopes both have status ACTIVE
- **THEN** no constraint violation SHALL occur

#### Scenario: Migration creates the partial unique index

- **WHEN** the migration is applied
- **THEN** the `uq_one_active_per_scope` index SHALL exist on the `knowledge_snapshots` table

#### Scenario: Migration downgrade removes the index

- **WHEN** the migration is downgraded
- **THEN** the `uq_one_active_per_scope` index SHALL no longer exist

---

### Requirement: Admin API list snapshots endpoint

The system SHALL provide `GET /api/admin/snapshots` that returns a list of snapshots. The endpoint SHALL accept optional `status` query parameters (repeatable, e.g. `?status=draft&status=published`) to filter by status. Without any `status` parameter, the endpoint SHALL return all snapshots except ARCHIVED. An optional `include_archived=true` parameter SHALL include ARCHIVED snapshots in the results. If `status=archived` is explicitly passed as a filter, archived snapshots SHALL be returned regardless of `include_archived`. The response SHALL be a JSON array of `SnapshotResponse` objects. The response status SHALL be 200.

#### Scenario: List all non-archived snapshots

- **WHEN** `GET /api/admin/snapshots` is called without parameters
- **THEN** the response SHALL contain all snapshots with status DRAFT, PUBLISHED, or ACTIVE
- **AND** ARCHIVED snapshots SHALL NOT be included

#### Scenario: Filter by specific status

- **WHEN** `GET /api/admin/snapshots?status=draft` is called
- **THEN** the response SHALL contain only DRAFT snapshots

#### Scenario: Filter by multiple statuses

- **WHEN** `GET /api/admin/snapshots?status=draft&status=published` is called
- **THEN** the response SHALL contain only DRAFT and PUBLISHED snapshots

#### Scenario: Include archived snapshots

- **WHEN** `GET /api/admin/snapshots?include_archived=true` is called
- **THEN** the response SHALL contain snapshots of all statuses including ARCHIVED

#### Scenario: Explicit archived filter returns archived snapshots

- **WHEN** `GET /api/admin/snapshots?status=archived` is called
- **THEN** the response SHALL contain ARCHIVED snapshots regardless of `include_archived`

---

### Requirement: Admin API get snapshot endpoint

The system SHALL provide `GET /api/admin/snapshots/:id` that returns a single snapshot by ID. The response SHALL be a `SnapshotResponse` object with status 200. If the snapshot does not exist, the response SHALL be 404 with detail "Snapshot not found".

#### Scenario: Get existing snapshot returns 200

- **WHEN** `GET /api/admin/snapshots/:id` is called with a valid snapshot ID
- **THEN** the response SHALL be 200 with the snapshot data

#### Scenario: Get non-existent snapshot returns 404

- **WHEN** `GET /api/admin/snapshots/:id` is called with a UUID that does not match any snapshot
- **THEN** the response SHALL be 404 with detail "Snapshot not found"

---

### Requirement: Admin API publish snapshot endpoint

The system SHALL provide `POST /api/admin/snapshots/:id/publish` that transitions a DRAFT snapshot to PUBLISHED (or ACTIVE if `?activate=true`). The endpoint SHALL return a `SnapshotResponse` with the updated snapshot on success (200). Error responses:

- 404 if the snapshot does not exist
- 409 if the snapshot is not in DRAFT status
- 422 if publish guards fail (empty snapshot or pending chunks)

#### Scenario: Publish valid draft returns 200

- **WHEN** `POST /api/admin/snapshots/:id/publish` is called on a DRAFT snapshot with all chunks INDEXED
- **THEN** the response SHALL be 200 with the snapshot in PUBLISHED status

#### Scenario: Publish non-existent snapshot returns 404

- **WHEN** `POST /api/admin/snapshots/:id/publish` is called with a non-existent ID
- **THEN** the response SHALL be 404

#### Scenario: Publish non-draft returns 409

- **WHEN** `POST /api/admin/snapshots/:id/publish` is called on an ACTIVE snapshot
- **THEN** the response SHALL be 409

#### Scenario: Publish empty draft returns 422

- **WHEN** `POST /api/admin/snapshots/:id/publish` is called on a DRAFT with no indexed chunks
- **THEN** the response SHALL be 422

---

### Requirement: Admin API activate snapshot endpoint

The system SHALL provide `POST /api/admin/snapshots/:id/activate` that transitions a PUBLISHED snapshot to ACTIVE. The endpoint SHALL return a `SnapshotResponse` with the updated snapshot on success (200). Error responses:

- 404 if the snapshot does not exist
- 409 if the snapshot is not in PUBLISHED status
- 409 if a concurrent activate conflict is detected (IntegrityError from unique index)

#### Scenario: Activate published snapshot returns 200

- **WHEN** `POST /api/admin/snapshots/:id/activate` is called on a PUBLISHED snapshot
- **THEN** the response SHALL be 200 with the snapshot in ACTIVE status

#### Scenario: Activate non-published returns 409

- **WHEN** `POST /api/admin/snapshots/:id/activate` is called on a DRAFT snapshot
- **THEN** the response SHALL be 409

#### Scenario: Concurrent activate conflict returns 409

- **WHEN** two concurrent activate calls target different PUBLISHED snapshots in the same scope and the unique index violation is raised
- **THEN** the losing call SHALL return 409 with detail "Another snapshot is being activated concurrently, retry"

---

### Requirement: SnapshotResponse schema

The API response schema `SnapshotResponse` SHALL contain the following fields: `id` (UUID), `agent_id` (UUID), `knowledge_base_id` (UUID), `name` (string), `description` (string or null), `status` (enum: draft, published, active, archived), `chunk_count` (integer), `created_at` (ISO datetime), `published_at` (ISO datetime or null), `activated_at` (ISO datetime or null), `archived_at` (ISO datetime or null). The `chunk_count` field is the advisory counter from the model, used for display purposes only.

#### Scenario: Response contains all required fields

- **WHEN** any snapshot endpoint returns a `SnapshotResponse`
- **THEN** all specified fields SHALL be present with correct types

#### Scenario: Timestamps reflect lifecycle events

- **WHEN** a snapshot has been published and activated
- **THEN** `published_at` and `activated_at` SHALL be non-null ISO datetime strings

---

### Requirement: Concurrency safety via FOR UPDATE locking

Both `publish` and `activate` operations SHALL acquire a row-level lock via `SELECT ... FROM knowledge_snapshots WHERE id = :id FOR UPDATE` before checking guards or performing state transitions. This serializes concurrent operations on the same snapshot row. The `activate` operation SHALL additionally lock the current ACTIVE snapshot row (if any) with FOR UPDATE before deactivating it. On `IntegrityError` from the `uq_one_active_per_scope` unique index during activate, the service SHALL catch the error and return 409.

#### Scenario: Concurrent publishes on the same draft are serialized

- **WHEN** two concurrent publish calls target the same DRAFT snapshot
- **THEN** one SHALL succeed and the other SHALL receive 409 (snapshot is already PUBLISHED)

#### Scenario: Concurrent activates are serialized by lock and unique index

- **WHEN** two concurrent activate calls target different PUBLISHED snapshots in the same scope
- **THEN** one SHALL succeed and the other SHALL receive 409 due to IntegrityError from the unique index

#### Scenario: Publish guard queries run under the same lock

- **WHEN** publish acquires the FOR UPDATE lock and runs guard queries
- **THEN** the guard queries SHALL see a consistent view of chunks within the same transaction

---

### Requirement: SnapshotService with get_or_create_draft and get_active_snapshot

The system SHALL provide a `SnapshotService` at `app/services/snapshot.py` with a `get_or_create_draft(session, agent_id, knowledge_base_id) -> KnowledgeSnapshot` method. The method SHALL return the persisted `KnowledgeSnapshot` row for the given `(agent_id, knowledge_base_id)` scope. If no draft exists, it SHALL create one with `status=DRAFT`, implementation-defined ingestion defaults for `name` and `description`, `owner_id=NULL`, and timestamps populated by the model mixins.

The `SnapshotService` SHALL additionally provide a `get_active_snapshot(agent_id, knowledge_base_id) -> KnowledgeSnapshot | None` method. The method SHALL query the `knowledge_snapshots` table for a snapshot with `status='active'` matching the given `(agent_id, knowledge_base_id)` scope. If an active snapshot exists, it SHALL be returned. If no active snapshot exists for the scope, the method SHALL return `None`. The method SHALL NOT raise an exception when no active snapshot is found — callers are responsible for handling the `None` case.

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

The `SnapshotService` SHALL provide an `ensure_draft_or_rebind(session, snapshot_id, agent_id, knowledge_base_id) -> KnowledgeSnapshot` method. This method SHALL always return a FOR UPDATE-locked DRAFT snapshot. The method SHALL:

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

- **State machine unit tests with real PG**: verify all valid transitions (draft->published, published->active, active->published on deactivation, draft->active via publish+activate). Verify all invalid transitions return 409 with correct messages.
- **Publish guard tests with real PG**: verify publish with zero indexed chunks returns 422, publish with pending chunks returns 422 with count, publish with all indexed chunks succeeds. Verify guards use live SQL not advisory counter.
- **Activate logic tests with real PG**: verify Agent.active_snapshot_id is updated, previous active is deactivated to published, first activation with no current active works.
- **Partial unique index test**: verify that two ACTIVE snapshots in the same scope raise IntegrityError, different scopes do not conflict.
- **Migration test**: verify migration applies cleanly and the uq_one_active_per_scope index exists.
- **Concurrency tests with real PG**: verify concurrent publishes serialize correctly, concurrent activates produce one success and one 409, publish-during-ingestion scenario.
- **API endpoint tests**: verify all 4 endpoints (list, get, publish, activate) with correct status codes, filtering, and error responses.
- **SnapshotResponse schema tests**: verify all fields are present and correctly typed.
- **get_active_snapshot integration tests with real PG**: verify method returns the ACTIVE snapshot when one exists for the scope. Verify method returns `None` when no ACTIVE snapshot exists. Verify method returns the correct snapshot when multiple scopes have different active snapshots. Verify method does not return DRAFT, PUBLISHED, or ARCHIVED snapshots.
- **ensure_draft_or_rebind tests with real PG**: verify method returns locked DRAFT when snapshot is still draft. Verify method rebinds to new draft when snapshot status is PUBLISHED. Verify the returned snapshot is always FOR UPDATE-locked. Verify serialization with concurrent publish.
