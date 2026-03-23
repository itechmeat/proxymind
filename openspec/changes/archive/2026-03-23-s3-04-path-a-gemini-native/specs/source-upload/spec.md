## MODIFIED Requirements

### Requirement: File extension validation and source type mapping

**[Modified by S3-04]** The upload validation SHALL accept the following file extensions: `.md`, `.txt`, `.pdf`, `.docx`, `.html`, `.htm`, `.png`, `.jpeg`, `.jpg`, `.mp3`, `.wav`, `.mp4`. Extension validation SHALL be case-insensitive. The canonical supported extension set in code SHALL be represented by `ALLOWED_SOURCE_EXTENSIONS` with lowercase entries only. Implementations SHALL normalize the extracted file extension to lowercase before validating membership in `ALLOWED_SOURCE_EXTENSIONS`. The `source_type` SHALL be determined automatically from the file extension using the following mapping:

| Extension | SourceType |
|-----------|------------|
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

## ADDED Requirements

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

| Extension | MIME Type |
|-----------|-----------|
| `.md`     | `text/markdown` |
| `.txt`    | `text/plain` |
| `.pdf`    | `application/pdf` |
| `.docx`   | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
| `.html`   | `text/html` |
| `.htm`    | `text/html` |
| `.png`    | `image/png` |
| `.jpeg`   | `image/jpeg` |
| `.jpg`    | `image/jpeg` |
| `.mp3`    | `audio/mpeg` |
| `.wav`    | `audio/wav` |
| `.mp4`    | `video/mp4` |

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
