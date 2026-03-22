## MODIFIED Requirements

### Requirement: Configurable file size limit

The maximum upload file size SHALL be configurable via the `UPLOAD_MAX_FILE_SIZE_MB` setting in the application configuration, defaulting to 50 MB. The endpoint SHALL enforce the size limit while reading the upload and SHALL reject the request before uploading any oversized payload to SeaweedFS.

#### Scenario: Default file size limit

- **WHEN** `UPLOAD_MAX_FILE_SIZE_MB` is not set in the environment
- **THEN** the default limit SHALL be 50 MB

#### Scenario: Custom file size limit

- **WHEN** `UPLOAD_MAX_FILE_SIZE_MB` is set to 10
- **THEN** files larger than 10 MB SHALL be rejected with status 413

---

### Requirement: SeaweedFS file storage

Uploaded files SHALL be stored in SeaweedFS via the Filer HTTP API with an object key following the pattern `{agent_id}/{source_id}/{sanitized_filename}`. The `source_id` SHALL be a pre-generated UUID that is shared between the SeaweedFS key and the PostgreSQL Source record. Filename sanitization SHALL strip path separators, limit the filename component to 255 characters, and replace characters outside the safe set `[A-Za-z0-9._-]` with underscores.

#### Scenario: File stored in SeaweedFS with correct key structure

- **WHEN** a file is successfully uploaded
- **THEN** the SeaweedFS object key SHALL follow the pattern `{agent_id}/{source_id}/{sanitized_filename}`
- **AND** the `source_id` in the key SHALL match the `source_id` in the PostgreSQL Source record

#### Scenario: Filename with path traversal is sanitized

- **WHEN** a file is uploaded with a name containing path separators (e.g., `../../etc/passwd.md`)
- **THEN** path separators SHALL be stripped from the filename before constructing the SeaweedFS key

#### Scenario: Unsafe characters are replaced with underscores

- **WHEN** a file is uploaded with characters outside `[A-Za-z0-9._-]`
- **THEN** those characters SHALL be replaced with underscores in `sanitized_filename`

#### Scenario: Long filename is truncated

- **WHEN** a file is uploaded with a filename longer than 255 characters
- **THEN** the sanitized filename in the SeaweedFS key SHALL be truncated to 255 characters or fewer

---

### Requirement: Source and BackgroundTask creation with commit-before-enqueue

The upload endpoint SHALL follow the commit-before-enqueue pattern: (1) upload file to SeaweedFS, (2) create Source (status PENDING) and BackgroundTask (status PENDING) in PostgreSQL and COMMIT, (3) enqueue the arq job. On enqueue success, the `arq_job_id` SHALL be saved on the BackgroundTask and committed. On enqueue failure, a compensating update SHALL mark both Source and BackgroundTask as FAILED with an error message, and the endpoint SHALL return 500.

#### Scenario: Source and Task records exist in PG after successful upload

- **WHEN** a file is successfully uploaded and the response is 202
- **THEN** a Source record SHALL exist in PostgreSQL with status PENDING and the correct `source_type`, `title`, `file_path`, and `agent_id`
- **AND** a BackgroundTask record SHALL exist with status PENDING, `task_type` INGESTION, and `source_id` referencing the Source

#### Scenario: arq job is enqueued after PG commit

- **WHEN** Source and BackgroundTask are committed to PostgreSQL
- **THEN** an arq job SHALL be enqueued with the `task_id`
- **AND** the BackgroundTask record SHALL be updated with the `arq_job_id`

#### Scenario: Compensating update on enqueue failure

- **WHEN** the arq enqueue call fails after Source and BackgroundTask have been committed
- **THEN** the Source status SHALL be updated to FAILED
- **AND** the BackgroundTask status SHALL be updated to FAILED with an `error_message` describing the enqueue failure
- **AND** the endpoint SHALL return 500

#### Scenario: SeaweedFS failure prevents PG records

- **WHEN** the SeaweedFS upload fails
- **THEN** no Source or BackgroundTask records SHALL be created in PostgreSQL
- **AND** the endpoint SHALL return 500

#### Scenario: PG failure after SeaweedFS upload triggers SeaweedFS cleanup

- **WHEN** the PostgreSQL create/commit fails after a successful SeaweedFS upload
- **THEN** the file SHALL be deleted from SeaweedFS
- **AND** the endpoint SHALL return 500

---

### Requirement: Pre-generated source_id shared identity

The upload endpoint SHALL pre-generate a `source_id` (UUID v7) before any storage operations. This `source_id` SHALL be used as the SeaweedFS key component AND as the explicit `id` of the Source record in PostgreSQL, ensuring both systems reference the same identifier.

#### Scenario: source_id is consistent across SeaweedFS and PG

- **WHEN** a file is uploaded successfully
- **THEN** the `source_id` in the 202 response SHALL match the `id` of the Source record in PostgreSQL
- **AND** the SeaweedFS object key SHALL contain the same `source_id`

---

### Requirement: StorageService abstraction

Storage operations SHALL be encapsulated in a `StorageService` class that receives an `httpx.AsyncClient` (with `base_url` set to the SeaweedFS Filer URL) and a `base_path` via constructor injection. The class SHALL provide methods for: `generate_object_key` (static), `ensure_storage_root`, `upload`, `download`, and `delete`. All methods SHALL be natively async using `httpx` — no `asyncio.to_thread()` wrappers are needed.

