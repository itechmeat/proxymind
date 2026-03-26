## ADDED Requirements

### Requirement: GET /api/admin/sources list endpoint

The API SHALL expose a `GET /api/admin/sources` endpoint that returns non-deleted sources for the given scope. The endpoint SHALL filter by `agent_id` and `knowledge_base_id` query parameters, both with defaults matching the canonical seeded IDs. The endpoint SHALL exclude sources with status DELETED. Results SHALL be ordered by `created_at` DESC (newest first). The endpoint SHALL NOT require authentication (explicit security exception -- local-only deployment; `TODO(S7-01)` MUST be present in the codebase).

The response SHALL be a JSON array where each item includes: `id` (UUID), `title` (string), `source_type` (string), `status` (string), `description` (string or null), `public_url` (string or null), `file_size_bytes` (integer or null), `language` (string or null), and `created_at` (ISO 8601 datetime string).

#### Scenario: Successful retrieval of sources

- **WHEN** a GET request is sent to `/api/admin/sources` with default scope parameters
- **THEN** the response status SHALL be 200
- **AND** the response body SHALL be a JSON array of source objects
- **AND** each object SHALL contain the fields: `id`, `title`, `source_type`, `status`, `description`, `public_url`, `file_size_bytes`, `language`, `created_at`

#### Scenario: Deleted sources excluded

- **WHEN** the database contains sources with status DELETED for the given scope
- **THEN** the response SHALL NOT include those sources

#### Scenario: Sources ordered by created_at descending

- **WHEN** multiple sources exist for the given scope
- **THEN** the response array SHALL be ordered by `created_at` DESC (newest first)

#### Scenario: Filtering by agent_id and knowledge_base_id

- **WHEN** a GET request is sent with explicit `agent_id` and `knowledge_base_id` query parameters
- **THEN** only sources matching both parameters SHALL be returned

#### Scenario: Default scope parameters used when omitted

- **WHEN** a GET request is sent to `/api/admin/sources` without `agent_id` or `knowledge_base_id` query parameters
- **THEN** the endpoint SHALL use the default agent ID and default knowledge base ID from the constants module

#### Scenario: Empty list when no sources exist

- **WHEN** no non-deleted sources exist for the given scope
- **THEN** the response status SHALL be 200
- **AND** the response body SHALL be an empty JSON array

#### Scenario: Endpoint accessible without authentication

- **WHEN** a GET request is sent to `/api/admin/sources` without any authorization header
- **THEN** the request SHALL be processed normally (not rejected for missing auth)
