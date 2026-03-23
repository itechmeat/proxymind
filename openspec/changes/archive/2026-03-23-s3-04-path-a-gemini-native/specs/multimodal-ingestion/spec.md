## ADDED Requirements

### Requirement: PathRouter file inspection

The system SHALL provide a `PathRouter` service at `app/services/path_router.py` with an `inspect_file(file_bytes: bytes, source_type: SourceType) -> FileMetadata` method. `FileMetadata` SHALL be a dataclass with fields: `page_count: int | None`, `duration_seconds: float | None`, `file_size_bytes: int`. For `PDF` source type, the method SHALL use `pypdf.PdfReader` to count pages and return `page_count`. For `AUDIO` and `VIDEO` source types, the method SHALL use `tinytag.TinyTag` to read `duration_seconds` from file metadata headers. For `IMAGE` source type, both `page_count` and `duration_seconds` SHALL be `None`. On inspection failure (corrupt file, unreadable metadata), the failed field SHALL be `None` — the caller decides how to handle missing metadata.

#### Scenario: Inspect a valid PDF returns page count

- **WHEN** `inspect_file()` is called with bytes of a 4-page PDF and `source_type=SourceType.PDF`
- **THEN** the returned `FileMetadata` SHALL have `page_count=4`, `duration_seconds=None`, and `file_size_bytes` equal to the length of the input bytes

#### Scenario: Inspect a valid MP3 returns duration

- **WHEN** `inspect_file()` is called with bytes of a 45-second MP3 file and `source_type=SourceType.AUDIO`
- **THEN** the returned `FileMetadata` SHALL have `page_count=None`, `duration_seconds` approximately 45.0, and `file_size_bytes` equal to the length of the input bytes

#### Scenario: Inspect an image returns no page count or duration

- **WHEN** `inspect_file()` is called with bytes of a PNG file and `source_type=SourceType.IMAGE`
- **THEN** the returned `FileMetadata` SHALL have `page_count=None` and `duration_seconds=None`

#### Scenario: Corrupt PDF returns None for page count

- **WHEN** `inspect_file()` is called with corrupt bytes and `source_type=SourceType.PDF`
- **THEN** the returned `FileMetadata` SHALL have `page_count=None`
- **AND** no exception SHALL propagate to the caller

#### Scenario: Unreadable audio metadata returns None for duration

- **WHEN** `inspect_file()` is called with bytes from which `tinytag` cannot extract duration and `source_type=SourceType.AUDIO`
- **THEN** the returned `FileMetadata` SHALL have `duration_seconds=None`
- **AND** no exception SHALL propagate to the caller

---

### Requirement: PathRouter path determination

The `PathRouter` SHALL provide a pure function `determine_path(source_type: SourceType, file_metadata: FileMetadata, settings: Settings) -> PathDecision`. `PathDecision` SHALL be a dataclass with fields: `path: ProcessingPath | None`, `reason: str`, `rejected: bool`. The routing rules SHALL be:

- `IMAGE` -> always `ProcessingPath.PATH_A`
- `PDF` -> `PATH_A` if `file_metadata.page_count` is not None and `page_count <= settings.path_a_max_pdf_pages` (default 6); otherwise `PATH_B`
- `AUDIO` -> `PATH_A` if `file_metadata.duration_seconds` is None (unknown — proceed optimistically, threshold check is the safety net) or `duration_seconds <= settings.path_a_max_audio_duration_sec` (default 80); if duration is known and exceeds the limit, `rejected=True` and `path=None`
- `VIDEO` -> `PATH_A` if `file_metadata.duration_seconds` is None (unknown — proceed optimistically) or `duration_seconds <= settings.path_a_max_video_duration_sec` (default 120); if duration is known and exceeds the limit, `rejected=True` and `path=None`
- `MARKDOWN`, `TXT`, `DOCX`, `HTML` -> always `PATH_B`

When `rejected=True`, the ingestion task SHALL be marked FAILED because Path B is not available for audio/video formats. `determine_path()` SHALL be a pure function with no I/O, making it 100% unit-testable without mocks.

#### Scenario: Image always routes to Path A

