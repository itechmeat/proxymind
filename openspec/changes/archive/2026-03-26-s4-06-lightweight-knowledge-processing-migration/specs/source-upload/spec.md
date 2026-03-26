# source-upload (delta)

**Story:** S4-06 — Lightweight Knowledge Processing Migration
**Status:** MODIFIED capability
**Test coverage requirement:** All stable behavior introduced or modified by this change MUST be covered by CI tests before archive.

---

## MODIFIED Requirements

### Requirement: Upload metadata validation

The `metadata` field SHALL be validated as JSON conforming to a Pydantic schema with the following fields: `title` (string, required, 1-255 characters), `description` (string, optional, max 2000 characters), `public_url` (string, optional, valid HTTP/HTTPS URL, max 2048 characters), `catalog_item_id` (UUID, optional), `language` (string, optional, max 32 characters), `processing_hint` (string, optional, one of `"auto"` or `"external"`, default `"auto"`). The `source_type` SHALL be determined automatically from the file extension and SHALL NOT be part of the metadata input.

The `language` field from `SourceUploadMetadata` SHALL be persisted on the `Source` record. The `source.py` service `create_source_and_task()` method MUST pass `language=metadata.language` to the Source constructor. Empty or whitespace-only `language` values SHALL be normalized to NULL before persistence. A nullable `language` column (VARCHAR(32)) exists on the `sources` table (added in S2-02 migration 004). Existing sources have NULL, which means "use system default."

**[Modified by S4-06]** The `SourceUploadMetadata` Pydantic schema SHALL gain an optional `processing_hint` field of type `Literal["auto", "external"]` with a default value of `"auto"`. This field allows users to explicitly request external processing (Document AI, Path C) for complex documents. The field is fully backward-compatible -- omitting it defaults to `"auto"`, which preserves existing routing behavior.

#### Scenario: Missing title in metadata (unchanged)

- **WHEN** a POST request is sent with metadata JSON that lacks the `title` field
- **THEN** the response status SHALL be 422

#### Scenario: processing_hint defaults to "auto" when omitted

- **WHEN** a POST request is sent with valid metadata that does not include `processing_hint`
- **THEN** the `processing_hint` SHALL default to `"auto"`
- **AND** the upload SHALL proceed with standard automatic routing

#### Scenario: processing_hint "external" is accepted

- **WHEN** a POST request is sent with metadata containing `"processing_hint": "external"`
- **THEN** the response status SHALL be 202
- **AND** the `processing_hint` value SHALL be stored for downstream routing

#### Scenario: processing_hint "auto" is accepted

- **WHEN** a POST request is sent with metadata containing `"processing_hint": "auto"`
- **THEN** the response status SHALL be 202

#### Scenario: Invalid processing_hint value is rejected

- **WHEN** a POST request is sent with metadata containing `"processing_hint": "fast"` (not in allowed values)
- **THEN** the response status SHALL be 422
- **AND** the response body SHALL contain validation error details indicating allowed values

#### Scenario: Language field is persisted on Source record (unchanged)

- **WHEN** a POST request is sent with metadata containing `"language": "russian"`
- **THEN** the created Source record in PostgreSQL SHALL have `language` set to `"russian"`

---

### Requirement: Source and BackgroundTask creation with commit-before-enqueue

The upload endpoint SHALL follow the commit-before-enqueue pattern: (1) upload file to SeaweedFS, (2) create Source (status PENDING) and BackgroundTask (status PENDING) in PostgreSQL and COMMIT, (3) enqueue the arq job. On enqueue success, the `arq_job_id` SHALL be saved on the BackgroundTask and committed. On enqueue failure, a compensating update SHALL mark both Source and BackgroundTask as FAILED with an error message, and the endpoint SHALL return 500.

**[Modified by S4-06]** When `processing_hint` is not `"auto"`, the value SHALL be stored in `BackgroundTask.result_metadata` so that the ingestion worker can read it during routing. When `processing_hint` is `"auto"` (the default), it SHALL NOT be stored in `result_metadata` — the worker SHALL treat absence of the key as `"auto"`. This follows the existing pattern where only non-default values are stored in `result_metadata` (same as `skip_embedding`).

Note: `BackgroundTask.result_metadata` is a transport mechanism. The canonical audit record is `DocumentVersion.processing_hint`, which is always written by the worker (defaulting to `"auto"` when the key is absent from `result_metadata`).

#### Scenario: Non-default processing_hint stored in BackgroundTask result_metadata

- **WHEN** a file is uploaded with `processing_hint="external"`
- **AND** the response is 202
- **THEN** the `BackgroundTask.result_metadata` SHALL contain `{"processing_hint": "external"}`

#### Scenario: Default processing_hint omitted from result_metadata

- **WHEN** a file is uploaded without specifying `processing_hint` (default `"auto"`)
- **AND** the response is 202
- **THEN** the `BackgroundTask.result_metadata` SHALL NOT contain a `"processing_hint"` key
- **AND** the worker SHALL treat the absence as `"auto"`

#### Scenario: Source and Task records exist in PG after successful upload (unchanged)

- **WHEN** a file is successfully uploaded and the response is 202
- **THEN** a Source record SHALL exist in PostgreSQL with status PENDING and the correct `source_type`, `title`, `file_path`, and `agent_id`
- **AND** a BackgroundTask record SHALL exist with status PENDING, `task_type` INGESTION, and `source_id` referencing the Source

#### Scenario: arq job is enqueued after PG commit (unchanged)

- **WHEN** Source and BackgroundTask are committed to PostgreSQL
- **THEN** an arq job SHALL be enqueued with the `task_id`
- **AND** the BackgroundTask record SHALL be updated with the `arq_job_id`

---

### Requirement: DocumentVersion gains processing_hint column

**[Added by S4-06]** The `DocumentVersion` model at `app/db/models/knowledge.py` SHALL gain a `processing_hint` column of type `String(32)`, nullable, for audit purposes. This column stores the user-provided `processing_hint` value (`"auto"` or `"external"`) at the time of upload, enabling traceability of routing decisions. The column SHALL be added via an Alembic migration in the same migration file that adds `PATH_C` to the `processing_path_enum`.

The ingestion worker SHALL populate `DocumentVersion.processing_hint` by reading `BackgroundTask.result_metadata.get("processing_hint", "auto")` — defaulting to `"auto"` when the key is absent (which is the case for default uploads).

#### Scenario: processing_hint column stores user-provided value

- **WHEN** a document is ingested with `processing_hint="external"`
- **THEN** the `DocumentVersion.processing_hint` column SHALL contain `"external"`

#### Scenario: processing_hint column stores default value

- **WHEN** a document is ingested with default `processing_hint` (auto)
- **THEN** the `DocumentVersion.processing_hint` column SHALL contain `"auto"`

#### Scenario: processing_hint column is nullable for existing records

- **WHEN** the Alembic migration runs on a database with existing `DocumentVersion` records
- **THEN** existing records SHALL have `processing_hint` set to `NULL`
- **AND** the migration SHALL NOT fail

#### Scenario: Alembic migration adds column and enum value together

- **WHEN** the Alembic migration for S4-06 runs
- **THEN** it SHALL add `path_c` to `processing_path_enum`
- **AND** it SHALL add the `processing_hint` column to `document_versions`
- **AND** both changes SHALL be in the same migration file
