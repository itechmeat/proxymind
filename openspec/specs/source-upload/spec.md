## ADDED Requirements

### Requirement: POST /api/admin/sources endpoint

The API SHALL expose a `POST /api/admin/sources` endpoint that accepts a multipart/form-data request with two fields: `file` (UploadFile) and `metadata` (string containing JSON). The endpoint SHALL return `202 Accepted` on success. The endpoint SHALL NOT require authentication (explicit security exception — local-only deployment; `TODO(S7-01)` MUST be present in the codebase).

#### Scenario: Successful upload of a Markdown file

- **WHEN** a POST request is sent with a valid `.md` file and valid metadata JSON containing at least a `title`
- **THEN** the response status SHALL be 202
- **AND** the response body SHALL contain `source_id` (UUID), `task_id` (UUID), `status` ("pending"), `file_path` (string), and `message` (string)

#### Scenario: Successful upload of a TXT file

- **WHEN** a POST request is sent with a valid `.txt` file and valid metadata JSON containing at least a `title`
- **THEN** the response status SHALL be 202
- **AND** the response body SHALL contain `source_id`, `task_id`, `status`, `file_path`, and `message`

#### Scenario: Unsupported file format is rejected

- **WHEN** a POST request is sent with a file having an extension other than `.md` or `.txt` (e.g., `.pdf`, `.docx`, `.html`)
- **THEN** the response status SHALL be 422
- **AND** the response body SHALL indicate the file format is unsupported and list the allowed extensions

#### Scenario: Empty file is rejected

- **WHEN** a POST request is sent with a zero-byte file
- **THEN** the response status SHALL be 422

#### Scenario: Oversized file is rejected

- **WHEN** a POST request is sent with a file exceeding the configured `UPLOAD_MAX_FILE_SIZE_MB` limit
- **THEN** the response status SHALL be 413

#### Scenario: File extension validation is case-insensitive

- **WHEN** a POST request is sent with a file named `DOCUMENT.MD` or `notes.Txt`
- **THEN** the endpoint SHALL accept the file as a valid format

---

### Requirement: Upload metadata validation

The `metadata` field SHALL be validated as JSON conforming to a Pydantic schema with the following fields: `title` (string, required, 1-255 characters), `description` (string, optional, max 2000 characters), `public_url` (string, optional, valid HTTP/HTTPS URL, max 2048 characters), `catalog_item_id` (UUID, optional), `language` (string, optional, max 32 characters). The `source_type` SHALL be determined automatically from the file extension (`.md` -> MARKDOWN, `.txt` -> TXT) and SHALL NOT be part of the metadata input.

The `language` field from `SourceUploadMetadata` SHALL be persisted on the `Source` record. The `source.py` service `create_source_and_task()` method MUST pass `language=metadata.language` to the Source constructor. Empty or whitespace-only `language` values SHALL be normalized to NULL before persistence. A nullable `language` column (VARCHAR(32)) exists on the `sources` table (added in S2-02 migration 004). Existing sources have NULL, which means "use system default."

#### Scenario: Missing title in metadata

- **WHEN** a POST request is sent with metadata JSON that lacks the `title` field
- **THEN** the response status SHALL be 422

#### Scenario: Title exceeds maximum length

- **WHEN** a POST request is sent with a `title` longer than 255 characters
- **THEN** the response status SHALL be 422

#### Scenario: Invalid metadata JSON

- **WHEN** a POST request is sent with a `metadata` field that is not valid JSON
- **THEN** the response status SHALL be 422

#### Scenario: Invalid public_url format

- **WHEN** a POST request is sent with `public_url` set to a non-HTTP/HTTPS string
- **THEN** the response status SHALL be 422

#### Scenario: source_type derived from extension

- **WHEN** a `.md` file is uploaded
- **THEN** the created Source record SHALL have `source_type` set to MARKDOWN

- **WHEN** a `.txt` file is uploaded
- **THEN** the created Source record SHALL have `source_type` set to TXT

#### Scenario: Language field is persisted on Source record

- **WHEN** a POST request is sent with metadata containing `"language": "russian"`
- **THEN** the created Source record in PostgreSQL SHALL have `language` set to `"russian"`

#### Scenario: Missing language field results in NULL

- **WHEN** a POST request is sent with metadata that does not include `language`
- **THEN** the created Source record in PostgreSQL SHALL have `language` set to NULL

#### Scenario: Blank language is normalized to NULL

- **WHEN** a POST request is sent with metadata containing `"language": "   "`
- **THEN** the created Source record in PostgreSQL SHALL have `language` set to NULL

---

### Requirement: Configurable file size limit