The constructor SHALL normalize `base_path` to have a leading slash and no trailing slash (e.g., `/sources`). URL construction SHALL use a private `_build_url(object_key: str) -> str` helper that joins `base_path` and `object_key` with a single `/` separator, preventing double-slash or missing-slash issues.

Error handling SHALL use `resp.raise_for_status()` which raises `httpx.HTTPStatusError` on non-2xx responses.

#### Scenario: StorageService methods are natively async

- **WHEN** `upload`, `download`, `delete`, or `ensure_storage_root` is called
- **THEN** the underlying HTTP call SHALL be a native async `httpx` request without `asyncio.to_thread()` wrappers

#### Scenario: generate_object_key produces correct format

- **WHEN** `generate_object_key(agent_id, source_id, filename)` is called
- **THEN** the result SHALL be `{agent_id}/{source_id}/{sanitized_filename}`

#### Scenario: ensure_storage_root validates Filer availability

- **WHEN** `ensure_storage_root()` is called
- **THEN** a POST request SHALL be sent to the `base_path` directory on the SeaweedFS Filer
- **AND** the Filer SHALL create the directory if it does not exist

#### Scenario: Upload sends multipart POST to Filer

- **WHEN** `upload(object_key, content, content_type)` is called
- **THEN** a multipart POST request SHALL be sent to `{base_path}/{object_key}` on the SeaweedFS Filer

#### Scenario: Download retrieves bytes via GET

- **WHEN** `download(object_key)` is called with a valid object key
- **THEN** a GET request SHALL be sent to `{base_path}/{object_key}` on the SeaweedFS Filer
- **AND** the method SHALL return the response body as bytes

#### Scenario: Delete sends DELETE to Filer

- **WHEN** `delete(object_key)` is called
- **THEN** a DELETE request SHALL be sent to `{base_path}/{object_key}` on the SeaweedFS Filer

#### Scenario: Path normalization handles edge cases

- **WHEN** `StorageService` is constructed with `base_path` values like `"/sources/"`, `"sources"`, or `"/sources"`
- **THEN** the normalized `base_path` SHALL always be `"/sources"` (leading slash, no trailing slash)

#### Scenario: URL construction prevents double slashes

- **WHEN** `_build_url` is called with `object_key` starting with `/`
- **THEN** the resulting URL SHALL NOT contain double slashes between `base_path` and `object_key`

---

### Requirement: SeaweedFS storage root auto-creation at startup

The SeaweedFS sources storage root SHALL be automatically created during the FastAPI application lifespan startup if it does not already exist. The root path SHALL be configurable via the `SEAWEEDFS_SOURCES_PATH` setting, defaulting to `"/sources"`.

#### Scenario: Storage root created on first startup

- **WHEN** the application starts and the sources directory does not exist in SeaweedFS Filer
- **THEN** the directory SHALL be created automatically via a POST to the Filer

#### Scenario: Storage root creation is idempotent

- **WHEN** the application starts and the sources directory already exists
- **THEN** the startup SHALL succeed without error

---

### Requirement: Upload response contract

The `POST /api/admin/sources` endpoint SHALL return a JSON response with the following fields: `source_id` (UUID), `task_id` (UUID), `status` (string, value "pending"), `file_path` (string, the SeaweedFS object key), and `message` (string, human-readable confirmation).

#### Scenario: Response contains all required fields

- **WHEN** a successful upload returns 202
- **THEN** the JSON body SHALL contain all five fields: `source_id`, `task_id`, `status`, `file_path`, `message`
- **AND** `status` SHALL be "pending"

---

### Requirement: CI test coverage for upload

Upload validation, endpoint flow, and error handling SHALL be covered by deterministic CI tests. SeaweedFS SHALL be mocked via dependency injection (using `httpx.MockTransport`). arq enqueue SHALL be mocked. PostgreSQL SHALL use a real database via testcontainer. Tests SHALL NOT depend on real SeaweedFS or Redis instances.

#### Scenario: Unit tests cover validation logic

- **WHEN** unit tests are executed
- **THEN** tests SHALL verify: allowed file extensions, rejected extensions, case-insensitive extension matching, empty file rejection, metadata validation (missing title, invalid JSON, title length), object key generation format, filename sanitization, and source_type determination

#### Scenario: Integration tests cover endpoint flow

- **WHEN** integration tests are executed with a real PostgreSQL testcontainer
- **THEN** tests SHALL verify: successful .md upload returns 202 with correct response fields, successful .txt upload, rejected .pdf upload returns 422, empty file returns 422, invalid metadata returns 422, Source and BackgroundTask records created in PG with correct fields, SeaweedFS upload called with correct key (mocked via httpx.MockTransport), arq enqueue called with task_id (mocked)

#### Scenario: Integration tests cover enqueue failure

- **WHEN** the arq enqueue mock is configured to raise an exception
- **THEN** the endpoint SHALL return 500
- **AND** Source and BackgroundTask records in PG SHALL have status FAILED with error_message populated

---

## RENAMED Requirements

### Requirement: MinIO file storage

- **FROM:** MinIO file storage
- **TO:** SeaweedFS file storage

### Requirement: MinIO bucket auto-creation at startup

- **FROM:** MinIO bucket auto-creation at startup
- **TO:** SeaweedFS storage root auto-creation at startup