- **WHEN** `determine_path()` is called with `source_type=SourceType.IMAGE` and any `FileMetadata`
- **THEN** the result SHALL have `path=ProcessingPath.PATH_A` and `rejected=False`

#### Scenario: Short PDF routes to Path A

- **WHEN** `determine_path()` is called with `source_type=SourceType.PDF` and `FileMetadata(page_count=4)`
- **THEN** the result SHALL have `path=ProcessingPath.PATH_A` and `rejected=False`

#### Scenario: Long PDF routes to Path B

- **WHEN** `determine_path()` is called with `source_type=SourceType.PDF` and `FileMetadata(page_count=10)`
- **THEN** the result SHALL have `path=ProcessingPath.PATH_B` and `rejected=False`

#### Scenario: PDF at exact page threshold routes to Path A

- **WHEN** `determine_path()` is called with `source_type=SourceType.PDF` and `FileMetadata(page_count=6)` and `path_a_max_pdf_pages=6`
- **THEN** the result SHALL have `path=ProcessingPath.PATH_A`

#### Scenario: PDF exceeding page threshold by one routes to Path B

- **WHEN** `determine_path()` is called with `source_type=SourceType.PDF` and `FileMetadata(page_count=7)` and `path_a_max_pdf_pages=6`
- **THEN** the result SHALL have `path=ProcessingPath.PATH_B`

#### Scenario: PDF with unknown page count falls back to Path B

- **WHEN** `determine_path()` is called with `source_type=SourceType.PDF` and `FileMetadata(page_count=None)`
- **THEN** the result SHALL have `path=ProcessingPath.PATH_B` and `rejected=False`
- **AND** `reason` SHALL indicate that page count could not be determined

#### Scenario: Audio within duration limit routes to Path A

- **WHEN** `determine_path()` is called with `source_type=SourceType.AUDIO` and `FileMetadata(duration_seconds=60.0)`
- **THEN** the result SHALL have `path=ProcessingPath.PATH_A` and `rejected=False`

#### Scenario: Audio exceeding duration limit is rejected

- **WHEN** `determine_path()` is called with `source_type=SourceType.AUDIO` and `FileMetadata(duration_seconds=100.0)` and `path_a_max_audio_duration_sec=80`
- **THEN** the result SHALL have `path=None` and `rejected=True`
- **AND** `reason` SHALL indicate that audio exceeds the duration limit and Path B is not available

#### Scenario: Video at exact duration threshold routes to Path A

- **WHEN** `determine_path()` is called with `source_type=SourceType.VIDEO` and `FileMetadata(duration_seconds=120.0)` and `path_a_max_video_duration_sec=120`
- **THEN** the result SHALL have `path=ProcessingPath.PATH_A`

#### Scenario: Video exceeding duration limit is rejected

- **WHEN** `determine_path()` is called with `source_type=SourceType.VIDEO` and `FileMetadata(duration_seconds=150.0)`
- **THEN** the result SHALL have `path=None` and `rejected=True`

#### Scenario: Markdown always routes to Path B

- **WHEN** `determine_path()` is called with `source_type=SourceType.MARKDOWN`
- **THEN** the result SHALL have `path=ProcessingPath.PATH_B` and `rejected=False`

#### Scenario: TXT always routes to Path B

- **WHEN** `determine_path()` is called with `source_type=SourceType.TXT`
- **THEN** the result SHALL have `path=ProcessingPath.PATH_B` and `rejected=False`

#### Scenario: Audio with unknown duration defaults to Path A

- **WHEN** `determine_path()` is called with `source_type=SourceType.AUDIO` and `FileMetadata(duration_seconds=None)`
- **THEN** the result SHALL have `path=ProcessingPath.PATH_A` and `rejected=False`
- **AND** `reason` SHALL indicate that duration could not be determined and Path A is assumed (threshold check is the safety net)

---

### Requirement: GeminiContentService text extraction

