## ADDED Requirements

### Requirement: DoclingParser service for document parsing and chunking

The system SHALL provide a `DoclingParser` service at `app/services/docling_parser.py` that accepts raw file bytes, a filename, and a source type, and returns a list of `ChunkData` instances. The service SHALL use Docling `DocumentConverter` for parsing and `HybridChunker` for structure-aware chunking. Docling is CPU-bound; all calls to Docling SHALL be wrapped in `asyncio.to_thread()` to avoid blocking the event loop. The service SHALL support MD and TXT source types in S2-02 scope.

#### Scenario: Parse a Markdown file with headings into chunks

- **WHEN** `parse_and_chunk()` is called with bytes of a Markdown file containing multiple headings and paragraphs
- **THEN** the result SHALL be a list of `ChunkData` instances
- **AND** each `ChunkData` SHALL contain `text_content` (non-empty string), `token_count` (positive integer), and anchor metadata fields (`anchor_page`, `anchor_chapter`, `anchor_section`)

#### Scenario: Parse a plain text file

- **WHEN** `parse_and_chunk()` is called with bytes of a `.txt` file
- **THEN** the result SHALL be a non-empty list of `ChunkData` instances with `text_content` populated

#### Scenario: Empty document produces no chunks

- **WHEN** `parse_and_chunk()` is called with bytes that contain no textual content
- **THEN** the result SHALL be an empty list

#### Scenario: Single-paragraph document produces one chunk

- **WHEN** `parse_and_chunk()` is called with a document containing a single short paragraph
- **THEN** the result SHALL contain exactly one `ChunkData` instance

---

### Requirement: HybridChunker configuration

The `HybridChunker` SHALL be configured with `max_tokens` sourced from the `chunk_max_tokens` setting (default 1024). The chunker SHALL preserve heading hierarchy and section metadata from the Docling parse result. Chunks SHALL NOT exceed the configured `max_tokens` limit. Consecutive small sections under the same heading SHALL be merged into a single chunk when they fit within the token limit.

#### Scenario: No chunk exceeds the configured max_tokens

- **WHEN** a document is chunked with `chunk_max_tokens` set to 1024
- **THEN** every `ChunkData` in the result SHALL have `token_count` less than or equal to 1024

#### Scenario: Chunk max_tokens is configurable

- **WHEN** `chunk_max_tokens` is changed from 1024 to 512 in Settings
- **THEN** chunking SHALL use 512 as the maximum token limit

---

### Requirement: ChunkData dataclass

The system SHALL define a `ChunkData` dataclass with the following fields: `text_content` (str), `token_count` (int), `chunk_index` (int), `anchor_page` (int or None), `anchor_chapter` (str or None), `anchor_section` (str or None). The `chunk_index` field SHALL be a zero-based sequential index assigned by DoclingParser. This dataclass is the contract between DoclingParser and downstream pipeline stages (including the Qdrant payload where `chunk_index` is required).

#### Scenario: ChunkData fields are accessible

- **WHEN** a `ChunkData` instance is created with all fields
- **THEN** all fields SHALL be accessible as typed attributes
- **AND** `chunk_index` SHALL be an integer ≥ 0

#### Scenario: Chunk indices are sequential

- **WHEN** DoclingParser produces multiple chunks from a document
- **THEN** chunk indices SHALL be sequential starting from 0 (0, 1, 2, ...)

---

### Requirement: EmbeddingService for dense vector generation

The system SHALL provide an `EmbeddingService` at `app/services/embedding.py` that generates dense embeddings via the Google GenAI SDK (`google-genai`). The service SHALL accept a list of texts and a task type, and return a list of float vectors. The default task type for indexing SHALL be `RETRIEVAL_DOCUMENT`. The output dimensionality SHALL be controlled by the `embedding_dimensions` setting (default 3072). The embedding model SHALL be controlled by the `embedding_model` setting.

#### Scenario: Generate embeddings for a list of texts

