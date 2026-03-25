## ADDED Requirements

### Requirement: POST /api/admin/sources endpoint

**[Modified by S3-04]** The API SHALL expose a `POST /api/admin/sources` endpoint that accepts a multipart/form-data request with two fields: `file` (UploadFile) and `metadata` (string containing JSON). The endpoint SHALL return `202 Accepted` on success. The endpoint SHALL NOT require authentication (explicit security exception -- local-only deployment; `TODO(S7-01)` MUST be present in the codebase).

> **MODIFIED by S3-01:** The unsupported file format scenario is updated to reflect the expanded set of allowed extensions.
>
> **MODIFIED by S3-04:** Upload scenarios extended to cover IMAGE, AUDIO, and VIDEO source types.

#### Scenario: Successful upload of a Markdown file

- **WHEN** a POST request is sent with a valid `.md` file and valid metadata JSON containing at least a `title`
- **THEN** the response status SHALL be 202
- **AND** the response body SHALL contain `source_id` (UUID), `task_id` (UUID), `status` ("pending"), `file_path` (string), and `message` (string)
- **AND** the created Source record SHALL have `source_type` set to MARKDOWN

#### Scenario: Successful upload of a TXT file

- **WHEN** a POST request is sent with a valid `.txt` file and valid metadata JSON containing at least a `title`
- **THEN** the response status SHALL be 202
- **AND** the response body SHALL contain `source_id`, `task_id`, `status`, `file_path`, and `message`
- **AND** the created Source record SHALL have `source_type` set to TXT

#### Scenario: Successful upload of a PDF file

- **WHEN** a POST request is sent with a valid `.pdf` file and valid metadata JSON containing at least a `title`
- **THEN** the response status SHALL be 202
- **AND** the response body SHALL contain `source_id`, `task_id`, `status`, `file_path`, and `message`
- **AND** the created Source record SHALL have `source_type` set to PDF

#### Scenario: Successful upload of a DOCX file

- **WHEN** a POST request is sent with a valid `.docx` file and valid metadata JSON containing at least a `title`
- **THEN** the response status SHALL be 202
- **AND** the response body SHALL contain `source_id`, `task_id`, `status`, `file_path`, and `message`
- **AND** the created Source record SHALL have `source_type` set to DOCX

#### Scenario: Successful upload of an HTML file

- **WHEN** a POST request is sent with a valid `.html` file and valid metadata JSON containing at least a `title`
- **THEN** the response status SHALL be 202
- **AND** the response body SHALL contain `source_id`, `task_id`, `status`, `file_path`, and `message`
- **AND** the created Source record SHALL have `source_type` set to HTML

#### Scenario: Successful upload of an HTM file

- **WHEN** a POST request is sent with a valid `.htm` file and valid metadata JSON containing at least a `title`
- **THEN** the response status SHALL be 202
- **AND** the response body SHALL contain `source_id`, `task_id`, `status`, `file_path`, and `message`
- **AND** the created Source record SHALL have `source_type` set to HTML

#### Scenario: Successful upload of a PNG image

- **WHEN** a POST request is sent with a valid `.png` file and valid metadata JSON containing at least a `title`
- **THEN** the response status SHALL be 202
- **AND** the response body SHALL contain `source_id`, `task_id`, `status`, `file_path`, and `message`
- **AND** the created Source record SHALL have `source_type` set to IMAGE

#### Scenario: Successful upload of a JPEG image

- **WHEN** a POST request is sent with a valid `.jpeg` or `.jpg` file and valid metadata JSON containing at least a `title`
- **THEN** the response status SHALL be 202
- **AND** the response body SHALL contain `source_id`, `task_id`, `status`, `file_path`, and `message`
- **AND** the created Source record SHALL have `source_type` set to IMAGE

#### Scenario: Successful upload of an MP3 audio file

- **WHEN** a POST request is sent with a valid `.mp3` file and valid metadata JSON containing at least a `title`
- **THEN** the response status SHALL be 202
- **AND** the response body SHALL contain `source_id`, `task_id`, `status`, `file_path`, and `message`
- **AND** the created Source record SHALL have `source_type` set to AUDIO

#### Scenario: Successful upload of a WAV audio file

- **WHEN** a POST request is sent with a valid `.wav` file and valid metadata JSON containing at least a `title`
- **THEN** the response status SHALL be 202
- **AND** the response body SHALL contain `source_id`, `task_id`, `status`, `file_path`, and `message`
- **AND** the created Source record SHALL have `source_type` set to AUDIO

#### Scenario: Successful upload of an MP4 video file

- **WHEN** a POST request is sent with a valid `.mp4` file and valid metadata JSON containing at least a `title`
- **THEN** the response status SHALL be 202
- **AND** the response body SHALL contain `source_id`, `task_id`, `status`, `file_path`, and `message`
- **AND** the created Source record SHALL have `source_type` set to VIDEO

#### Scenario: Invalid metadata JSON is rejected

- **WHEN** a POST request is sent with a supported file and a `metadata` field that is not valid JSON
- **THEN** the response status SHALL be 422
- **AND** the response body SHALL contain validation error details
- **AND** no Source record SHALL be created

