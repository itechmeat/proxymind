## MODIFIED Requirements

### Requirement: Snapshot state machine transitions

**[Modified by S3-05]** The system SHALL implement a snapshot state machine with the following valid transitions:

- `DRAFT -> PUBLISHED` via the publish action
- `PUBLISHED -> ACTIVE` via the activate action
- `ACTIVE -> PUBLISHED` via internal deactivation (when another snapshot is activated)
- `ACTIVE -> PUBLISHED` via rollback (auto-select the most recently demoted PUBLISHED snapshot by `activated_at` and re-activate it; the current ACTIVE snapshot is demoted to PUBLISHED)
- `DRAFT -> ACTIVE` via publish with `?activate=true` (both transitions in one transaction)

Any transition not listed above SHALL be rejected with HTTP 409 Conflict, including a message describing the current status and allowed actions. The `ARCHIVED` state is a terminal state if set by explicit owner action; S3-05 does not add an archive endpoint, but activation attempts against an already archived snapshot MUST still be rejected.

**Note:** When a snapshot is demoted from ACTIVE to PUBLISHED (whether by deactivation or rollback), its `activated_at` value SHALL be preserved. This timestamp records the last activation time and is used by future rollback operations to identify the most recently demoted snapshot as the rollback target.

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

#### Scenario: Active snapshot is demoted via rollback

- **WHEN** `POST /api/admin/snapshots/:id/rollback` is called on the ACTIVE snapshot
- **AND** a PUBLISHED snapshot with non-null `activated_at` exists in the same scope
- **THEN** the ACTIVE snapshot SHALL transition to PUBLISHED with its `activated_at` preserved
- **AND** the target PUBLISHED snapshot SHALL transition to ACTIVE with `activated_at` set to `now()`
- **AND** `Agent.active_snapshot_id` SHALL be updated to the target snapshot's ID

#### Scenario: Rollback with no candidate returns 409

- **WHEN** `POST /api/admin/snapshots/:id/rollback` is called on the ACTIVE snapshot
- **AND** no PUBLISHED snapshot with non-null `activated_at` exists in the same scope
- **THEN** the response SHALL be 409 Conflict with detail "No previously activated snapshot available for rollback"

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
- **THEN** the response SHALL be 409 Conflict with detail "Cannot activate: snapshot status is 'draft', publish it first"

#### Scenario: Activate an archived snapshot returns 409

- **WHEN** `POST /api/admin/snapshots/:id/activate` is called on an ARCHIVED snapshot
- **THEN** the response SHALL be 409 Conflict with detail "Cannot activate: snapshot status is 'archived', archived snapshots cannot be activated"

#### Scenario: First activation with no current active snapshot

- **WHEN** `POST /api/admin/snapshots/:id/activate` is called on a PUBLISHED snapshot and no ACTIVE snapshot exists for the scope
- **THEN** the snapshot SHALL transition to ACTIVE without deactivating any other snapshot