- **WHEN** `embed_texts()` is called with a list of 5 text strings
- **THEN** the result SHALL be a list of 5 float vectors
- **AND** each vector SHALL have length equal to `embedding_dimensions`

#### Scenario: Task type is passed to the GenAI SDK

- **WHEN** `embed_texts()` is called with `task_type="RETRIEVAL_DOCUMENT"`
- **THEN** the underlying GenAI SDK call SHALL receive `RETRIEVAL_DOCUMENT` as the task type parameter

---

### Requirement: Batch embedding strategy

The `EmbeddingService` SHALL batch texts into groups of up to `embedding_batch_size` (default 100) texts per API call. Each batch SHALL be sent as a single HTTP request to the Gemini Embedding API. The service SHALL concatenate results from all batches into a single flat list preserving input order.

#### Scenario: Texts are batched correctly

- **WHEN** `embed_texts()` is called with 250 texts and `embedding_batch_size` is 100
- **THEN** the service SHALL make exactly 3 API calls (100 + 100 + 50 texts)
- **AND** the returned list SHALL contain exactly 250 vectors in the original input order

#### Scenario: Single text does not create unnecessary batching overhead

- **WHEN** `embed_texts()` is called with 1 text
- **THEN** the service SHALL make exactly 1 API call

---

### Requirement: Tenacity retry on embedding API calls

Each batch embedding API call SHALL be wrapped with tenacity retry. The retry SHALL trigger on HTTP 429 (rate limit) and 5xx errors. The retry strategy SHALL use exponential backoff with a maximum of 3 attempts. Docling parse calls SHALL NOT be retried (deterministic failures do not benefit from retry).

#### Scenario: Transient 429 error is retried

- **WHEN** the Gemini API returns a 429 error on the first attempt and succeeds on the second
- **THEN** the embedding call SHALL succeed without raising an exception

#### Scenario: Persistent failure after max retries raises exception

- **WHEN** the Gemini API returns 5xx on all 3 attempts
- **THEN** the embedding call SHALL raise an exception after exhausting retries

#### Scenario: Docling parse failure is not retried

- **WHEN** Docling `DocumentConverter` raises an exception during parsing
- **THEN** the exception SHALL propagate immediately without retry

---

### Requirement: StorageService.download method

The existing `StorageService` SHALL be extended with a `download(object_key: str) -> bytes` method that retrieves file content from MinIO. The download SHALL be wrapped in `asyncio.to_thread()` since the MinIO SDK is synchronous.

#### Scenario: Download returns file bytes

- **WHEN** `download()` is called with a valid object key
- **THEN** the method SHALL return the file content as bytes

#### Scenario: Download of non-existent key raises exception

- **WHEN** `download()` is called with an object key that does not exist in MinIO
- **THEN** the method SHALL raise an exception

---

### Requirement: Pipeline orchestration in the worker task

The ingestion worker task (`app/workers/tasks/ingestion.py`) SHALL replace the noop handler with a real pipeline that executes these stages in sequence: (1) Download source file from MinIO, (2) Parse and chunk via DoclingParser, (3) Persist draft snapshot + Document + DocumentVersion + Chunk records in PostgreSQL (Tx 1), (4) Generate embeddings via EmbeddingService, (5) Upsert vectors to Qdrant via QdrantService, (6) Finalize statuses and create EmbeddingProfile (Tx 2). The worker task IS the orchestrator; there SHALL NOT be a separate Pipeline abstraction class.

#### Scenario: Successful end-to-end pipeline execution

- **WHEN** the ingestion task processes a valid source with status PENDING
- **THEN** the Source status SHALL transition PENDING -> PROCESSING -> READY
- **AND** a Document record SHALL be created with status READY
- **AND** a DocumentVersion record SHALL be created with `version_number=1`, `processing_path=PATH_B`, status READY
- **AND** Chunk records SHALL be created with status INDEXED
- **AND** vectors SHALL be upserted to Qdrant
- **AND** an EmbeddingProfile record SHALL be created
- **AND** the BackgroundTask SHALL have status COMPLETE, progress 100, and `result_metadata` populated