#### Scenario: Empty metadata object is rejected

- **WHEN** a POST request is sent with a supported file and `metadata={}`
- **THEN** the response status SHALL be 422
- **AND** the response body SHALL contain validation error details indicating that required fields are missing
- **AND** no Source record SHALL be created

#### Scenario: Missing title in metadata is rejected

- **WHEN** a POST request is sent with a supported file and metadata JSON that omits `title`
- **THEN** the response status SHALL be 422
- **AND** the response body SHALL contain validation error details for `title`
- **AND** no Source record SHALL be created

#### Scenario: Overlong metadata field is rejected

- **WHEN** a POST request is sent with a supported file and metadata JSON containing a field value longer than the schema allows
- **THEN** the response status SHALL be 422
- **AND** the response body SHALL contain validation error details
- **AND** no Source record SHALL be created

#### Scenario: Unsupported file format is rejected

- **WHEN** a POST request is sent with a file having an extension other than `.md`, `.txt`, `.pdf`, `.docx`, `.html`, `.htm`, `.png`, `.jpeg`, `.jpg`, `.mp3`, `.wav`, or `.mp4` (e.g., `.xlsx`, `.pptx`, `.xml`, `.avi`)
- **THEN** the response status SHALL be 422
- **AND** the response body SHALL indicate the file format is unsupported and list the allowed extensions

#### Scenario: Empty file is rejected

- **WHEN** a POST request is sent with a zero-byte file
- **THEN** the response status SHALL be 422

#### Scenario: Oversized file is rejected

- **WHEN** a POST request is sent with a file exceeding the configured `UPLOAD_MAX_FILE_SIZE_MB` limit
- **THEN** the response status SHALL be 413

#### Scenario: File extension validation is case-insensitive

- **WHEN** a POST request is sent with a file named `DOCUMENT.PDF`, `report.Docx`, `page.HTML`, `photo.PNG`, or `clip.MP4`
- **THEN** the endpoint SHALL accept the file as a valid format

---

### Requirement: Upload metadata validation

The `metadata` field SHALL be validated as JSON conforming to a Pydantic schema with the following fields: `title` (string, required, 1-255 characters), `description` (string, optional, max 2000 characters), `public_url` (string, optional, valid HTTP/HTTPS URL, max 2048 characters), `catalog_item_id` (UUID, optional), `language` (string, optional, max 32 characters). The `source_type` SHALL be determined automatically from the file extension and SHALL NOT be part of the metadata input.

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

### Requirement: File extension validation and source type mapping

**[Modified by S3-04]** The upload validation SHALL accept the following file extensions: `.md`, `.txt`, `.pdf`, `.docx`, `.html`, `.htm`, `.png`, `.jpeg`, `.jpg`, `.mp3`, `.wav`, `.mp4`. Extension validation SHALL be case-insensitive. The canonical supported extension set in code SHALL be represented by `ALLOWED_SOURCE_EXTENSIONS` with lowercase entries only. Implementations SHALL normalize the extracted file extension to lowercase before validating membership in `ALLOWED_SOURCE_EXTENSIONS`. The `source_type` SHALL be determined automatically from the file extension using the following mapping:

| Extension | SourceType |
| --------- | ---------- |
| `.md`     | MARKDOWN   |
| `.txt`    | TXT        |
| `.pdf`    | PDF        |
| `.docx`   | DOCX       |
| `.html`   | HTML       |
| `.htm`    | HTML       |
| `.png`    | IMAGE      |
| `.jpeg`   | IMAGE      |
| `.jpg`    | IMAGE      |
| `.mp3`    | AUDIO      |
| `.wav`    | AUDIO      |
| `.mp4`    | VIDEO      |

> **ADDED by S3-01:** Extended from `.md`/`.txt` to include `.pdf`, `.docx`, `.html`, `.htm`. Both `.html` and `.htm` map to `SourceType.HTML`.
>
> **MODIFIED by S3-04:** Extended to include `.png`, `.jpeg`, `.jpg` (IMAGE), `.mp3`, `.wav` (AUDIO), `.mp4` (VIDEO).

#### Scenario: PDF extension maps to PDF source type

- **WHEN** a file with extension `.pdf` is uploaded
- **THEN** the created Source record SHALL have `source_type` set to PDF

#### Scenario: DOCX extension maps to DOCX source type

- **WHEN** a file with extension `.docx` is uploaded
- **THEN** the created Source record SHALL have `source_type` set to DOCX

#### Scenario: HTML extension maps to HTML source type

- **WHEN** a file with extension `.html` is uploaded
- **THEN** the created Source record SHALL have `source_type` set to HTML

#### Scenario: HTM extension maps to HTML source type

- **WHEN** a file with extension `.htm` is uploaded
- **THEN** the created Source record SHALL have `source_type` set to HTML

#### Scenario: PNG extension maps to IMAGE source type

- **WHEN** a file with extension `.png` is uploaded
- **THEN** the created Source record SHALL have `source_type` set to IMAGE

