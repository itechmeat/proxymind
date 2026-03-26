# document-ai-fallback

**Story:** S4-06 — Lightweight Knowledge Processing Migration
**Status:** NEW capability
**Test coverage requirement:** All stable behavior introduced by this capability MUST be covered by CI tests before archive.

---

## ADDED Requirements

### Requirement: DocumentAIParser implements DocumentProcessor Protocol

The system SHALL provide a `DocumentAIParser` class at `app/services/document_ai_parser.py` that implements the `DocumentProcessor` Protocol. The class SHALL accept `content: bytes`, `filename: str`, and `source_type: SourceType` via the `parse_and_chunk()` method and return `list[ChunkData]`. The `DocumentAIParser` SHALL use Google Cloud Document AI (Layout Parser processor) to process documents. The class SHALL send the raw document bytes to the Document AI API and receive structured output including pages, blocks, paragraphs, tables, and reading order.

#### Scenario: DocumentAIParser satisfies DocumentProcessor Protocol

- **WHEN** `DocumentAIParser` is instantiated with valid configuration
- **THEN** it SHALL be assignable to a variable typed as `DocumentProcessor`
- **AND** it SHALL expose an async `parse_and_chunk(content, filename, source_type)` method returning `list[ChunkData]`

#### Scenario: Parse a PDF through Document AI

- **WHEN** `parse_and_chunk()` is called with bytes of a multi-page PDF
- **THEN** the result SHALL be a non-empty list of `ChunkData` instances
- **AND** each `ChunkData` SHALL contain `text_content` (non-empty string), `token_count` (positive integer), `chunk_index` (zero-based sequential integer), and anchor metadata fields

#### Scenario: Empty document produces no chunks

- **WHEN** `parse_and_chunk()` is called with a document that Document AI returns no text content for
- **THEN** the result SHALL be an empty list

---

### Requirement: Document AI output normalization to ChunkData contract

The `DocumentAIParser` SHALL normalize the structured response from Google Cloud Document AI into the `ChunkData` contract. The normalization SHALL extract `text_content` from Document AI text blocks, compute `token_count` using the same character-based estimation as `LightweightParser` (chars / CHARS_PER_TOKEN), assign sequential zero-based `chunk_index` values, extract `anchor_page` from Document AI page metadata (1-based), extract `anchor_chapter` from detected top-level headings, and extract `anchor_section` from detected sub-headings. The `anchor_timecode` field SHALL always be `None`. Provider-specific response shapes from Document AI MUST NOT leak into domain models or retrieval logic.

#### Scenario: Anchor page extracted from Document AI page metadata

- **WHEN** Document AI returns content associated with page 3 of a PDF
- **THEN** the corresponding `ChunkData` instances SHALL have `anchor_page` set to `3`

#### Scenario: Headings extracted as chapter and section anchors

- **WHEN** Document AI detects a top-level heading "Introduction" and a sub-heading "Background"
- **THEN** chunks under "Introduction" SHALL have `anchor_chapter` set to `"Introduction"`
- **AND** chunks under "Background" SHALL have `anchor_section` set to `"Background"`

#### Scenario: Token count computed consistently

- **WHEN** a `ChunkData` is produced with `text_content` of 300 characters
- **THEN** `token_count` SHALL be computed using the same `CHARS_PER_TOKEN` constant used by `LightweightParser` and `TextChunker`

#### Scenario: Chunk indices are sequential

- **WHEN** `DocumentAIParser` produces multiple chunks from a document
- **THEN** `chunk_index` values SHALL be sequential starting from 0 (0, 1, 2, ...)

---

### Requirement: TextChunker reuse in DocumentAIParser

The `DocumentAIParser` SHALL use the shared `TextChunker` (extracted from `LightweightParser._chunk_blocks`) to chunk the text blocks extracted from Document AI output. The `DocumentAIParser` SHALL convert Document AI's structured response into `ParsedBlock` instances and pass them to `TextChunker.chunk_blocks()`. This ensures chunking behavior (token limits, block merging, anchor preservation) is identical across Path B and Path C.

#### Scenario: DocumentAIParser delegates chunking to TextChunker

- **WHEN** `parse_and_chunk()` is called on `DocumentAIParser`
- **THEN** the extracted text blocks SHALL be converted to `ParsedBlock` instances
- **AND** `TextChunker.chunk_blocks()` SHALL be called with those blocks
- **AND** the returned `list[ChunkData]` SHALL come from `TextChunker`

#### Scenario: Chunking respects max_tokens setting

- **WHEN** `DocumentAIParser` processes a document with large text blocks
- **THEN** every resulting `ChunkData` SHALL have `token_count` less than or equal to the configured `chunk_max_tokens`

---

### Requirement: Retry policy for Document AI API calls

The `DocumentAIParser` SHALL wrap Document AI API calls with tenacity retry logic. The retry policy SHALL allow a maximum of 3 attempts with exponential backoff (1s, 2s, 8s). The retry SHALL trigger only on transient gRPC errors: `ServiceUnavailable` and `DeadlineExceeded`. On retry exhaustion, the exception SHALL propagate to the caller, causing the ingestion task to transition to `failed` status. Non-transient errors (e.g., `InvalidArgument`, `PermissionDenied`) SHALL NOT be retried.