#### Scenario: Pipeline creates Document and DocumentVersion during ingestion

- **WHEN** the pipeline reaches Stage 3 (Persist)
- **THEN** a Document record SHALL be created with `source_id` referencing the source and status PROCESSING
- **AND** a DocumentVersion record SHALL be created with `document_id` referencing the document, `version_number=1`, and `processing_path=PATH_B`
- **AND** Chunk records SHALL be bulk-inserted with status PENDING, linked to the DocumentVersion and snapshot

---

### Requirement: Two-transaction boundary

The pipeline SHALL use two distinct transaction scopes. Tx 1 (Stage 3) SHALL persist the draft snapshot, Document, DocumentVersion, and Chunk records, and COMMIT before any external API calls. Tx 2 (Stage 6) SHALL update Chunk statuses to INDEXED, update DocumentVersion/Document/Source to READY, create the EmbeddingProfile, and mark the task COMPLETE. Tx 2 SHALL only execute after successful Qdrant upsert.

#### Scenario: Tx 1 commits before Gemini API call

- **WHEN** the pipeline reaches Stage 4 (Embed)
- **THEN** all Chunk records from Stage 3 SHALL already be committed to PostgreSQL
- **AND** they SHALL be queryable in a separate database session

#### Scenario: Tx 2 only executes after successful Qdrant upsert

- **WHEN** the Qdrant upsert in Stage 5 succeeds
- **THEN** Tx 2 SHALL execute and commit
- **WHEN** the Qdrant upsert fails
- **THEN** Tx 2 SHALL NOT execute

---

### Requirement: Progress tracking through pipeline stages

The worker task SHALL update `BackgroundTask.progress` at each stage boundary: Stage 1 Download (0-10%), Stage 2 Parse+Chunk (10-40%), Stage 3 Persist (40-50%), Stage 4 Embed (50-85%), Stage 5 Index (85-95%), Stage 6 Finalize (95-100%).

#### Scenario: Progress is updated at stage boundaries

- **WHEN** the pipeline completes Stage 2 (Parse+Chunk)
- **THEN** `BackgroundTask.progress` SHALL be at least 40
- **WHEN** the pipeline completes all stages
- **THEN** `BackgroundTask.progress` SHALL be 100

---

### Requirement: All-or-nothing error handling with failure cleanup

On any failure after Tx 1 has committed, the pipeline SHALL execute a recovery transaction that marks the DocumentVersion, all associated Chunks, and the Document as FAILED. The Source SHALL be marked FAILED. The BackgroundTask SHALL be marked FAILED with `error_message` populated. No partial data SHALL exist in Qdrant (vectors are upserted only after ALL embeddings succeed). Failed records in PostgreSQL are NOT deleted; they serve as audit trail.

#### Scenario: Failure during embedding marks all records as FAILED

- **WHEN** the Gemini embedding call fails after Tx 1 has committed Chunk records
- **THEN** the DocumentVersion status SHALL be FAILED
- **AND** all Chunk records for this version SHALL have status FAILED
- **AND** the Document status SHALL be FAILED
- **AND** the Source status SHALL be FAILED
- **AND** no vectors SHALL exist in Qdrant for these chunks

#### Scenario: Failure before Tx 1 leaves no orphaned records

- **WHEN** the pipeline fails during Stage 1 (Download) or Stage 2 (Parse)
- **THEN** no Document, DocumentVersion, or Chunk records SHALL exist in PostgreSQL
- **AND** the Source and BackgroundTask SHALL be marked FAILED

#### Scenario: Failed records are preserved for audit

- **WHEN** ingestion fails and records are marked FAILED
- **THEN** the DocumentVersion and Chunk records SHALL remain in PostgreSQL (not deleted)

---

### Requirement: Result metadata on successful completion

On success, the BackgroundTask `result_metadata` SHALL contain: `chunk_count` (int), `embedding_model` (string), `embedding_dimensions` (int), `processing_path` (string, value "path_b"), `snapshot_id` (UUID string), `document_id` (UUID string), `document_version_id` (UUID string), `token_count_total` (int, sum of all chunk token counts).