#### Scenario: JPEG extension maps to IMAGE source type

- **WHEN** a file with extension `.jpeg` is uploaded
- **THEN** the created Source record SHALL have `source_type` set to IMAGE

#### Scenario: JPG extension maps to IMAGE source type

- **WHEN** a file with extension `.jpg` is uploaded
- **THEN** the created Source record SHALL have `source_type` set to IMAGE

#### Scenario: MP3 extension maps to AUDIO source type

- **WHEN** a file with extension `.mp3` is uploaded
- **THEN** the created Source record SHALL have `source_type` set to AUDIO

#### Scenario: WAV extension maps to AUDIO source type

- **WHEN** a file with extension `.wav` is uploaded
- **THEN** the created Source record SHALL have `source_type` set to AUDIO

#### Scenario: MP4 extension maps to VIDEO source type

- **WHEN** a file with extension `.mp4` is uploaded
- **THEN** the created Source record SHALL have `source_type` set to VIDEO

#### Scenario: Case-insensitive new extensions

- **WHEN** a file named `REPORT.PDF`, `Document.Docx`, `photo.PNG`, or `clip.MP4` is uploaded
- **THEN** the endpoint SHALL accept the file and determine the correct `source_type`

#### Scenario: Unsupported extensions are still rejected

- **WHEN** a file with extension `.xlsx`, `.pptx`, `.xml`, or `.avi` is uploaded
- **THEN** the response status SHALL be 422
- **AND** the response body SHALL list all allowed extensions

---

### Requirement: Configurable file size limit

The maximum upload file size SHALL be configurable via the `UPLOAD_MAX_FILE_SIZE_MB` setting in the application configuration, defaulting to 100 MB. The endpoint SHALL enforce the size limit while reading the upload and SHALL reject the request before uploading any oversized payload to SeaweedFS.

> **MODIFIED by S3-01:** Default raised from 50 MB to 100 MB to accommodate PDF books with embedded images. Single limit for all formats.

#### Scenario: Default file size limit

- **WHEN** `UPLOAD_MAX_FILE_SIZE_MB` is not set in the environment
- **THEN** the default limit SHALL be 100 MB

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

\*\*\* Add File: /Users/techmeat/www/projects/agentic-depot/proxymind/openspec/specs/admin-knowledge-ui/spec.md

## Purpose

Frontend admin interface for knowledge management — source upload, source list with status tracking, snapshot lifecycle management, draft testing. Includes admin routing, layout, and access control via environment flag. Introduced by S5-03.

## ADDED Requirements

### Requirement: Admin routing with VITE_ADMIN_MODE guard

The application SHALL expose `/admin`, `/admin/sources`, and `/admin/snapshots` routes. Navigating to `/admin` SHALL redirect to `/admin/sources`. All `/admin/*` routes SHALL be guarded by the `VITE_ADMIN_MODE` environment flag. When `import.meta.env.VITE_ADMIN_MODE` is not `"true"` or is unset, navigating to any `/admin/*` route SHALL redirect the user to `/`. The guard is UI-only and does not protect backend endpoints.

#### Scenario: Admin root redirects to sources tab

- **WHEN** a user navigates to `/admin` and `VITE_ADMIN_MODE` is `"true"`
- **THEN** the browser SHALL redirect to `/admin/sources`

#### Scenario: Admin routes accessible in admin mode

- **WHEN** `import.meta.env.VITE_ADMIN_MODE` equals `"true"`
- **AND** the user navigates to `/admin/sources` or `/admin/snapshots`
- **THEN** the corresponding tab content SHALL render

#### Scenario: Admin routes blocked when not admin mode

- **WHEN** `import.meta.env.VITE_ADMIN_MODE` is not `"true"` or is unset
- **AND** the user navigates to `/admin`, `/admin/sources`, or `/admin/snapshots`
- **THEN** the user SHALL be redirected to `/`

---

### Requirement: Admin layout with header and top tabs navigation

The admin pages SHALL render inside an `AdminLayout` component that provides: (1) a header with a "Chat" back-link navigating to `/`, a "ProxyMind Admin" title, and twin identity display; (2) horizontal top tabs for "Sources" and "Snapshots" that link to `/admin/sources` and `/admin/snapshots` respectively; (3) a scrollable content area below the tabs rendering the active tab's route outlet. On mobile, tabs SHALL span full width (50/50 for two tabs).

#### Scenario: Admin header renders navigation elements

- **WHEN** the admin layout renders
- **THEN** it SHALL display a back-link to `/` (Chat), the title "ProxyMind Admin", and the twin identity

#### Scenario: Tab navigation between sources and snapshots

- **WHEN** the user clicks the "Sources" tab
- **THEN** the browser SHALL navigate to `/admin/sources` and the Sources tab content SHALL render

- **WHEN** the user clicks the "Snapshots" tab
- **THEN** the browser SHALL navigate to `/admin/snapshots` and the Snapshots tab content SHALL render

#### Scenario: Active tab visually indicated

