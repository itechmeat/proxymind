## Purpose

Snapshot rollback endpoint, auto-target selection by activated_at, toggle behavior, scope isolation, and concurrency safety. Introduced by S3-05.

## Requirements

### Requirement: Rollback endpoint reverts the active snapshot

The system SHALL provide `POST /api/admin/snapshots/{snapshot_id}/rollback` that demotes the currently ACTIVE snapshot to PUBLISHED and re-activates the most recently demoted PUBLISHED snapshot in the same scope. The endpoint SHALL accept optional `agent_id` and `knowledge_base_id` query parameters using the endpoint's default scope values when omitted. These query parameters scope lookup of the current snapshot row; if the requested snapshot does not exist in the resolved scope, the response SHALL be 404. The scope for rollback target selection MUST be derived from the locked current snapshot's `agent_id` and `knowledge_base_id` — never from query parameters alone — to prevent cross-scope rollback.

#### Scenario: Rollback reactivates the previously demoted snapshot

- **WHEN** `POST /api/admin/snapshots/{snapshot_id}/rollback` is called where `{snapshot_id}` is an ACTIVE snapshot
- **AND** a PUBLISHED snapshot exists in the same scope with a non-null `activated_at`
- **THEN** the ACTIVE snapshot SHALL transition to PUBLISHED
- **AND** the demoted snapshot's existing `activated_at` SHALL be preserved
- **AND** the PUBLISHED snapshot with the most recent `activated_at` SHALL transition to ACTIVE
- **AND** the target snapshot's `activated_at` SHALL be set to the current timestamp
- **AND** `Agent.active_snapshot_id` SHALL be updated to the target snapshot's ID

#### Scenario: Scope is derived from the locked active snapshot

- **WHEN** `POST /api/admin/snapshots/{snapshot_id}/rollback` is called
- **THEN** the system SHALL lock the snapshot row with `SELECT ... FOR UPDATE`
- **AND** derive `agent_id` and `knowledge_base_id` from the locked row
- **AND** use those derived values to query for the rollback target

---

### Requirement: Rollback auto-selects the previous published snapshot by activated_at

The rollback target SHALL be selected as the PUBLISHED snapshot with the most recent `activated_at` timestamp within the same `(agent_id, knowledge_base_id)` scope. The target MUST have a non-null `activated_at` (indicating it was previously active). The target row SHALL be locked with `SELECT ... FOR UPDATE` before any state transition. The status change for the current snapshot, the status and `activated_at` update for the target snapshot, and the `Agent.active_snapshot_id` update SHALL occur atomically in a single database transaction.

#### Scenario: Target is the published snapshot with the freshest activated_at

- **WHEN** the scope contains two PUBLISHED snapshots: A with `activated_at = 2026-01-01` and C with `activated_at = 2026-01-03`
- **AND** snapshot B is ACTIVE
- **THEN** rollback SHALL select snapshot C as the target (most recent `activated_at`)

#### Scenario: Published snapshot without activated_at is not a rollback target

- **WHEN** the scope contains a PUBLISHED snapshot that was never activated (`activated_at IS NULL`)
- **THEN** that snapshot SHALL NOT be selected as the rollback target

---

### Requirement: Repeated rollback toggles between the two most recent snapshots

Because the rolled-back-to snapshot receives a new `activated_at = now()`, a subsequent rollback SHALL select the snapshot that was just demoted — creating a toggle between the two most recent snapshots. Deeper history traversal is not supported by rollback; the owner SHALL use the `activate` endpoint with an explicit snapshot ID for that purpose.

#### Scenario: Second rollback reverses the first

- **WHEN** snapshot B is active and rollback promotes snapshot A
- **AND** rollback is called again on snapshot A (now active)
- **THEN** snapshot B SHALL be re-activated (it was just demoted and has the freshest `activated_at` among PUBLISHED snapshots)

---

### Requirement: Rollback preserves activated_at on demotion

When the ACTIVE snapshot is demoted to PUBLISHED during rollback, its existing `activated_at` value SHALL be preserved. This timestamp records the last activation time and is used by future rollback operations to identify the most recently demoted snapshot.

#### Scenario: Demoted snapshot retains its activated_at

- **WHEN** snapshot B is ACTIVE with `activated_at = 2026-01-15T10:00:00Z`
- **AND** rollback demotes snapshot B to PUBLISHED
- **THEN** snapshot B's `activated_at` SHALL remain `2026-01-15T10:00:00Z`

---

### Requirement: Rollback response schema

The rollback endpoint SHALL return a JSON response containing `rolled_back_from` and `rolled_back_to` objects. Each object SHALL contain: `id` (UUID), `name` (string), `status` (enum), `published_at` (datetime), `activated_at` (datetime). The `rolled_back_from` object SHALL have `status: "published"`. The `rolled_back_to` object SHALL have `status: "active"`.

#### Scenario: Response contains both snapshot summaries

- **WHEN** rollback succeeds
- **THEN** the response SHALL contain `rolled_back_from` with `status = "published"` and `rolled_back_to` with `status = "active"`
- **AND** both objects SHALL include `id`, `name`, `published_at`, and `activated_at` fields

---

### Requirement: Rollback error cases

The rollback endpoint SHALL return the following error responses:

- **404 Not Found**: the snapshot ID does not match any snapshot
- **409 Conflict**: the snapshot is not in ACTIVE status ("Only the active snapshot can be rolled back")
- **409 Conflict**: no previously activated PUBLISHED snapshot exists in the same scope ("No previously activated snapshot available for rollback")

Concurrent rollback or activate requests SHALL be serialized by row-level `FOR UPDATE` locks on both the current active and target rows. If a concurrent operation changes the state before the lock is acquired, the appropriate 409 error SHALL be returned.

#### Scenario: Rollback on non-existent snapshot returns 404

- **WHEN** `POST /api/admin/snapshots/{snapshot_id}/rollback` is called with a UUID that does not match any snapshot
- **THEN** the response SHALL be 404 with detail "Snapshot not found"

#### Scenario: Rollback on non-active snapshot returns 409

- **WHEN** `POST /api/admin/snapshots/{snapshot_id}/rollback` is called on a PUBLISHED snapshot
- **THEN** the response SHALL be 409 with detail "Only the active snapshot can be rolled back"

#### Scenario: Rollback with no previous snapshot returns 409

- **WHEN** `POST /api/admin/snapshots/{snapshot_id}/rollback` is called on the only ACTIVE snapshot in the scope
- **AND** no PUBLISHED snapshot with non-null `activated_at` exists in the same scope
- **THEN** the response SHALL be 409 with detail "No previously activated snapshot available for rollback"

#### Scenario: Concurrent rollback is serialized by row locks

- **WHEN** two concurrent rollback requests target the same ACTIVE snapshot
- **THEN** one SHALL succeed and the other SHALL receive 409 (snapshot is no longer ACTIVE after the first completes)

---

## Test Coverage

### CI tests (deterministic)

The following stable behavior MUST be covered by CI tests before archive:

- **Rollback happy path**: publish A, activate A, publish B, activate B, rollback on B -> A is active, B is published, Agent pointer updated.
- **Toggle behavior**: rollback twice -> returns to original active snapshot.
- **Error: not active**: rollback on PUBLISHED snapshot -> 409.
- **Error: no previous**: rollback on first-ever active snapshot (no demoted published) -> 409.
- **Error: not found**: rollback on non-existent UUID -> 404.
- **Scope isolation**: rollback auto-selects target from the same scope only, ignoring published snapshots from other scopes.
- **API endpoint tests**: verify HTTP status codes and response schema for all rollback cases.
