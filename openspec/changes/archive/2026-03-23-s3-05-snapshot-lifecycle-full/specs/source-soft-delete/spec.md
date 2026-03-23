## ADDED Requirements

### Requirement: Source soft delete endpoint

The system SHALL provide `DELETE /api/admin/sources/{source_id}` that performs a soft delete on the specified source. The endpoint SHALL accept optional `agent_id` and `knowledge_base_id` query parameters using the endpoint's default scope values when omitted. Source lookup MUST be scoped by the resolved `agent_id` and `knowledge_base_id` values to prevent cross-scope deletion.

#### Scenario: Soft delete marks the source as deleted

- **WHEN** `DELETE /api/admin/sources/{source_id}` is called with a valid source ID
- **THEN** the source's `status` SHALL be set to `DELETED`
- **AND** the source's `deleted_at` SHALL be set to the current timestamp
- **AND** the response SHALL be 200

#### Scenario: Source lookup is scoped

- **WHEN** `DELETE /api/admin/sources/{source_id}` is called with an ID that exists in a different scope
- **THEN** the response SHALL be 404

---

### Requirement: Dual-field soft delete contract

On soft delete, both `status = DELETED` and `deleted_at = now()` MUST be set together in the same operation. The `status` field is the authoritative signal for business logic (ingestion guard, source listing, all queries). The `deleted_at` field records the precise timestamp for audit and potential future undo. Code MUST NOT check only one field without the other.

#### Scenario: Both fields are set atomically

- **WHEN** a source is soft-deleted
- **THEN** `source.status` SHALL be `DELETED`
- **AND** `source.deleted_at` SHALL be a non-null timestamp
- **AND** both fields SHALL be set in the same database transaction

#### Scenario: Neither field is set independently

- **WHEN** any code path sets `status = DELETED`
- **THEN** it MUST also set `deleted_at = now()` in the same operation
- **AND** vice versa

---

### Requirement: Draft chunk cascade on soft delete

When a source is soft-deleted, all chunks belonging to that source in DRAFT snapshots SHALL be removed from both Qdrant and PostgreSQL. Qdrant deletion MUST occur before PostgreSQL deletion so the system only proceeds to PostgreSQL after vector cleanup succeeds, preferring orphaned PostgreSQL rows over searchable stale vectors if a later failure occurs. The affected draft snapshot's `chunk_count` SHALL be decremented by the number of removed chunks. All PostgreSQL mutations for the soft delete (`Source.status`, `Source.deleted_at`, `Chunk` deletions, and `KnowledgeSnapshot.chunk_count` updates) SHALL be committed in the same database transaction.

#### Scenario: Draft chunks are removed from Qdrant and PostgreSQL

- **WHEN** a source with 5 chunks in a DRAFT snapshot is soft-deleted
- **THEN** those 5 chunks SHALL be deleted from Qdrant first
- **AND** then deleted from PostgreSQL
- **AND** the draft snapshot's `chunk_count` SHALL be decremented by 5

#### Scenario: Multiple draft snapshots are cleaned up

- **WHEN** a source has chunks in two different DRAFT snapshots
- **THEN** chunks in both drafts SHALL be removed
- **AND** both snapshots' `chunk_count` SHALL be decremented accordingly

#### Scenario: Qdrant deletion failure aborts the database changes

- **WHEN** Qdrant deletion fails while cleaning up draft chunks
- **THEN** the soft delete SHALL fail
- **AND** no PostgreSQL mutations for `Source.status`, `Source.deleted_at`, draft chunk deletions, or `chunk_count` updates SHALL be committed

---

### Requirement: Published and active snapshot chunks are preserved

Chunks belonging to the soft-deleted source in PUBLISHED or ACTIVE snapshots SHALL NOT be modified or removed. Published and active snapshots are immutable — removing chunks would break the snapshot contract and affect live retrieval. Instead, the response SHALL include warnings informing the owner that chunks remain visible.

#### Scenario: Published snapshot chunks remain untouched