- **WHEN** the user is on `/admin/sources`
- **THEN** the "Sources" tab SHALL have active styling (e.g., highlighted border or background)
- **AND** the "Snapshots" tab SHALL have inactive styling

#### Scenario: Mobile responsive tabs

- **WHEN** the viewport width is below the mobile breakpoint
- **THEN** the two tabs SHALL each occupy 50% of the available width

---

### Requirement: ChatHeader admin link

The ChatHeader component SHALL render an "Admin" link button that navigates to `/admin`. The link SHALL be visible only when `import.meta.env.VITE_ADMIN_MODE === "true"`. When `VITE_ADMIN_MODE` is not `"true"` or is unset, the Admin link SHALL NOT be rendered. The Admin link SHALL be separate from the existing Settings icon button.

#### Scenario: Admin link visible in admin mode

- **WHEN** `import.meta.env.VITE_ADMIN_MODE` equals `"true"`
- **THEN** the ChatHeader SHALL render an Admin link button that navigates to `/admin`

#### Scenario: Admin link hidden when not admin mode

- **WHEN** `import.meta.env.VITE_ADMIN_MODE` is not `"true"` or is unset
- **THEN** the ChatHeader SHALL NOT render the Admin link button

---

### Requirement: Sources tab with drag and drop upload zone

The Sources tab SHALL include a drag and drop upload zone at the top of the page. The drop zone SHALL display a dashed border, an icon, and instructional text. When files are dragged over the zone, it SHALL enter a highlighted visual state. The zone SHALL support multi-file upload: each dropped file SHALL trigger a separate `POST /api/admin/sources` request. On mobile, tapping the zone SHALL open the native file picker as a fallback. Upload metadata SHALL be auto-derived: `title` defaults to the filename without extension. No metadata modal SHALL be shown.

#### Scenario: Drop zone renders with instructional text

- **WHEN** the Sources tab renders
- **THEN** a drop zone with dashed border, icon, and instructional text SHALL be displayed

#### Scenario: Visual highlight on drag over

- **WHEN** files are dragged over the drop zone
- **THEN** the zone SHALL enter a highlighted visual state (e.g., changed border color/style)

- **WHEN** the drag leaves the zone without dropping
- **THEN** the zone SHALL return to its default visual state

#### Scenario: Multi-file upload triggers separate requests

- **WHEN** the user drops 3 files onto the zone
- **THEN** 3 separate `POST /api/admin/sources` requests SHALL be sent, one per file
- **AND** each request SHALL use the filename (without extension) as the `title` in metadata

#### Scenario: Mobile tap opens file picker

- **WHEN** the user taps the drop zone on a mobile device
- **THEN** the native file picker SHALL open to allow file selection

---

### Requirement: Client-side file validation

Before sending an upload request, the client SHALL validate each file. Allowed extensions SHALL be: `.md`, `.txt`, `.pdf`, `.docx`, `.html`, `.htm`, `.png`, `.jpg`, `.jpeg`, `.mp3`, `.wav`, `.mp4`. Files with unsupported extensions SHALL be rejected with an error toast before any network request. Empty (zero-byte) files SHALL be rejected with an error toast. Extension validation SHALL be case-insensitive.

#### Scenario: Unsupported file extension rejected

- **WHEN** the user drops a file with extension `.xlsx`
- **THEN** the upload SHALL NOT be sent
- **AND** an error toast SHALL display indicating the file type is unsupported

#### Scenario: Empty file rejected

- **WHEN** the user drops a zero-byte file
- **THEN** the upload SHALL NOT be sent
- **AND** an error toast SHALL display indicating the file is empty

#### Scenario: Allowed extension accepted

- **WHEN** the user drops a file with extension `.pdf`
- **THEN** the client-side validation SHALL pass and the upload request SHALL be sent

#### Scenario: Case-insensitive extension validation

- **WHEN** the user drops a file named `REPORT.PDF`
- **THEN** the client-side validation SHALL accept it as a valid PDF file

---

### Requirement: Source list with status badges and polling

The Sources tab SHALL display a list of sources below the upload zone. On desktop, the list SHALL render as a table with columns: title, type (icon), status (badge), and actions (delete button). On mobile, the list SHALL render as a card stack with each card showing title, type badge, status badge, and delete button. Sources SHALL be sorted by `created_at` descending (newest first). Status badges SHALL use the following colors: PENDING = yellow, PROCESSING = blue with animated pulse/spinner, READY = green, FAILED = red.

The list SHALL poll for updates: on mount, it SHALL fetch sources; when any source has status PENDING or PROCESSING, it SHALL start polling every 3 seconds; when all visible sources are READY or FAILED, polling SHALL stop. After a successful upload, it SHALL re-fetch immediately and start polling. After a successful delete, it SHALL re-fetch immediately. On unmount, polling intervals SHALL be cleaned up.

#### Scenario: Source list renders as table on desktop

- **WHEN** the Sources tab renders on a desktop viewport
- **THEN** sources SHALL be displayed in a table with title, type, status, and actions columns

#### Scenario: Source list renders as cards on mobile