The system SHALL provide a `GeminiContentService` at `app/services/gemini_content.py` that extracts text content from multimodal files via Gemini LLM GenerateContent. The service SHALL accept `file_bytes: bytes`, `mime_type: str`, and `source_type: SourceType`, and return a `str` containing the extracted text. The service SHALL use the `google.genai.Client` with the model specified by `settings.gemini_content_model` (default `"gemini-2.5-flash"`). Per-modality extraction prompts SHALL be defined as module-level constants (`EXTRACTION_PROMPTS: dict[SourceType, str]`). All prompts SHALL be language-neutral, instructing the model to "preserve the original language" per the multilingual policy. The service SHALL use `prepare_file_part()` from `gemini_file_transfer` to handle file transfer (inline vs Files API). Retry SHALL use tenacity with exponential backoff (3 attempts).

#### Scenario: Extract text from a PDF file

- **WHEN** `extract_text_content()` is called with PDF bytes, `mime_type="application/pdf"`, and `source_type=SourceType.PDF`
- **THEN** the service SHALL call Gemini LLM GenerateContent with the PDF extraction prompt and the file content
- **AND** the result SHALL be a non-empty string containing the extracted text

#### Scenario: Extract text from an image file

- **WHEN** `extract_text_content()` is called with JPEG bytes, `mime_type="image/jpeg"`, and `source_type=SourceType.IMAGE`
- **THEN** the service SHALL call Gemini LLM GenerateContent with the image extraction prompt
- **AND** the result SHALL describe the visual content of the image

#### Scenario: Extract text from an audio file

- **WHEN** `extract_text_content()` is called with MP3 bytes, `mime_type="audio/mpeg"`, and `source_type=SourceType.AUDIO`
- **THEN** the service SHALL call Gemini LLM GenerateContent with the audio extraction prompt

#### Scenario: Correct prompt selected per source type (CI, mocked Gemini)

- **WHEN** `extract_text_content()` is called with `source_type=SourceType.IMAGE`
- **THEN** the underlying GenerateContent call SHALL receive the prompt from `EXTRACTION_PROMPTS[SourceType.IMAGE]`

#### Scenario: Transient Gemini error is retried

- **WHEN** the Gemini LLM GenerateContent call fails on the first attempt with a transient error and succeeds on the second
- **THEN** the method SHALL return the extracted text without raising an exception

#### Scenario: Persistent Gemini failure after max retries raises exception

- **WHEN** the Gemini LLM GenerateContent call fails on all 3 attempts
- **THEN** the method SHALL raise an exception after exhausting retries

#### Scenario: Empty extracted text is treated as failure

- **WHEN** `extract_text_content()` receives an empty or whitespace-only response from Gemini
- **THEN** the method SHALL raise an error instead of returning an empty string
- **AND** the ingestion task SHALL later be marked FAILED rather than creating an empty chunk

#### Scenario: Cleanup is called after Files API upload (CI, mocked Gemini)

- **WHEN** `extract_text_content()` uses the Files API path (file >= 10 MB)
- **THEN** `cleanup_uploaded_file()` SHALL be called after GenerateContent completes, regardless of success or failure

---

### Requirement: EmbeddingService multimodal file embedding

The `EmbeddingService` at `app/services/embedding.py` SHALL provide a new method `embed_file(file_bytes: bytes, mime_type: str, *, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]`. This method SHALL generate a dense embedding directly from the original file via Gemini Embedding 2, using `prepare_file_part()` from `gemini_file_transfer` for file transfer. The method SHALL use the same `google.genai.Client`, model, and dimensions as `embed_texts()`. The method SHALL pass `task_type` and `output_dimensionality` to the GenAI SDK. Retry SHALL use the same tenacity configuration as `embed_texts()`.

#### Scenario: Generate embedding from an image file (CI, mocked GenAI)

- **WHEN** `embed_file()` is called with JPEG bytes and `mime_type="image/jpeg"`
- **THEN** the result SHALL be a list of floats with length equal to `embedding_dimensions`
- **AND** the GenAI SDK call SHALL receive `task_type="RETRIEVAL_DOCUMENT"` and `output_dimensionality` matching the configured dimensions

#### Scenario: Generate embedding from a PDF file (CI, mocked GenAI)

- **WHEN** `embed_file()` is called with PDF bytes and `mime_type="application/pdf"`
- **THEN** the result SHALL be a list of floats with length equal to `embedding_dimensions`

