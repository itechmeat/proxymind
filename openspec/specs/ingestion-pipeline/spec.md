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

Each batch embedding API call SHALL be wrapped with tenacity retry. The retry SHALL trigger on HTTP 429 (rate limit) and 5xx errors. The retry strategy SHALL use exponential backoff with `multiplier=1`, `min=1`, `max=8`, and a maximum of 3 attempts. Docling parse calls SHALL NOT be retried (deterministic failures do not benefit from retry).

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

The existing `StorageService` SHALL provide a `download(object_key: str) -> bytes` method that retrieves file content from SeaweedFS via the Filer HTTP API. The download SHALL be a native async `httpx` GET request to `{base_path}/{object_key}` — no `asyncio.to_thread()` wrapper is needed.

#### Scenario: Download returns file bytes

- **WHEN** `download()` is called with a valid object key
- **THEN** the method SHALL return the file content as bytes via a GET request to the SeaweedFS Filer

#### Scenario: Download of non-existent key raises exception

- **WHEN** `download()` is called with an object key that does not exist in SeaweedFS
- **THEN** the method SHALL raise an `httpx.HTTPStatusError` (non-2xx response from Filer)

---

### Requirement: Pipeline orchestration in the worker task

The ingestion worker task (`app/workers/tasks/ingestion.py`) SHALL replace the noop handler with a real pipeline that executes these stages in sequence: (1) Download source file from SeaweedFS, (2) Parse and chunk via DoclingParser, (3) Persist draft snapshot + Document + DocumentVersion + Chunk records in PostgreSQL (Tx 1), (4) Generate embeddings via EmbeddingService, (5) Upsert vectors to Qdrant via QdrantService, (6) Finalize statuses and create EmbeddingProfile (Tx 2). The worker task IS the orchestrator; there SHALL NOT be a separate Pipeline abstraction class.

**[Modified by S2-03]** Stage 3 (Persist) SHALL use `ensure_draft_or_rebind` to acquire a FOR UPDATE lock on the snapshot row before persisting any chunks. The lock SHALL be held through the chunk insert and transaction commit. If the snapshot is no longer DRAFT (published concurrently), the worker SHALL rebind to a new draft via the same method.

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

### Requirement: Ingestion worker snapshot locking protocol

**[Added by S2-03]** Before persisting chunks in Stage 3 (Tx 1), the ingestion worker MUST call `SnapshotService.ensure_draft_or_rebind(session, snapshot_id, agent_id, knowledge_base_id)` to obtain a FOR UPDATE-locked DRAFT snapshot. The worker SHALL use the returned snapshot's ID for all chunk records. The FOR UPDATE lock SHALL be held through the chunk insert and the transaction commit. The lock is released when the transaction commits.

This protocol serializes the ingestion worker with the publish operation. Since both publish and ingestion acquire FOR UPDATE on the same snapshot row, they cannot execute concurrently. This guarantees:

- If ingestion holds the lock first: chunks are inserted, then publish sees them (and may return 422 if chunks are still PENDING).
- If publish holds the lock first: snapshot transitions to PUBLISHED, then ingestion sees the non-DRAFT status and rebinds to a new draft. The published snapshot remains untouched.

#### Scenario: Ingestion acquires lock before publish

- **WHEN** the ingestion worker acquires the FOR UPDATE lock on a DRAFT snapshot
- **AND** inserts chunks with status PENDING
- **AND** a concurrent publish call attempts to lock the same snapshot
- **THEN** the publish call SHALL block until the ingestion transaction commits
- **AND** after the ingestion transaction commits, publish SHALL see the PENDING chunks and return 422

#### Scenario: Publish completes before ingestion acquires lock

- **WHEN** the publish operation has already transitioned a snapshot from DRAFT to PUBLISHED and committed
- **AND** the ingestion worker then calls `ensure_draft_or_rebind` with that snapshot's ID
- **THEN** the worker SHALL see the snapshot status is PUBLISHED (not DRAFT)
- **AND** the worker SHALL obtain a new DRAFT snapshot via `get_or_create_draft()`
- **AND** chunks SHALL be inserted into the new DRAFT snapshot
- **AND** the published snapshot SHALL have no new chunks added

#### Scenario: Worker uses returned snapshot ID for all chunks

- **WHEN** `ensure_draft_or_rebind` returns a different snapshot (rebind occurred)
- **THEN** all Chunk records and Qdrant points created by this ingestion run SHALL reference the new snapshot's ID, not the original

#### Scenario: Lock held through chunk insert and commit

- **WHEN** the ingestion worker obtains a locked DRAFT snapshot from `ensure_draft_or_rebind`
- **THEN** the FOR UPDATE lock SHALL remain held while chunks are bulk-inserted
- **AND** the lock SHALL remain held until the transaction is committed
- **AND** no concurrent publish can acquire the lock during this window