- **WHEN** the Sources tab renders on a mobile viewport
- **THEN** sources SHALL be displayed as a card stack

#### Scenario: Status badge colors

- **WHEN** a source has status PENDING
- **THEN** its badge SHALL be yellow

- **WHEN** a source has status PROCESSING
- **THEN** its badge SHALL be blue with an animated pulse or spinner

- **WHEN** a source has status READY
- **THEN** its badge SHALL be green

- **WHEN** a source has status FAILED
- **THEN** its badge SHALL be red

#### Scenario: Polling starts when sources are processing

- **WHEN** the source list contains at least one source with status PENDING or PROCESSING
- **THEN** the list SHALL poll `GET /api/admin/sources` every 3 seconds

#### Scenario: Polling stops when all sources are terminal

- **WHEN** all visible sources have status READY or FAILED
- **THEN** the polling interval SHALL be stopped

#### Scenario: Re-fetch after upload

- **WHEN** a file upload completes successfully
- **THEN** the source list SHALL re-fetch immediately
- **AND** polling SHALL start if the new source has status PENDING or PROCESSING

#### Scenario: Cleanup on unmount

- **WHEN** the Sources tab component unmounts
- **THEN** all active polling intervals SHALL be cleaned up

---

### Requirement: Soft delete with AlertDialog confirmation

Each source in the list SHALL have a delete button. Clicking the delete button SHALL open an AlertDialog with the confirmation message: `Delete source {title}? Chunks in published snapshots will remain until replaced.` Confirming the dialog SHALL send a `DELETE /api/admin/sources/{id}` request. On success, the source SHALL be removed from the rendered list (the backend excludes DELETED sources). Backend warnings (e.g., source referenced in a published snapshot) SHALL be shown in a toast notification.

#### Scenario: Delete button opens confirmation dialog

- **WHEN** the user clicks the delete button on a source
- **THEN** an AlertDialog SHALL open with a confirmation message containing the source title

#### Scenario: Confirm delete sends request

- **WHEN** the user confirms the delete in the AlertDialog
- **THEN** a `DELETE /api/admin/sources/{id}` request SHALL be sent
- **AND** on success, the source SHALL be removed from the list

#### Scenario: Cancel delete closes dialog

- **WHEN** the user cancels the delete in the AlertDialog
- **THEN** the dialog SHALL close and no delete request SHALL be sent

#### Scenario: Backend warning shown as toast

- **WHEN** the delete response includes a warning message
- **THEN** the warning SHALL be displayed in a toast notification

---

### Requirement: Snapshots tab with card layout

The Snapshots tab SHALL display snapshots in a card layout. Each card SHALL show: snapshot name, status badge (colored), chunk count, relevant timestamps (created, published, activated as applicable), and action buttons based on status. Cards SHALL be sorted by status priority: ACTIVE first, then DRAFT, then PUBLISHED (newest first within each group). Status badge colors SHALL be: ACTIVE = green, DRAFT = yellow, PUBLISHED = blue, ARCHIVED = gray. ARCHIVED snapshots SHALL be hidden by default; a `Show archived` toggle at the bottom SHALL reveal them.

#### Scenario: Snapshot cards sorted by status priority

- **WHEN** the Snapshots tab renders with snapshots of various statuses
- **THEN** ACTIVE snapshots SHALL appear first, then DRAFT, then PUBLISHED

#### Scenario: Status badge colors on snapshot cards

- **WHEN** a snapshot has status ACTIVE
- **THEN** its badge SHALL be green

- **WHEN** a snapshot has status DRAFT
- **THEN** its badge SHALL be yellow

- **WHEN** a snapshot has status PUBLISHED
- **THEN** its badge SHALL be blue

- **WHEN** a snapshot has status ARCHIVED
- **THEN** its badge SHALL be gray

#### Scenario: Archived snapshots hidden by default

- **WHEN** the Snapshots tab renders and ARCHIVED snapshots exist
- **THEN** ARCHIVED snapshots SHALL NOT be visible

#### Scenario: Show archived toggle reveals archived snapshots

- **WHEN** the user activates the `Show archived` toggle
- **THEN** ARCHIVED snapshot cards SHALL become visible

#### Scenario: Card displays chunk count and timestamps

- **WHEN** a snapshot card renders
- **THEN** it SHALL display the snapshot name, chunk count, and relevant timestamps

---

### Requirement: Create draft button

The Snapshots tab SHALL display a `+ New Draft` button at the top of the snapshot list. Clicking the button SHALL send a `POST /api/admin/snapshots` request and add the returned snapshot to the list. The button SHALL be disabled when a DRAFT snapshot already exists in the current list. When disabled, a tooltip SHALL display: `A draft already exists`.

#### Scenario: Create draft button sends request

- **WHEN** no DRAFT snapshot exists and the user clicks `+ New Draft`
- **THEN** a `POST /api/admin/snapshots` request SHALL be sent
- **AND** the returned snapshot SHALL appear in the list

#### Scenario: Create draft button disabled when draft exists

