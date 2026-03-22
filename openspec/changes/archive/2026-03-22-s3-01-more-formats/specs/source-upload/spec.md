## MODIFIED Requirements

### Requirement: POST /api/admin/sources endpoint

The API SHALL expose a `POST /api/admin/sources` endpoint that accepts a multipart/form-data request with two fields: `file` (UploadFile) and `metadata` (string containing JSON). The endpoint SHALL return `202 Accepted` on success. The endpoint SHALL NOT require authentication (explicit security exception — local-only deployment; `TODO(S7-01)` MUST be present in the codebase).

> **MODIFIED by S3-01:** The unsupported file format scenario is updated to reflect the expanded set of allowed extensions.

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

#### Scenario: Unsupported file format is rejected

- **WHEN** a POST request is sent with a file having an extension other than `.md`, `.txt`, `.pdf`, `.docx`, `.html`, or `.htm` (e.g., `.xlsx`, `.pptx`, `.xml`)
- **THEN** the response status SHALL be 422
- **AND** the response body SHALL indicate the file format is unsupported and list the allowed extensions

#### Scenario: Empty file is rejected

- **WHEN** a POST request is sent with a zero-byte file
- **THEN** the response status SHALL be 422

#### Scenario: Oversized file is rejected

- **WHEN** a POST request is sent with a file exceeding the configured `UPLOAD_MAX_FILE_SIZE_MB` limit
- **THEN** the response status SHALL be 413

#### Scenario: File extension validation is case-insensitive

- **WHEN** a POST request is sent with a file named `DOCUMENT.PDF`, `report.Docx`, or `page.HTML`
- **THEN** the endpoint SHALL accept the file as a valid format

---

### Requirement: File extension validation and source type mapping

The upload validation SHALL accept the following file extensions: `.md`, `.txt`, `.pdf`, `.docx`, `.html`, `.htm`. Extension validation SHALL be case-insensitive. The `source_type` SHALL be determined automatically from the file extension using the following mapping:

| Extension | SourceType |
|-----------|------------|
| `.md`     | MARKDOWN   |
| `.txt`    | TXT        |
| `.pdf`    | PDF        |
| `.docx`   | DOCX       |
| `.html`   | HTML       |
| `.htm`    | HTML       |

> **MODIFIED by S3-01:** Extended from `.md`/`.txt` to include `.pdf`, `.docx`, `.html`, `.htm`. Both `.html` and `.htm` map to `SourceType.HTML`.

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

#### Scenario: Case-insensitive new extensions

- **WHEN** a file named `REPORT.PDF` or `Document.Docx` is uploaded
- **THEN** the endpoint SHALL accept the file and determine the correct `source_type`

#### Scenario: Unsupported extensions are still rejected

- **WHEN** a file with extension `.xlsx`, `.pptx`, or `.xml` is uploaded
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