The maximum upload file size SHALL be configurable via the `UPLOAD_MAX_FILE_SIZE_MB` setting in the application configuration, defaulting to 50 MB. The endpoint SHALL enforce the size limit while reading the upload and SHALL reject the request before uploading any oversized payload to MinIO.

#### Scenario: Default file size limit

- **WHEN** `UPLOAD_MAX_FILE_SIZE_MB` is not set in the environment
- **THEN** the default limit SHALL be 50 MB

#### Scenario: Custom file size limit

- **WHEN** `UPLOAD_MAX_FILE_SIZE_MB` is set to 10
- **THEN** files larger than 10 MB SHALL be rejected with status 413

---

### Requirement: MinIO file storage

Uploaded files SHALL be stored in MinIO with an object key following the pattern `{agent_id}/{source_id}/{sanitized_filename}`. The `source_id` SHALL be a pre-generated UUID that is shared between the MinIO key and the PostgreSQL Source record. Filename sanitization SHALL strip path separators, limit the filename component to 255 characters, and replace characters outside the safe set `[A-Za-z0-9._-]` with underscores.

#### Scenario: File stored in MinIO with correct key structure

- **WHEN** a file is successfully uploaded
- **THEN** the MinIO object key SHALL follow the pattern `{agent_id}/{source_id}/{sanitized_filename}`
- **AND** the `source_id` in the key SHALL match the `source_id` in the PostgreSQL Source record

#### Scenario: Filename with path traversal is sanitized

- **WHEN** a file is uploaded with a name containing path separators (e.g., `../../etc/passwd.md`)
- **THEN** path separators SHALL be stripped from the filename before constructing the MinIO key

#### Scenario: Unsafe characters are replaced with underscores

- **WHEN** a file is uploaded with characters outside `[A-Za-z0-9._-]`
- **THEN** those characters SHALL be replaced with underscores in `sanitized_filename`

#### Scenario: Long filename is truncated

- **WHEN** a file is uploaded with a filename longer than 255 characters
- **THEN** the sanitized filename in the MinIO key SHALL be truncated to 255 characters or fewer

---

### Requirement: Source and BackgroundTask creation with commit-before-enqueue

The upload endpoint SHALL follow the commit-before-enqueue pattern: (1) upload file to MinIO, (2) create Source (status PENDING) and BackgroundTask (status PENDING) in PostgreSQL and COMMIT, (3) enqueue the arq job. On enqueue success, the `arq_job_id` SHALL be saved on the BackgroundTask and committed. On enqueue failure, a compensating update SHALL mark both Source and BackgroundTask as FAILED with an error message, and the endpoint SHALL return 500.

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

#### Scenario: MinIO failure prevents PG records

- **WHEN** the MinIO upload fails
- **THEN** no Source or BackgroundTask records SHALL be created in PostgreSQL
- **AND** the endpoint SHALL return 500

#### Scenario: PG failure after MinIO upload triggers MinIO cleanup

- **WHEN** the PostgreSQL create/commit fails after a successful MinIO upload
- **THEN** the file SHALL be deleted from MinIO
- **AND** the endpoint SHALL return 500

---

### Requirement: Pre-generated source_id shared identity

The upload endpoint SHALL pre-generate a `source_id` (UUID v7) before any storage operations. This `source_id` SHALL be used as the MinIO key component AND as the explicit `id` of the Source record in PostgreSQL, ensuring both systems reference the same identifier.

#### Scenario: source_id is consistent across MinIO and PG

- **WHEN** a file is uploaded successfully
- **THEN** the `source_id` in the 202 response SHALL match the `id` of the Source record in PostgreSQL
- **AND** the MinIO object key SHALL contain the same `source_id`

---

### Requirement: StorageService abstraction

MinIO operations SHALL be encapsulated in a `StorageService` class that receives the MinIO client and bucket name via constructor injection. The class SHALL provide methods for: `generate_object_key` (static), `ensure_bucket`, `upload`, and `delete`. All synchronous MinIO SDK calls SHALL be wrapped in `asyncio.to_thread()` for non-blocking operation.

#### Scenario: StorageService methods are non-blocking

- **WHEN** `upload`, `delete`, or `ensure_bucket` is called
- **THEN** the underlying synchronous MinIO SDK call SHALL be executed via `asyncio.to_thread()`

#### Scenario: generate_object_key produces correct format

- **WHEN** `generate_object_key(agent_id, source_id, filename)` is called
- **THEN** the result SHALL be `{agent_id}/{source_id}/{sanitized_filename}`

---

### Requirement: MinIO bucket auto-creation at startup

