## ADDED Requirements

### Requirement: PreparedFilePart dataclass

The system SHALL define a `PreparedFilePart` dataclass in `app/services/gemini_file_transfer.py` with the following fields:

- `part: types.Part` — the Gemini SDK Part object to pass to GenerateContent or embed_content
- `uploaded_file_name: str | None` — the name of the file uploaded via Files API, or `None` if inline transfer was used

The `uploaded_file_name` field SHALL be used by `cleanup_uploaded_file()` to delete the uploaded file after processing. When `uploaded_file_name` is `None`, no cleanup is needed.

#### Scenario: PreparedFilePart with inline transfer has no uploaded_file_name

- **WHEN** a `PreparedFilePart` is created for an inline transfer
- **THEN** `part` SHALL be a `types.Part` object and `uploaded_file_name` SHALL be `None`

#### Scenario: PreparedFilePart with Files API transfer has uploaded_file_name

- **WHEN** a `PreparedFilePart` is created for a Files API transfer
- **THEN** `part` SHALL be a `types.Part` object and `uploaded_file_name` SHALL be a non-empty string

---

### Requirement: prepare_file_part inline transfer

The module SHALL provide an async function `prepare_file_part(client: genai.Client, file_bytes: bytes, mime_type: str, *, threshold_bytes: int) -> PreparedFilePart`. When `len(file_bytes) < threshold_bytes` (default 10,485,760 = 10 MB), the function SHALL create a `types.Part.from_bytes(data=file_bytes, mime_type=mime_type)` and return a `PreparedFilePart` with the part and `uploaded_file_name=None`. No network call SHALL be made for inline transfer.

#### Scenario: File under threshold uses inline Part.from_bytes (CI, mocked GenAI)

- **WHEN** `prepare_file_part()` is called with a 5 MB file and `threshold_bytes=10_485_760`
- **THEN** the returned `PreparedFilePart.part` SHALL be created via `types.Part.from_bytes()`
- **AND** `uploaded_file_name` SHALL be `None`
- **AND** no Files API upload call SHALL be made

#### Scenario: File at exactly one byte below threshold uses inline transfer

- **WHEN** `prepare_file_part()` is called with a file of size `threshold_bytes - 1`
- **THEN** inline transfer SHALL be used and `uploaded_file_name` SHALL be `None`

---

### Requirement: prepare_file_part Files API transfer

When `len(file_bytes) >= threshold_bytes`, `prepare_file_part()` SHALL upload the file via `client.files.upload(file=io.BytesIO(file_bytes), config={"mime_type": mime_type})`. After upload, the function SHALL call `_wait_until_active()` to poll until the file state is `ACTIVE`. Once active, the function SHALL create a `types.Part.from_uri(file_uri=uploaded_file.uri, mime_type=mime_type)` and return a `PreparedFilePart` with the part and `uploaded_file_name=uploaded_file.name`.

#### Scenario: File at threshold uses Files API upload (CI, mocked GenAI)

- **WHEN** `prepare_file_part()` is called with a file of size exactly `threshold_bytes`
- **THEN** the file SHALL be uploaded via `client.files.upload()`
- **AND** `_wait_until_active()` SHALL be called on the uploaded file
- **AND** the returned `PreparedFilePart.part` SHALL be created via `types.Part.from_uri()`
- **AND** `uploaded_file_name` SHALL be the name returned by the Files API

#### Scenario: Large video file uses Files API upload (CI, mocked GenAI)

- **WHEN** `prepare_file_part()` is called with a 25 MB MP4 file and `threshold_bytes=10_485_760`
- **THEN** the file SHALL be uploaded via the Files API
- **AND** `uploaded_file_name` SHALL be a non-empty string

---

### Requirement: _wait_until_active polling

The module SHALL provide an internal async function `_wait_until_active(client: genai.Client, file_name: str, *, poll_interval: float = 1.0, max_wait: float = 300.0)` that polls `client.files.get(name=file_name)` until the file's `state` is `ACTIVE`. The function SHALL raise a `TimeoutError` if the file does not become `ACTIVE` within `max_wait` seconds. The function SHALL raise a `RuntimeError` if the file enters a `FAILED` state. Polling is required because video files uploaded via the Files API need processing time before they can be used in API calls.