#### Scenario: Transient ServiceUnavailable is retried

- **WHEN** the Document AI API returns `ServiceUnavailable` on the first attempt and succeeds on the second
- **THEN** the `parse_and_chunk()` call SHALL succeed without raising an exception

#### Scenario: Transient DeadlineExceeded is retried

- **WHEN** the Document AI API returns `DeadlineExceeded` on the first two attempts and succeeds on the third
- **THEN** the `parse_and_chunk()` call SHALL succeed without raising an exception

#### Scenario: Persistent transient failure exhausts retries

- **WHEN** the Document AI API returns `ServiceUnavailable` on all 3 attempts
- **THEN** `parse_and_chunk()` SHALL raise an exception after exhausting retries

#### Scenario: Non-transient error is not retried

- **WHEN** the Document AI API returns `InvalidArgument` on the first attempt
- **THEN** the exception SHALL propagate immediately without retry

---

### Requirement: Graceful disable when Document AI is not configured

If the `DOCUMENT_AI_PROJECT_ID` environment variable is not set, Document AI SHALL be considered unconfigured and Path C SHALL be unavailable. The `DocumentAIParser` instance SHALL be `None` in the worker context when Document AI is not configured. Warning ownership is split by detection source:

- **Explicit user hint:** The path router SHALL log the warning when `processing_hint="external"` cannot be honored because Document AI is not configured. The router owns this warning because it makes the fallback decision.
- **Scan auto-detection:** The path_b handler SHALL log the warning when scan detection triggers but Document AI is not configured. The handler owns this warning because scan detection happens after parsing, inside the handler.

This preserves the cheap-VPS-first constraint: the base installation works without Google Cloud entirely.

#### Scenario: Document AI not configured disables Path C

- **WHEN** `DOCUMENT_AI_PROJECT_ID` is not set in the environment
- **THEN** `DocumentAIParser` SHALL NOT be instantiated
- **AND** the `document_ai_parser` field in `PipelineServices` SHALL be `None`
- **AND** Path C SHALL be unavailable for all documents

#### Scenario: Scan-detected PDF falls back to Path B when unconfigured

- **WHEN** a PDF has low characters per page (suspected scan)
- **AND** Document AI is not configured
- **THEN** the document SHALL be processed via Path B (best-effort)
- **AND** a warning SHALL be logged by the path_b handler indicating that Path C is unavailable

#### Scenario: User hint "external" falls back to Path B when unconfigured

- **WHEN** a user uploads a PDF with `processing_hint="external"`
- **AND** Document AI is not configured
- **THEN** the router SHALL return `PATH_B`
- **AND** a warning SHALL be logged by the router indicating that Document AI is not configured

---

### Requirement: Document AI configuration via environment variables

The `DocumentAIParser` SHALL be configured via the following environment variables:

| Variable                   | Default    | Required    | Description                                                             |
| -------------------------- | ---------- | ----------- | ----------------------------------------------------------------------- |
| `DOCUMENT_AI_PROJECT_ID`   | -- (unset) | Conditional | Google Cloud project ID. Must be set together with `DOCUMENT_AI_PROCESSOR_ID` |
| `DOCUMENT_AI_LOCATION`     | `us`       | No          | Document AI processor region                                            |
| `DOCUMENT_AI_PROCESSOR_ID` | -- (unset) | Conditional | Layout Parser processor ID. Must be set together with `DOCUMENT_AI_PROJECT_ID` |

If either `DOCUMENT_AI_PROJECT_ID` or `DOCUMENT_AI_PROCESSOR_ID` is set without the other, the system SHALL raise a configuration error at startup. The `google-cloud-documentai` package SHALL be the only Document AI dependency -- no local ML runtimes.

#### Scenario: Valid configuration with all variables set

- **WHEN** `DOCUMENT_AI_PROJECT_ID`, `DOCUMENT_AI_LOCATION`, and `DOCUMENT_AI_PROCESSOR_ID` are all set
- **THEN** `DocumentAIParser` SHALL be instantiated successfully
- **AND** it SHALL use the configured processor for all API calls

#### Scenario: Default location used when not specified

- **WHEN** `DOCUMENT_AI_PROJECT_ID` and `DOCUMENT_AI_PROCESSOR_ID` are set
- **AND** `DOCUMENT_AI_LOCATION` is not set
- **THEN** the location SHALL default to `"us"`

#### Scenario: Missing processor ID with project ID raises startup error

- **WHEN** `DOCUMENT_AI_PROJECT_ID` is set
- **AND** `DOCUMENT_AI_PROCESSOR_ID` is not set
- **THEN** the system SHALL raise a configuration error during startup

#### Scenario: Missing project ID with processor ID raises startup error

- **WHEN** `DOCUMENT_AI_PROCESSOR_ID` is set
- **AND** `DOCUMENT_AI_PROJECT_ID` is not set
- **THEN** the system SHALL raise a configuration error during startup

---

