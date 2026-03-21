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