- **WHEN** a DRAFT snapshot already exists in the list
- **THEN** the `+ New Draft` button SHALL be disabled
- **AND** hovering over it SHALL show a tooltip: `A draft already exists`

---

### Requirement: Snapshot actions by status

Snapshot cards SHALL display action buttons based on their status. DRAFT cards SHALL show: `Test`, `Publish`, and `Publish & Activate` buttons. PUBLISHED cards SHALL show an `Activate` button. ACTIVE cards SHALL show a `Rollback` button. ARCHIVED cards SHALL show no action buttons.

#### Scenario: DRAFT card actions

- **WHEN** a snapshot card has status DRAFT
- **THEN** it SHALL display `Test`, `Publish`, and `Publish & Activate` buttons

#### Scenario: PUBLISHED card actions

- **WHEN** a snapshot card has status PUBLISHED
- **THEN** it SHALL display an `Activate` button

#### Scenario: ACTIVE card actions

- **WHEN** a snapshot card has status ACTIVE
- **THEN** it SHALL display a `Rollback` button

#### Scenario: ARCHIVED card has no actions

- **WHEN** a snapshot card has status ARCHIVED
- **THEN** no action buttons SHALL be displayed

---

### Requirement: Publish and activate actions with confirmations

The `Publish` button SHALL open an AlertDialog confirmation before sending `POST /api/admin/snapshots/{id}/publish`. The `Publish & Activate` button SHALL open an AlertDialog confirmation before sending `POST /api/admin/snapshots/{id}/publish?activate=true`. The `Activate` button on a PUBLISHED card SHALL send `POST /api/admin/snapshots/{id}/activate`. Backend validation errors (no indexed chunks, failed chunks, pending chunks) SHALL be displayed as error toasts with details. On success, the snapshot list SHALL be re-fetched.

#### Scenario: Publish with confirmation

- **WHEN** the user clicks `Publish` on a DRAFT card
- **THEN** an AlertDialog SHALL open asking for confirmation
- **AND** confirming SHALL send `POST /api/admin/snapshots/{id}/publish`
- **AND** on success, the list SHALL re-fetch and a success toast SHALL display

#### Scenario: Publish and activate with confirmation

- **WHEN** the user clicks `Publish & Activate` on a DRAFT card
- **THEN** an AlertDialog SHALL open asking for confirmation
- **AND** confirming SHALL send `POST /api/admin/snapshots/{id}/publish?activate=true`
- **AND** on success, the list SHALL re-fetch and a success toast SHALL display

#### Scenario: Activate published snapshot

- **WHEN** the user clicks `Activate` on a PUBLISHED card
- **THEN** a `POST /api/admin/snapshots/{id}/activate` request SHALL be sent
- **AND** on success, the list SHALL re-fetch and a success toast SHALL display

#### Scenario: Backend validation error shown as toast

- **WHEN** a publish or activate request fails with a 422 status (e.g., no indexed chunks)
- **THEN** an error toast SHALL display with the validation error details from the backend response

---

### Requirement: Rollback action with confirmation

The `Rollback` button on an ACTIVE snapshot card SHALL open an AlertDialog with the message: `Roll back to previous published snapshot {name}?` Confirming SHALL send `POST /api/admin/snapshots/{id}/rollback`. The response contains `rolled_back_from` and `rolled_back_to` objects (each with `id`, `name`, `status`). On success, a toast SHALL display: `Rolled back to {rolled_back_to.name}` and the snapshot list SHALL re-fetch.

#### Scenario: Rollback opens confirmation dialog

- **WHEN** the user clicks `Rollback` on an ACTIVE snapshot card
- **THEN** an AlertDialog SHALL open with a rollback confirmation message

#### Scenario: Rollback success

- **WHEN** the user confirms the rollback
- **THEN** a `POST /api/admin/snapshots/{id}/rollback` request SHALL be sent
- **AND** on success, a toast SHALL display `Rolled back to {rolled_back_to.name}`
- **AND** the snapshot list SHALL re-fetch

#### Scenario: Rollback failure

- **WHEN** the rollback request fails (e.g., 409 conflict)
- **THEN** an error toast SHALL display with the backend error message
- **AND** the snapshot list SHALL re-fetch to reflect the current state

---

### Requirement: Inline draft test panel

The `Test` button on a DRAFT snapshot card SHALL expand an inline panel below the card. The panel SHALL contain: a text input for the search query, a mode selector (Hybrid, Dense, Sparse) with Hybrid as the default, and a `Search` button. On desktop, the mode selector SHALL render as radio buttons. On mobile, it SHALL render as a dropdown. Clicking `Search` SHALL send `POST /api/admin/snapshots/{id}/test` with `{ query, top_n: 5, mode }`. Results SHALL display as a list showing: source title, score, anchor metadata (`page`, `chapter`, `section`, `timecode`), and a text preview (first 500 characters).

#### Scenario: Test button expands inline panel

- **WHEN** the user clicks `Test` on a DRAFT card
- **THEN** an inline panel SHALL expand below the card with query input, mode selector, and search button

#### Scenario: Test button collapses panel on second click