---

### Requirement: Two-transaction boundary

The pipeline SHALL use two distinct transaction scopes. Tx 1 (Stage 3) SHALL persist the draft snapshot, Document, DocumentVersion, and Chunk records, and COMMIT before any external API calls. **[Modified by S2-03]** Tx 1 SHALL acquire a FOR UPDATE lock on the snapshot row via `ensure_draft_or_rebind` before inserting chunks and hold it through the commit. Tx 2 (Stage 6) SHALL, only after successful Qdrant upsert, update Chunk statuses to INDEXED; update DocumentVersion, Document, and Source to READY; create the EmbeddingProfile; and mark the task COMPLETE.

#### Scenario: Tx 1 commits before Gemini API call

- **WHEN** the pipeline reaches Stage 4 (Embed)
- **THEN** all Chunk records from Stage 3 SHALL already be committed to PostgreSQL
- **AND** they SHALL be queryable in a separate database session

#### Scenario: Tx 2 only executes after successful Qdrant upsert

- **WHEN** the Qdrant upsert in Stage 5 succeeds
- **THEN** Tx 2 SHALL execute and commit
- **WHEN** the Qdrant upsert fails
- **THEN** Tx 2 SHALL NOT execute

#### Scenario: Tx 1 holds FOR UPDATE lock through commit

- **WHEN** the ingestion worker executes Tx 1
- **THEN** the FOR UPDATE lock on the snapshot row SHALL be held from the `ensure_draft_or_rebind` call until the Tx 1 commit
- **AND** the lock SHALL be released after commit, before Stage 4 begins

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

On any failure after Tx 1 has committed, the pipeline SHALL execute a recovery transaction that marks the DocumentVersion, all associated Chunks, and the Document as FAILED. The Source SHALL be marked FAILED. The BackgroundTask SHALL be marked FAILED with `error_message` populated. Qdrant points SHALL use stable deterministic IDs derived from `chunk_id`, so re-upserts remain idempotent. If the worker cannot prove whether a Qdrant upsert wrote data, it SHALL attempt compensating deletion by those same `chunk_id` values before final failure handling. Failed records in PostgreSQL are NOT deleted; they serve as audit trail.

#### Scenario: Failure during embedding marks all records as FAILED

- **WHEN** the Gemini embedding call fails after Tx 1 has committed Chunk records
- **THEN** the DocumentVersion status SHALL be FAILED
- **AND** all Chunk records for this version SHALL have status FAILED
- **AND** the Document status SHALL be FAILED
- **AND** the Source status SHALL be FAILED
- **AND** no vectors SHALL exist in Qdrant for these chunks

#### Scenario: Failure before Tx 1 leaves no orphaned records

- **WHEN** the pipeline fails during Stage 1 (Download from SeaweedFS) or Stage 2 (Parse)
- **THEN** no Document, DocumentVersion, or Chunk records SHALL exist in PostgreSQL
- **AND** the Source and BackgroundTask SHALL be marked FAILED

#### Scenario: Failed records are preserved for audit

- **WHEN** ingestion fails and records are marked FAILED
- **THEN** the DocumentVersion and Chunk records SHALL remain in PostgreSQL (not deleted)

#### Scenario: Ambiguous Qdrant upsert triggers compensating cleanup

- **WHEN** the Qdrant upsert may have partially succeeded but the worker loses the response or later finalization fails
- **THEN** the worker SHALL attempt to delete the affected Qdrant points by deterministic `chunk_id`
- **AND** a later retry or re-upsert SHALL remain idempotent because the point IDs are stable

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

The arq worker `on_startup` hook SHALL initialize and store in the worker context: a dedicated `storage_http_client` (`httpx.AsyncClient` with `base_url=settings.seaweedfs_filer_url` and `timeout=30.0`), `StorageService` (wrapping the storage HTTP client with `base_path=settings.seaweedfs_sources_path`), `DoclingParser`, `QdrantService` (async Qdrant client), `EmbeddingService` (GenAI client), `SnapshotService`, and `settings`. The `on_startup` hook SHALL call `qdrant_service.ensure_collection()` (idempotent) and `storage_service.ensure_storage_root()` (idempotent). The `on_shutdown` hook SHALL close the Qdrant client connection AND call `await ctx["storage_http_client"].aclose()` to properly clean up the storage HTTP client.

The `storage_http_client` is a **new lifecycle responsibility** for the worker. The previous MinIO SDK was synchronous and did not require async cleanup. The worker now MUST manage the async httpx client lifecycle: create in `on_startup`, close in `on_shutdown`.

#### Scenario: All services available in worker context after startup