The MinIO `sources` bucket SHALL be automatically created during the FastAPI application lifespan startup if it does not already exist. The bucket name SHALL be configurable via the `MINIO_BUCKET_SOURCES` setting, defaulting to `"sources"`.

#### Scenario: Bucket created on first startup

- **WHEN** the application starts and the `sources` bucket does not exist in MinIO
- **THEN** the bucket SHALL be created automatically

#### Scenario: Bucket creation is idempotent

- **WHEN** the application starts and the `sources` bucket already exists
- **THEN** the startup SHALL succeed without error

---

### Requirement: arq pool lifecycle in FastAPI lifespan

The FastAPI lifespan SHALL create an arq Redis pool (`ArqRedis`) during startup and store it in `app.state.arq_pool`. During shutdown, the pool SHALL be closed via `await app.state.arq_pool.close()`.

#### Scenario: arq pool available after startup

- **WHEN** the application has completed startup
- **THEN** `app.state.arq_pool` SHALL be an active `ArqRedis` instance

#### Scenario: arq pool closed on shutdown

- **WHEN** the application shuts down
- **THEN** `app.state.arq_pool.close()` SHALL be awaited

---

### Requirement: Admin API no-auth security exception

The `POST /api/admin/sources` and `GET /api/admin/tasks/{task_id}` endpoints SHALL NOT require authentication in S2-01. This is an explicit security exception documented as a deviation from secure-by-default principles. The codebase MUST contain a `TODO(S7-01)` comment referencing the future addition of Bearer token authentication on `/api/admin/*`. This exception is valid only for local Docker development; Caddy MUST NOT expose `/api/admin/*` externally without explicit configuration.

#### Scenario: Admin endpoints accessible without auth

- **WHEN** a request is sent to `POST /api/admin/sources` or `GET /api/admin/tasks/{id}` without any authorization header
- **THEN** the request SHALL be processed normally (not rejected for missing auth)

#### Scenario: TODO marker exists in codebase

- **WHEN** the admin router source code is inspected
- **THEN** a `TODO(S7-01)` comment referencing authentication SHALL be present

---

### Requirement: Constants module for canonical seeded IDs

The application SHALL provide a constants module (`app/core/constants.py`) that defines `DEFAULT_AGENT_ID` and `DEFAULT_KNOWLEDGE_BASE_ID` as the same UUIDs present in the seed migration. Runtime code SHALL import these constants from the constants module, NOT from migration files.

#### Scenario: Constants match seed migration values

- **WHEN** `DEFAULT_AGENT_ID` from `app.core.constants` is compared with the agent ID in seed migration 002
- **THEN** they SHALL be identical UUIDs

#### Scenario: Upload uses constants for agent_id

- **WHEN** a file is uploaded via `POST /api/admin/sources`
- **THEN** the Source record SHALL use `DEFAULT_AGENT_ID` as its `agent_id`

---

### Requirement: Upload response contract

The `POST /api/admin/sources` endpoint SHALL return a JSON response with the following fields: `source_id` (UUID), `task_id` (UUID), `status` (string, value "pending"), `file_path` (string, the MinIO object key), and `message` (string, human-readable confirmation).

#### Scenario: Response contains all required fields

- **WHEN** a successful upload returns 202
- **THEN** the JSON body SHALL contain all five fields: `source_id`, `task_id`, `status`, `file_path`, `message`
- **AND** `status` SHALL be "pending"

---

### Requirement: CI test coverage for upload

Upload validation, endpoint flow, and error handling SHALL be covered by deterministic CI tests. MinIO SHALL be mocked via dependency injection. arq enqueue SHALL be mocked. PostgreSQL SHALL use a real database via testcontainer. Tests SHALL NOT depend on real MinIO or Redis instances.

#### Scenario: Unit tests cover validation logic

- **WHEN** unit tests are executed
- **THEN** tests SHALL verify: allowed file extensions, rejected extensions, case-insensitive extension matching, empty file rejection, metadata validation (missing title, invalid JSON, title length), MinIO key generation format, filename sanitization, and source_type determination

#### Scenario: Integration tests cover endpoint flow

- **WHEN** integration tests are executed with a real PostgreSQL testcontainer
- **THEN** tests SHALL verify: successful .md upload returns 202 with correct response fields, successful .txt upload, rejected .pdf upload returns 422, empty file returns 422, invalid metadata returns 422, Source and BackgroundTask records created in PG with correct fields, MinIO upload called with correct key (mocked), arq enqueue called with task_id (mocked)

#### Scenario: Integration tests cover enqueue failure

- **WHEN** the arq enqueue mock is configured to raise an exception
- **THEN** the endpoint SHALL return 500
- **AND** Source and BackgroundTask records in PG SHALL have status FAILED with error_message populated