#### Scenario: File becomes ACTIVE on first poll (CI, mocked GenAI)

- **WHEN** `_wait_until_active()` is called and `client.files.get()` immediately returns a file with `state=ACTIVE`
- **THEN** the function SHALL return without waiting

#### Scenario: File becomes ACTIVE after multiple polls (CI, mocked GenAI)

- **WHEN** `_wait_until_active()` is called and the file state transitions from `PROCESSING` to `ACTIVE` after 3 polls
- **THEN** the function SHALL return after the file becomes `ACTIVE`
- **AND** `client.files.get()` SHALL have been called at least 3 times

#### Scenario: File does not become ACTIVE within max_wait

- **WHEN** `_wait_until_active()` is called with `max_wait=5.0` and the file remains in `PROCESSING` state
- **THEN** the function SHALL raise a `TimeoutError` after approximately 5 seconds
- **AND** the error message SHALL include the file name

#### Scenario: File enters FAILED state during polling

- **WHEN** `_wait_until_active()` is called and `client.files.get()` returns a file with `state=FAILED`
- **THEN** the function SHALL raise a `RuntimeError`
- **AND** the error message SHALL include the file name and indicate the file processing failed

---

### Requirement: cleanup_uploaded_file

The module SHALL provide an async function `cleanup_uploaded_file(client: genai.Client, file_name: str | None) -> None`. If `file_name` is `None`, the function SHALL return immediately (no-op). If `file_name` is not `None`, the function SHALL call `client.files.delete(name=file_name)` to remove the uploaded file from the Gemini Files API storage. The deletion SHALL be best-effort: any exception during deletion SHALL be logged as a warning via structlog but SHALL NOT propagate to the caller. This ensures that temporary files are cleaned up but cleanup failures do not cause ingestion failures.

#### Scenario: Cleanup with None file_name is a no-op

- **WHEN** `cleanup_uploaded_file()` is called with `file_name=None`
- **THEN** no Files API call SHALL be made
- **AND** the function SHALL return without error

#### Scenario: Cleanup deletes the uploaded file (CI, mocked GenAI)

- **WHEN** `cleanup_uploaded_file()` is called with a valid `file_name`
- **THEN** `client.files.delete(name=file_name)` SHALL be called

#### Scenario: Cleanup failure is logged but does not raise (CI, mocked GenAI)

- **WHEN** `cleanup_uploaded_file()` is called and `client.files.delete()` raises an exception
- **THEN** the exception SHALL NOT propagate to the caller
- **AND** a warning SHALL be logged via structlog containing the file name and error details

#### Scenario: Cleanup is always called in finally block by callers

- **WHEN** `GeminiContentService.extract_text_content()` or `EmbeddingService.embed_file()` uses a `PreparedFilePart` with a non-None `uploaded_file_name`
- **THEN** `cleanup_uploaded_file()` SHALL be called in a `finally` block, ensuring cleanup runs even if the API call raises an exception

---

## Test Coverage

### CI tests (deterministic, mocked external services)

- **prepare_file_part unit tests** (`tests/unit/services/test_gemini_file_transfer.py`): mock `google.genai.Client`. Verify inline path for files below threshold (Part.from_bytes called, no upload). Verify Files API path for files at or above threshold (upload called, _wait_until_active called, Part.from_uri created). Verify threshold boundary: file at `threshold_bytes - 1` uses inline, file at `threshold_bytes` uses Files API.
- **_wait_until_active unit tests**: mock `client.files.get()`. Verify immediate return when ACTIVE. Verify polling loop with PROCESSING then ACTIVE. Verify TimeoutError after max_wait. Verify RuntimeError on FAILED state.
- **cleanup_uploaded_file unit tests**: verify no-op for None. Verify delete call for valid name. Verify exception suppression with warning log.
- **PreparedFilePart dataclass tests**: verify field access and types.

### Evals (non-CI, real providers)

- Upload a video file (>10 MB) through the full ingestion pipeline and verify that Files API upload, polling, and cleanup all complete successfully with real Gemini Files API.