- **WHEN** the arq worker completes startup
- **THEN** `ctx["storage_http_client"]`, `ctx["storage_service"]`, `ctx["docling_parser"]`, `ctx["qdrant_service"]`, `ctx["embedding_service"]`, `ctx["snapshot_service"]`, and `ctx["settings"]` SHALL all be present and initialized

#### Scenario: Qdrant collection ensured on startup

- **WHEN** the arq worker starts
- **THEN** `ensure_collection()` SHALL be called during startup to verify collection readiness

#### Scenario: Storage root ensured on startup

- **WHEN** the arq worker starts
- **THEN** `ensure_storage_root()` SHALL be called during startup to verify SeaweedFS Filer availability

#### Scenario: Qdrant client closed on shutdown

- **WHEN** the arq worker shuts down
- **THEN** the Qdrant client connection SHALL be closed

#### Scenario: Storage HTTP client closed on shutdown

- **WHEN** the arq worker shuts down
- **THEN** `await ctx["storage_http_client"].aclose()` SHALL be called to release the httpx connection pool

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
- **StorageService unit tests** (`test_storage.py`): use `httpx.MockTransport` to mock HTTP responses. Verify correct HTTP methods (POST for upload/ensure, GET for download, DELETE for delete), URL path construction, path normalization edge cases, content_type forwarding, response body handling, error propagation (non-2xx raises `httpx.HTTPStatusError`).
- **Pipeline orchestration unit tests**: mock all services (DoclingParser, EmbeddingService, QdrantService, StorageService, SnapshotService). Verify correct call sequence, progress updates, status transitions for Source/Document/DocumentVersion/Chunk, error propagation and failure cleanup, draft snapshot auto-creation, result_metadata population.
- **Integration tests with real PG**: run the pipeline with mocked GenAI and real Docling (local library for MD/TXT). Verify all PG records are created with correct statuses, relationships, and field values.
- **Snapshot locking integration tests with real PG** [Added by S2-03]: verify that the ingestion worker calls `ensure_draft_or_rebind` before chunk persistence. Verify that chunks are inserted under the FOR UPDATE lock. Verify the rebind scenario: when the snapshot has been published between `get_or_create_draft` and chunk insert, the worker rebinds to a new draft and the published snapshot receives no new chunks.
- **Worker shutdown test**: verify that the worker `on_shutdown` properly closes both the Qdrant client AND the `storage_http_client` via `aclose()`.

### Evals (non-CI, real providers)

- Embedding quality evaluation with real Gemini Embedding 2 calls is out of scope for CI. Manual verification covers: upload MD file, verify chunks in PG, verify vectors in Qdrant, vector search returns results.

---

## Requirements added by S3-01

### Requirement: Corrupt file contract between parser and worker

When `DoclingParser.parse_and_chunk()` raises an exception due to a corrupt or malformed input file, the ingestion worker SHALL catch the exception and mark the `BackgroundTask` as FAILED with `error_message` containing the exception details. The `Source` record SHALL be marked FAILED. No Document, DocumentVersion, or Chunk records SHALL be created for corrupt files (failure occurs before Tx 1). The worker SHALL NOT retry parsing failures — corrupt input is a deterministic failure.

> **ADDED by S3-01:** This contract was implicit when only MD/TXT were supported (text formats rarely corrupt). With binary formats (PDF, DOCX), corrupt file handling becomes a required explicit contract.

#### Scenario: Corrupt PDF triggers task failure

- **WHEN** the ingestion worker processes a source with a corrupt PDF file
- **AND** `DoclingParser.parse_and_chunk()` raises an exception
- **THEN** the `BackgroundTask` status SHALL be FAILED
- **AND** `BackgroundTask.error_message` SHALL contain a description of the parsing failure
- **AND** the `Source` status SHALL be FAILED
- **AND** no Document, DocumentVersion, or Chunk records SHALL exist for this source

#### Scenario: Corrupt DOCX triggers task failure

- **WHEN** the ingestion worker processes a source with a corrupt DOCX file
- **AND** `DoclingParser.parse_and_chunk()` raises an exception
- **THEN** the `BackgroundTask` status SHALL be FAILED
- **AND** `BackgroundTask.error_message` SHALL contain a description of the parsing failure
- **AND** the `Source` status SHALL be FAILED
- **AND** no Document, DocumentVersion, or Chunk records SHALL exist for this source

#### Scenario: Parsing failure is not retried by the worker

- **WHEN** `DoclingParser.parse_and_chunk()` raises an exception for a corrupt file
- **THEN** the worker SHALL NOT re-enqueue or retry the ingestion task
- **AND** the task SHALL remain in FAILED status as a permanent terminal state

#### Scenario: Worker error message includes exception details

- **WHEN** `DoclingParser` raises an exception with message "Invalid PDF header"
- **THEN** `BackgroundTask.error_message` SHALL contain "Invalid PDF header" or a message that includes the original exception text
