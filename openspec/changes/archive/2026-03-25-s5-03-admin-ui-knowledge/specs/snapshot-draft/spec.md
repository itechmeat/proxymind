## ADDED Requirements

### Requirement: POST /api/admin/snapshots create-or-get-draft endpoint

The API SHALL expose a `POST /api/admin/snapshots` endpoint that returns the current draft snapshot for the given scope, creating one if none exists. The endpoint SHALL accept `agent_id` and `knowledge_base_id` query parameters, both with defaults matching the canonical seeded IDs. The endpoint SHALL delegate to the existing `SnapshotService.get_or_create_draft()` method. The endpoint SHALL return `200 OK` for both the create and reuse paths — it is a thin wrapper over existing service logic and does not distinguish between newly created and pre-existing drafts in its response status. The response body SHALL conform to the existing `SnapshotResponse` schema. The endpoint SHALL NOT require authentication (explicit security exception -- local-only deployment; `TODO(S7-01)` MUST be present in the codebase).

#### Scenario: Draft created when none exists

- **WHEN** a POST request is sent to `/api/admin/snapshots` and no DRAFT snapshot exists for the given scope
- **THEN** the response status SHALL be 200
- **AND** the response body SHALL conform to `SnapshotResponse`
- **AND** a new DRAFT snapshot SHALL be created in the database

#### Scenario: Existing draft returned when one already exists

- **WHEN** a POST request is sent to `/api/admin/snapshots` and a DRAFT snapshot already exists for the given scope
- **THEN** the response status SHALL be 200
- **AND** the response body SHALL contain the existing draft snapshot
- **AND** no new snapshot SHALL be created

#### Scenario: Default scope parameters used when omitted

- **WHEN** a POST request is sent to `/api/admin/snapshots` without `agent_id` or `knowledge_base_id` query parameters
- **THEN** the endpoint SHALL use the default agent ID and default knowledge base ID from the constants module

#### Scenario: Response conforms to SnapshotResponse schema

- **WHEN** a POST request to `/api/admin/snapshots` succeeds
- **THEN** the response body SHALL include all fields defined in the `SnapshotResponse` schema (id, name, status, chunk_count, timestamps, etc.)

#### Scenario: Endpoint accessible without authentication

- **WHEN** a POST request is sent to `/api/admin/snapshots` without any authorization header
- **THEN** the request SHALL be processed normally (not rejected for missing auth)