#### Scenario: Small file uses inline transfer (CI, mocked GenAI)

- **WHEN** `embed_file()` is called with a file smaller than `gemini_file_upload_threshold_bytes` (10 MB)
- **THEN** `prepare_file_part()` SHALL use `Part.from_bytes()` for inline transfer

#### Scenario: Large file uses Files API transfer (CI, mocked GenAI)

- **WHEN** `embed_file()` is called with a file larger than or equal to `gemini_file_upload_threshold_bytes`
- **THEN** `prepare_file_part()` SHALL upload via the Files API

#### Scenario: Cleanup is called after Files API upload (CI, mocked GenAI)

- **WHEN** `embed_file()` uses the Files API path
- **THEN** `cleanup_uploaded_file()` SHALL be called after the embed call completes

---

### Requirement: Path A handler single-chunk creation

The system SHALL provide a Path A handler at `app/workers/tasks/handlers/path_a.py` with a function `handle_path_a()` that executes the following steps in order:

1. Call `GeminiContentService.extract_text_content()` to obtain `text_content`
2. Count tokens in `text_content` via `HuggingFaceTokenizer.count_tokens()`
3. Threshold check applies only to PDF, AUDIO, and VIDEO — **not to IMAGE** (images are inherently single-chunk regardless of description length). If token count exceeds the threshold (`path_a_text_threshold_pdf` for PDF, `path_a_text_threshold_media` for AUDIO/VIDEO): for PDF, return a fallback signal to the orchestrator which SHALL dispatch to Path B; for AUDIO and VIDEO, raise an error causing the task to be marked FAILED (Path B is not available for these formats). For IMAGE, proceed to embedding regardless of token count
4. If token count is within threshold: call `EmbeddingService.embed_file()` to generate a dense vector from the original file, build a BM25 sparse vector from `text_content`, create a single `Chunk` record in PostgreSQL, and upsert to Qdrant with both dense and BM25 named vectors plus payload
5. Return the pipeline metadata needed for finalization so the orchestrator can create an `EmbeddingProfile` with `pipeline_version="s3-04-path-a"`

The handler SHALL create exactly one chunk per file. The `DocumentVersion.processing_path` SHALL be set to `ProcessingPath.PATH_A`.

#### Scenario: Happy path produces a single chunk (CI, mocked Gemini)

- **WHEN** `handle_path_a()` processes an image file
- **AND** `GeminiContentService` returns non-empty `text_content`
- **THEN** exactly one `Chunk` record SHALL be created in PostgreSQL
- **AND** the chunk SHALL have `text_content` equal to the extracted text
- **AND** one Qdrant point SHALL be upserted with both dense and BM25 named vectors
- **AND** the `DocumentVersion.processing_path` SHALL be `ProcessingPath.PATH_A`

#### Scenario: PDF threshold exceeded triggers Path B fallback (CI, mocked Gemini)

- **WHEN** `handle_path_a()` processes a PDF file
- **AND** `GeminiContentService` returns text_content with token count exceeding `path_a_text_threshold_pdf`
- **THEN** the handler SHALL return a fallback signal (not raise an exception)
- **AND** no Chunk record SHALL be created by the Path A handler
- **AND** the orchestrator SHALL dispatch the file to Path B

#### Scenario: Audio threshold exceeded marks task FAILED (CI, mocked Gemini)

- **WHEN** `handle_path_a()` processes an audio file
- **AND** `GeminiContentService` returns text_content with token count exceeding `path_a_text_threshold_media`
- **THEN** the handler SHALL raise an error
- **AND** the task SHALL be marked FAILED with a message indicating that audio content is too dense for single-chunk indexing and no structural parser is available

#### Scenario: Video threshold exceeded marks task FAILED (CI, mocked Gemini)

- **WHEN** `handle_path_a()` processes a video file
- **AND** `GeminiContentService` returns text_content with token count exceeding `path_a_text_threshold_media`
- **THEN** the handler SHALL raise an error
- **AND** the task SHALL be marked FAILED

#### Scenario: Gemini extraction failure marks task FAILED (CI, mocked Gemini)