#### Scenario: result_metadata contains all required fields

- **WHEN** the ingestion task completes successfully
- **THEN** `result_metadata` SHALL contain all 8 specified fields with correct types and values

---

### Requirement: EmbeddingProfile audit record

The pipeline SHALL create one `EmbeddingProfile` record per successful ingestion pass during Tx 2. The record SHALL capture the embedding model, dimensions, task type, and pipeline metadata. EmbeddingProfile records SHALL never be updated; each ingestion creates a new record for audit trail.

#### Scenario: EmbeddingProfile created on success

- **WHEN** the ingestion pipeline completes successfully
- **THEN** exactly one new EmbeddingProfile record SHALL exist in PostgreSQL
- **AND** its `model_name` field SHALL match `settings.embedding_model`
- **AND** its `dimensions` field SHALL match `settings.embedding_dimensions`

---

### Requirement: Worker service initialization

The arq worker `on_startup` hook SHALL initialize and store in the worker context: `StorageService` (MinIO client), `QdrantService` (async Qdrant client), `EmbeddingService` (GenAI client), and `settings`. The `on_startup` hook SHALL call `qdrant_service.ensure_collection()` (idempotent). The `on_shutdown` hook SHALL close the Qdrant client connection.

#### Scenario: All services available in worker context after startup

- **WHEN** the arq worker completes startup
- **THEN** `ctx["storage_service"]`, `ctx["qdrant_service"]`, `ctx["embedding_service"]`, and `ctx["settings"]` SHALL all be present and initialized

#### Scenario: Qdrant collection ensured on startup

- **WHEN** the arq worker starts
- **THEN** `ensure_collection()` SHALL be called exactly once

#### Scenario: Qdrant client closed on shutdown

- **WHEN** the arq worker shuts down
- **THEN** the Qdrant client connection SHALL be closed

---

### Requirement: Source language persistence in pipeline

The pipeline SHALL use the `language` value from the Source record (persisted at upload time) for the Qdrant payload `language` field. If the Source has no language set (NULL), the system-wide `bm25_language` setting SHALL be used as the default. This ensures every chunk in Qdrant has a language value for future BM25 sparse vector indexing (S3-02).

#### Scenario: Source with explicit language uses that value

- **WHEN** a Source has `language="russian"` and the pipeline indexes its chunks
- **THEN** the Qdrant payload `language` field for each chunk SHALL be `"russian"`

#### Scenario: Source without language falls back to system default

- **WHEN** a Source has `language=NULL` and `bm25_language` is `"english"`
- **THEN** the Qdrant payload `language` field for each chunk SHALL be `"english"`

---

## Test Coverage

### CI tests (deterministic, mocked external services)

The following stable behavior MUST be covered by CI tests before archive:

- **DoclingParser unit tests**: mock Docling DocumentConverter and HybridChunker. Verify chunk extraction, anchor metadata mapping, token counting. Cover edge cases: empty document, single-paragraph document, document with heading hierarchy.
- **EmbeddingService unit tests**: mock GenAI SDK. Verify batching logic (texts split into groups of `embedding_batch_size`), retry behavior on 429/5xx, dimension validation.
- **Pipeline orchestration unit tests**: mock all services (DoclingParser, EmbeddingService, QdrantService, StorageService, SnapshotService). Verify correct call sequence, progress updates, status transitions for Source/Document/DocumentVersion/Chunk, error propagation and failure cleanup, draft snapshot auto-creation, result_metadata population.
- **Integration tests with real PG**: run the pipeline with mocked GenAI and real Docling (local library for MD/TXT). Verify all PG records are created with correct statuses, relationships, and field values.

### Evals (non-CI, real providers)

- Embedding quality evaluation with real Gemini Embedding 2 calls is out of scope for CI. Manual verification covers: upload MD file, verify chunks in PG, verify vectors in Qdrant, vector search returns results.