- **WHEN** the user clicks `Test` again while the panel is expanded
- **THEN** the panel SHALL collapse

#### Scenario: Default search mode is Hybrid

- **WHEN** the test panel opens
- **THEN** the mode selector SHALL default to `Hybrid`

#### Scenario: Search sends test request

- **WHEN** the user enters a query and clicks `Search`
- **THEN** a `POST /api/admin/snapshots/{id}/test` request SHALL be sent with `{ query, top_n: 5, mode }`

#### Scenario: Search results displayed

- **WHEN** the test request returns results
- **THEN** each result SHALL display: source title, score, anchor metadata, and text preview (first 500 characters)

#### Scenario: Mode selector responsive rendering

- **WHEN** the test panel renders on a desktop viewport
- **THEN** the mode selector SHALL render as radio buttons

- **WHEN** the test panel renders on a mobile viewport
- **THEN** the mode selector SHALL render as a dropdown

---

### Requirement: Toast notifications

The admin UI SHALL use toast notifications for success and error feedback. Toast types SHALL be: success (green), error (red), warning (yellow), info (blue). Toasts SHALL auto-dismiss after 5 seconds and SHALL be manually closable. Toasts SHALL be lightweight and SHALL NOT require a heavy external library.

#### Scenario: Success toast displayed after action

- **WHEN** an admin action (upload, delete, publish, activate, rollback) succeeds
- **THEN** a success toast SHALL display with a confirmation message

#### Scenario: Error toast displayed on failure

- **WHEN** an admin action fails
- **THEN** an error toast SHALL display with the error details

#### Scenario: Toast auto-dismisses

- **WHEN** a toast is displayed
- **THEN** it SHALL auto-dismiss after 5 seconds

#### Scenario: Toast manually closable

- **WHEN** a toast is displayed and the user clicks the close button
- **THEN** the toast SHALL dismiss immediately

---

### Requirement: Error handling for admin API calls

Admin API calls SHALL handle errors according to the following mapping: network errors SHALL show a toast `Connection error. Retrying...` with auto-retry after 5 seconds; 404 responses SHALL show a toast `Not found` and remove the entity from local state; 409 responses SHALL show a toast with the backend message and re-fetch the list; 422 responses SHALL show a toast with error details from the backend; 413 responses SHALL show a toast `File exceeds server size limit`; 500 responses SHALL show a toast `Server error` with the error message if available.

#### Scenario: Network error with retry

- **WHEN** a fetch request fails due to a network error
- **THEN** an error toast SHALL display `Connection error. Retrying...`
- **AND** the request SHALL be retried after 5 seconds

#### Scenario: 404 removes entity from state

- **WHEN** a request returns 404
- **THEN** a toast SHALL display `Not found`
- **AND** the entity SHALL be removed from the local state

#### Scenario: 409 conflict triggers re-fetch

- **WHEN** a request returns 409
- **THEN** a toast SHALL display the backend error message
- **AND** the list SHALL be re-fetched

#### Scenario: 422 validation error

- **WHEN** a request returns 422
- **THEN** a toast SHALL display the validation error details from the response

#### Scenario: 413 file too large

- **WHEN** an upload request returns 413
- **THEN** a toast SHALL display `File exceeds server size limit`

#### Scenario: 500 server error

- **WHEN** a request returns 500
- **THEN** a toast SHALL display `Server error` with additional details if available

---

### Requirement: Responsive layout

The admin UI SHALL be responsive. On desktop, the source list SHALL render as a table; on mobile, it SHALL render as a card stack. Tabs SHALL span full width on mobile (50/50 for two tabs). The draft test mode selector SHALL render as radio buttons on desktop and a dropdown on mobile. Snapshot cards SHALL adapt to the available width.

#### Scenario: Table to cards on mobile

- **WHEN** the viewport width is below the mobile breakpoint
- **THEN** the source list SHALL render as cards instead of a table

#### Scenario: Desktop table layout

- **WHEN** the viewport width is above the mobile breakpoint
- **THEN** the source list SHALL render as a table with columns

---

### Requirement: Test coverage for admin UI

All stable admin UI behavior MUST be covered by deterministic CI tests. Tests SHALL cover: admin routing with mode guard (redirect when disabled, access when enabled), source list rendering with status badges, source polling lifecycle (start on PENDING/PROCESSING, stop on terminal), drag and drop upload with file validation, soft delete with confirmation dialog, snapshot card rendering with status-dependent actions, snapshot lifecycle actions (create draft, publish, activate, rollback), and draft test search flow. Tests SHALL use mocked API responses and SHALL NOT depend on real backend services.

#### Scenario: Routing guard tests pass

- **WHEN** CI runs the admin routing test suite
- **THEN** tests SHALL verify: redirect to `/` when `VITE_ADMIN_MODE` is not `"true"`, access granted when `VITE_ADMIN_MODE` is `"true"`, `/admin` redirects to `/admin/sources`

#### Scenario: Source list tests pass

- **WHEN** CI runs the source list test suite
- **THEN** tests SHALL verify: rendering with correct status badge colors, polling starts for PENDING/PROCESSING sources, polling stops for terminal sources, delete confirmation dialog flow