- **WHEN** `handle_path_a()` processes a file
- **AND** `GeminiContentService.extract_text_content()` raises an exception after retries
- **THEN** the task SHALL be marked FAILED with `error_message` containing the exception details

#### Scenario: Gemini embedding failure marks task FAILED (CI, mocked Gemini)

- **WHEN** `handle_path_a()` processes a file
- **AND** `EmbeddingService.embed_file()` raises an exception after retries
- **THEN** the task SHALL be marked FAILED
- **AND** the handler SHALL attempt compensating Qdrant point deletion if it has already started or completed a Qdrant upsert call for the chunk
- **AND** cleanup failure SHALL be logged as a secondary error while the original ingestion failure is re-raised

#### Scenario: Successful Path A ingestion records the Path A pipeline version

- **WHEN** Path A ingestion completes successfully
- **THEN** finalization SHALL create an `EmbeddingProfile` record with `pipeline_version="s3-04-path-a"`

---

### Requirement: Token counting via HuggingFaceTokenizer

The Path A handler SHALL count tokens in `text_content` using the `HuggingFaceTokenizer` already present in the project (used by Docling HybridChunker). A `count_tokens(text: str) -> int` function SHALL be available for use by the handler. The tokenizer SHALL work correctly for multilingual text. The token count SHALL be compared against `settings.path_a_text_threshold_pdf` (default 2000) for PDF sources and `settings.path_a_text_threshold_media` (default 500) for AUDIO and VIDEO sources. IMAGE sources SHALL bypass threshold enforcement and continue as a single Path A chunk regardless of description length.

#### Scenario: Token count below PDF threshold allows Path A

- **WHEN** `count_tokens()` returns 1500 for a PDF's text_content and `path_a_text_threshold_pdf=2000`
- **THEN** the Path A handler SHALL proceed with embedding and chunk creation

#### Scenario: Token count at exact PDF threshold allows Path A

- **WHEN** `count_tokens()` returns 2000 for a PDF's text_content and `path_a_text_threshold_pdf=2000`
- **THEN** the Path A handler SHALL proceed with embedding and chunk creation (threshold is inclusive)

#### Scenario: Token count above PDF threshold triggers fallback

- **WHEN** `count_tokens()` returns 2001 for a PDF's text_content and `path_a_text_threshold_pdf=2000`
- **THEN** the Path A handler SHALL return a fallback signal to dispatch to Path B

#### Scenario: Media threshold is applied for audio and video

- **WHEN** `count_tokens()` returns 600 for an audio file's text_content and `path_a_text_threshold_media=500`
- **THEN** the Path A handler SHALL mark the task FAILED (media threshold exceeded, no Path B available)

---

### Requirement: Path A anchor metadata

For Path A chunks, the handler SHALL populate anchor metadata fields on the `Chunk` record and Qdrant payload as follows:

| Source Type | `anchor_page` | `anchor_chapter` | `anchor_section` | `anchor_timecode` |
|-------------|---------------|-------------------|-------------------|---------------------|
| PDF         | `1`           | `None`            | `None`            | `None`              |
| IMAGE       | `None`        | `None`            | `None`            | `None`              |
| AUDIO       | `None`        | `None`            | `None`            | `"0:00-{duration}"` |
| VIDEO       | `None`        | `None`            | `None`            | `"0:00-{duration}"` |

The `{duration}` in `anchor_timecode` SHALL be formatted as `M:SS` (e.g., `"0:00-1:20"` for 80 seconds). The Qdrant payload SHALL include `page_count` (int, omitted when None) and `duration_seconds` (float, omitted when None) from `FileMetadata`. These fields are stored in payload only — reader-side exposure (RetrievedChunk, API schemas) is deferred to S4-03 (citation builder). No retrieval or API changes are required in this story.

#### Scenario: PDF chunk has anchor_page set to 1

- **WHEN** a Path A chunk is created for a PDF file
- **THEN** `anchor_page` SHALL be `1` and `anchor_timecode` SHALL be `None`

#### Scenario: Audio chunk has anchor_timecode with duration

- **WHEN** a Path A chunk is created for an audio file with `duration_seconds=75.0`
- **THEN** `anchor_timecode` SHALL be `"0:00-1:15"` and `anchor_page` SHALL be `None`