### Requirement: Path C handler follows existing handler pattern

The system SHALL provide a `handle_path_c()` function at `app/workers/tasks/handlers/path_c.py` that follows the same pattern as `handle_path_a()` and `handle_path_b()`. The handler receives `file_bytes` already downloaded by the ingestion orchestrator (`_run_ingestion_pipeline`) — it does NOT download the file itself. The handler SHALL execute the following stages in sequence:

1. Call `DocumentAIParser.parse_and_chunk(file_bytes, filename, source_type)` to get `list[ChunkData]`
2. Save chunks to PostgreSQL with status `PENDING` (Tx 1)
3. Generate embeddings: interactive Gemini Embedding API if chunks <= `batch_embed_chunk_threshold` (50), otherwise Gemini Batch Embedding API via `BatchOrchestrator`
4. Upsert into Qdrant with `snapshot_id` of current draft
5. Update chunk statuses to `INDEXED` and finalize (Tx 2)
6. Set `DocumentVersion.processing_path` to `PATH_C`

The handler SHALL own its own error cleanup (same as Path A and Path B handlers).

#### Scenario: Successful Path C ingestion end-to-end

- **WHEN** a PDF is routed to Path C and Document AI is configured
- **THEN** the handler SHALL send the file bytes to Document AI, chunk the result, embed, upsert to Qdrant, and finalize
- **AND** `DocumentVersion.processing_path` SHALL be `PATH_C`
- **AND** chunk statuses SHALL transition from `PENDING` to `INDEXED`
- **AND** the `result_metadata["processing_path"]` SHALL be `"path_c"`

#### Scenario: Path C handler returns BatchSubmittedResult for large documents

- **WHEN** Document AI returns more than `batch_embed_chunk_threshold` chunks
- **THEN** the handler SHALL return a `BatchSubmittedResult` early
- **AND** a `BatchJob` SHALL be created and submitted to Gemini Batch API
- **AND** the Source SHALL remain in `PROCESSING` status

#### Scenario: Path C handler failure after Tx 1 triggers cleanup

- **WHEN** the handler fails after chunks have been committed to PostgreSQL (Tx 1)
- **THEN** the handler SHALL call `mark_persisted_records_failed()`
- **AND** DocumentVersion, Chunks, Document, and Source SHALL be marked as FAILED
- **AND** the handler SHALL attempt compensating Qdrant point deletion

---

### Requirement: Scan detection reroutes from Path B to Path C

When the Path B handler processes a PDF and pypdf extracts text, the handler SHALL compute the average characters per page. If the average characters per page is below `PATH_C_MIN_CHARS_PER_PAGE` (default 50), the document is a suspected scan and SHALL be rerouted to Path C. The scan detection happens in the Path B handler (not the router) because text scarcity is only visible after pypdf extraction attempt. If Document AI is not configured, Path B SHALL continue processing with a warning logged.

#### Scenario: Low text PDF rerouted to Path C

- **WHEN** a PDF is being processed via Path B
- **AND** pypdf extraction yields an average of 30 characters per page
- **AND** `PATH_C_MIN_CHARS_PER_PAGE` is 50
- **AND** Document AI is configured
- **THEN** the Path B handler SHALL delegate to the Path C handler
- **AND** `DocumentVersion.processing_path` SHALL be `PATH_C`

#### Scenario: Normal text PDF continues on Path B

- **WHEN** a PDF is being processed via Path B
- **AND** pypdf extraction yields an average of 200 characters per page
- **THEN** the Path B handler SHALL continue processing normally via Path B

#### Scenario: Scan detected but Document AI not configured

- **WHEN** a PDF is being processed via Path B
- **AND** pypdf extraction yields an average of 10 characters per page
- **AND** Document AI is not configured
- **THEN** the Path B handler SHALL continue processing via Path B (best-effort)
- **AND** a warning SHALL be logged indicating that scan was detected but Path C is unavailable

#### Scenario: Configurable scan detection threshold

- **WHEN** `PATH_C_MIN_CHARS_PER_PAGE` is set to 100
- **AND** a PDF has an average of 75 characters per page
- **THEN** the document SHALL be rerouted to Path C (if configured)

---

### Requirement: Shared embed-and-index logic between Path B and Path C

Steps 3-6 of the Path C handler (persist chunks, generate embeddings, upsert to Qdrant, finalize) are identical to the Path B handler. A shared function `embed_and_index_chunks()` SHALL be extracted that both `handle_path_b()` and `handle_path_c()` call. This avoids duplicating embedding, indexing, and finalization logic.

#### Scenario: Path B and Path C use same embed-and-index logic

- **WHEN** a document is processed via Path B
- **AND** another document is processed via Path C
- **THEN** both handlers SHALL call the same shared `embed_and_index_chunks()` function
- **AND** the resulting Qdrant payloads SHALL have identical schema

#### Scenario: Chunk contract is identical across all paths

- **WHEN** Path A, Path B, and Path C each produce chunks
- **THEN** all chunks SHALL conform to the `ChunkData` contract
- **AND** Qdrant payload schema SHALL be identical regardless of processing path