#### Scenario: Upload tests pass

- **WHEN** CI runs the upload test suite
- **THEN** tests SHALL verify: file validation (allowed/rejected extensions, empty files), multi-file upload triggers separate requests, metadata auto-derivation from filename

#### Scenario: Snapshot tests pass

- **WHEN** CI runs the snapshot test suite
- **THEN** tests SHALL verify: card rendering with status-dependent actions, create draft disabled when draft exists, publish/activate/rollback action flows with confirmation dialogs, draft test panel expand/collapse and search flow

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

### Requirement: SOURCE_TYPE_BY_EXTENSION mapping for media types

**[Added by S3-04]** The `SOURCE_TYPE_BY_EXTENSION` mapping in `app/services/storage.py` SHALL include entries for IMAGE, AUDIO, and VIDEO source types: `.png` -> IMAGE, `.jpeg` -> IMAGE, `.jpg` -> IMAGE, `.mp3` -> AUDIO, `.wav` -> AUDIO, `.mp4` -> VIDEO. `SOURCE_TYPE_BY_EXTENSION` SHALL use lowercase keys only. The `determine_source_type()` function SHALL normalize the extracted extension to lowercase (via the same validation helper used by upload validation) before using this mapping to resolve the `SourceType`.

#### Scenario: Media extensions resolve to correct SourceType

- **WHEN** `determine_source_type()` is called with a filename ending in `.png`, `.jpeg`, or `.jpg`
- **THEN** the result SHALL be `SourceType.IMAGE`

- **WHEN** `determine_source_type()` is called with a filename ending in `.mp3` or `.wav`
- **THEN** the result SHALL be `SourceType.AUDIO`

- **WHEN** `determine_source_type()` is called with a filename ending in `.mp4`
- **THEN** the result SHALL be `SourceType.VIDEO`

#### Scenario: Existing text format mappings are unchanged

- **WHEN** `determine_source_type()` is called with a filename ending in `.md`, `.txt`, `.pdf`, `.docx`, `.html`, or `.htm`
- **THEN** the result SHALL match the existing mapping (MARKDOWN, TXT, PDF, DOCX, HTML, HTML respectively)

---

### Requirement: MIME_TYPE_BY_EXTENSION mapping for all file types

**[Added by S3-04]** The `app/services/storage.py` module SHALL export a `MIME_TYPE_BY_EXTENSION` dictionary mapping file extensions to their MIME types. `MIME_TYPE_BY_EXTENSION` SHALL use lowercase keys only. The `determine_mime_type()` helper SHALL normalize the extracted extension to lowercase via the same validation helper used by `determine_source_type()`. The mapping SHALL include all supported extensions:

| Extension | MIME Type                                                                 |
| --------- | ------------------------------------------------------------------------- |
| `.md`     | `text/markdown`                                                           |
| `.txt`    | `text/plain`                                                              |
| `.pdf`    | `application/pdf`                                                         |
| `.docx`   | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| `.html`   | `text/html`                                                               |
| `.htm`    | `text/html`                                                               |
| `.png`    | `image/png`                                                               |
| `.jpeg`   | `image/jpeg`                                                              |
| `.jpg`    | `image/jpeg`                                                              |
| `.mp3`    | `audio/mpeg`                                                              |
| `.wav`    | `audio/wav`                                                               |
| `.mp4`    | `video/mp4`                                                               |

This mapping SHALL be used by `determine_mime_type()` to determine the correct MIME type for storage upload headers and for `Source.mime_type` persistence. The persisted `mime_type` value SHALL then be reused by `GeminiContentService` and `EmbeddingService.embed_file()` when sending files to the Gemini API.

#### Scenario: MIME type lookup returns correct value for each extension

- **WHEN** `MIME_TYPE_BY_EXTENSION[".png"]` is accessed
- **THEN** the value SHALL be `"image/png"`

- **WHEN** `MIME_TYPE_BY_EXTENSION[".mp3"]` is accessed
- **THEN** the value SHALL be `"audio/mpeg"`

- **WHEN** `MIME_TYPE_BY_EXTENSION[".mp4"]` is accessed
- **THEN** the value SHALL be `"video/mp4"`

- **WHEN** `MIME_TYPE_BY_EXTENSION[".pdf"]` is accessed
- **THEN** the value SHALL be `"application/pdf"`

#### Scenario: MIME type lookup is case-insensitive through the helper

- **WHEN** `determine_mime_type()` is called with `photo.JPG` or `REPORT.PDF`
- **THEN** the helper SHALL normalize the extension to lowercase before lookup
- **AND** the result SHALL be `"image/jpeg"` for `photo.JPG` and `"application/pdf"` for `REPORT.PDF`

#### Scenario: All allowed extensions have a MIME type entry

- **WHEN** the set of keys in `MIME_TYPE_BY_EXTENSION` is compared with the supported extension set defined in the file extension validation requirement
- **THEN** every supported extension SHALL have a corresponding entry in `MIME_TYPE_BY_EXTENSION`