- **WHEN** a source has 10 chunks in a PUBLISHED snapshot and 3 chunks in a DRAFT snapshot
- **AND** the source is soft-deleted
- **THEN** the 10 chunks in the PUBLISHED snapshot SHALL remain in both Qdrant and PostgreSQL
- **AND** the 3 chunks in the DRAFT snapshot SHALL be removed
- **AND** the response SHALL include a warning about the preserved published chunks

#### Scenario: Active snapshot chunks remain untouched

- **WHEN** a source has chunks in an ACTIVE snapshot
- **AND** the source is soft-deleted
- **THEN** the chunks in the ACTIVE snapshot SHALL NOT be modified

---

### Requirement: Soft delete warnings in response

When a soft-deleted source has chunks that persist in PUBLISHED or ACTIVE snapshots, the response SHALL include a `warnings` array with descriptive messages. The warning message SHALL indicate the number of affected snapshots and that chunks will remain visible until a new snapshot replaces them.

#### Scenario: Warning returned for published/active chunks

- **WHEN** a source is soft-deleted and it has chunks in 2 published/active snapshots
- **THEN** the `warnings` array SHALL contain a message like "Source is referenced in 2 published/active snapshot(s). Chunks will remain visible until a new snapshot replaces them."

#### Scenario: No warnings when only draft chunks exist

- **WHEN** a source is soft-deleted and it has chunks only in DRAFT snapshots
- **THEN** the `warnings` array SHALL be empty

---

### Requirement: Soft delete is idempotent

If a source has already been soft-deleted (`status = DELETED`), a subsequent `DELETE` request for the same source SHALL return 200 with no warnings and no side effects. The operation SHALL NOT re-execute the draft cascade or modify timestamps. Empty warnings on idempotent deletes are intentional even if published/active chunks still exist; warnings are emitted only on the first transition to `DELETED`.

#### Scenario: Already-deleted source returns idempotent 200

- **WHEN** `DELETE /api/admin/sources/{source_id}` is called on a source with `status = DELETED`
- **THEN** the response SHALL be 200
- **AND** the `warnings` array SHALL be empty
- **AND** no Qdrant or PostgreSQL deletions SHALL occur

---

### Requirement: Source soft delete error cases

The endpoint SHALL return 404 if the source ID does not match any source within the given scope.

#### Scenario: Non-existent source returns 404

- **WHEN** `DELETE /api/admin/sources/{source_id}` is called with a UUID that does not match any source in the scope
- **THEN** the response SHALL be 404 with detail "Source not found"

---

### Requirement: Source soft delete response schema

The soft delete response SHALL be a JSON object with the following fields:

- `id` (UUID): the source ID
- `title` (string): the source title
- `source_type` (string): the source type (e.g., `"pdf"`, `"markdown"`)
- `status` (string): `"deleted"`
- `deleted_at` (ISO datetime): the deletion timestamp
- `warnings` (array of strings): any warning messages about persisted chunks

#### Scenario: Response contains all required fields

- **WHEN** a source is soft-deleted successfully
- **THEN** the response SHALL contain `id`, `title`, `source_type`, `status`, `deleted_at`, and `warnings`
- **AND** `status` SHALL be `"deleted"`
- **AND** `deleted_at` SHALL be a valid ISO datetime string

---

## Test Coverage

### CI tests (deterministic)

The following stable behavior MUST be covered by CI tests before archive:

- **Draft-only cascade**: delete source with chunks only in draft -> chunks removed from PG + Qdrant, `chunk_count` decremented.
- **Published preservation**: delete source with chunks in published snapshot -> source deleted, published chunks untouched, warnings returned.
- **Mixed draft and published**: delete source with chunks in both -> draft cleaned up, published preserved, warnings returned.
- **Idempotent delete**: delete already-deleted source -> 200 with empty warnings.
- **Error: not found**: delete non-existent source -> 404.
- **Dual-field contract**: verify both `status` and `deleted_at` are set on soft delete.
- **Qdrant failure handling**: if draft vector cleanup fails, no PostgreSQL soft-delete mutations are committed.
- **API endpoint tests**: verify HTTP status codes and response schema for all soft delete cases.