#### Scenario: Image chunk has no anchor metadata

- **WHEN** a Path A chunk is created for an image file
- **THEN** `anchor_page`, `anchor_chapter`, `anchor_section`, and `anchor_timecode` SHALL all be `None`

#### Scenario: Qdrant payload includes only non-null metadata fields

- **WHEN** a Path A chunk is upserted to Qdrant for a 4-page PDF
- **THEN** the Qdrant point payload SHALL include `page_count=4`
- **AND** `duration_seconds` SHALL be omitted because its value is `None`

---

### Requirement: Path A configuration settings

The `Settings` class in `app/core/config.py` SHALL include the following new fields with defaults:

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `path_a_text_threshold_pdf` | `int` | `2000` | Token threshold for PDF Path A to Path B fallback |
| `path_a_text_threshold_media` | `int` | `500` | Token threshold for AUDIO/VIDEO (not applied to IMAGE) |
| `path_a_max_pdf_pages` | `int` | `6` | Max PDF pages for Path A eligibility |
| `path_a_max_audio_duration_sec` | `int` | `80` | Max audio duration in seconds for Path A |
| `path_a_max_video_duration_sec` | `int` | `120` | Max video duration in seconds for Path A |
| `gemini_content_model` | `str` | `"gemini-2.5-flash"` | Gemini model for text extraction |
| `gemini_file_upload_threshold_bytes` | `int` | `10485760` | Inline vs Files API threshold (10 MB) |

All settings SHALL follow the existing convention: snake_case field names map to uppercase environment variables.

#### Scenario: Default settings are correct

- **WHEN** `Settings` is instantiated with no overrides for Path A fields
- **THEN** `path_a_text_threshold_pdf` SHALL be 2000, `path_a_text_threshold_media` SHALL be 500, `path_a_max_pdf_pages` SHALL be 6, `path_a_max_audio_duration_sec` SHALL be 80, `path_a_max_video_duration_sec` SHALL be 120, `gemini_content_model` SHALL be `"gemini-2.5-flash"`, and `gemini_file_upload_threshold_bytes` SHALL be 10485760

#### Scenario: Settings are overridable via environment variables

- **WHEN** `PATH_A_MAX_PDF_PAGES=10` is set in the environment
- **THEN** `settings.path_a_max_pdf_pages` SHALL be 10

---

## Test Coverage

### CI tests (deterministic, mocked external services)

- **PathRouter unit tests** (`tests/unit/services/test_path_router.py`): parametrized tests for `determine_path()` covering every source type, boundary values (exact thresholds), unknown metadata (None fields), and Path B-only source types. Separate tests for `inspect_file()` with real file fixtures (small PDF, MP3, PNG). Corrupt file handling tests.
- **GeminiContentService unit tests** (`tests/unit/services/test_gemini_content.py`): mock `google.genai.Client`. Verify correct prompt selection per source type. Verify inline path for small files and Files API path for large files. Verify cleanup is called after Files API usage. Verify retry behavior.
- **EmbeddingService.embed_file unit tests** (`tests/unit/services/test_embedding_file.py`): mock GenAI client. Verify correct task type and dimensions. Verify inline vs Files API threshold. Verify cleanup after Files API.
- **Path A handler unit tests** (`tests/unit/workers/test_path_a_handler.py`): mock GeminiContentService, EmbeddingService, QdrantService. Verify happy path (single chunk created), PDF threshold fallback, media threshold FAILED, Gemini failure propagation, anchor metadata correctness.
- **Path A integration tests** (`tests/integration/test_path_a_ingestion.py`): mock only Gemini (fixed text_content + embedding vector), real Qdrant. Verify chunk upsert with dense + BM25 vectors. Verify payload fields. Verify hybrid search retrieves the chunk.

### Evals (non-CI, real providers)

- Upload image file, verify text_content quality from real Gemini LLM.
- Upload short PDF, verify multimodal embedding quality via search recall.
- Upload audio file, verify transcription-like text_content from Gemini.
- Threshold calibration: upload files of varying content density, evaluate whether default thresholds produce correct Path A / Path B routing decisions.
