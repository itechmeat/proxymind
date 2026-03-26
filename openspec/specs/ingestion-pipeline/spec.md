## ADDED Requirements

### Requirement: LightweightParser service for document parsing and chunking

The system SHALL provide a `LightweightParser` service at `app/services/lightweight_parser.py` that accepts raw file bytes, a filename, and a source type, and returns a list of `ChunkData` instances. The service SHALL implement the local lightweight parsing path for `MD`, `TXT`, `PDF`, `DOCX`, and `HTML` sources using the existing per-format parsers. CPU-bound parsing work SHALL be wrapped in `asyncio.to_thread()` to avoid blocking the event loop. The `LightweightParser` SHALL satisfy the shared `DocumentProcessor` contract used by the ingestion pipeline.

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

### Requirement: TextChunker configuration

The shared `TextChunker` SHALL be configured with `max_tokens` sourced from the `chunk_max_tokens` setting (default 1024). The chunker SHALL preserve heading hierarchy and section metadata from parsed blocks. Chunks SHALL NOT exceed the configured `max_tokens` limit. Consecutive small sections under the same heading SHALL be merged into a single chunk when they fit within the token limit, and a heading change SHALL flush the current chunk boundary before the next section starts.

#### Scenario: No chunk exceeds the configured max_tokens

- **WHEN** a document is chunked with `chunk_max_tokens` set to 1024
- **THEN** every `ChunkData` in the result SHALL have `token_count` less than or equal to 1024

#### Scenario: Chunk max_tokens is configurable

- **WHEN** `chunk_max_tokens` is changed from 1024 to 512 in Settings
- **THEN** chunking SHALL use 512 as the maximum token limit

---

### Requirement: ChunkData dataclass

The system SHALL define a `ChunkData` dataclass with the following fields: `text_content` (str), `token_count` (int), `chunk_index` (int), `anchor_page` (int or None), `anchor_chapter` (str or None), `anchor_section` (str or None). The `chunk_index` field SHALL be a zero-based sequential index assigned by the parser and shared `TextChunker`. This dataclass is the contract between `DocumentProcessor` implementations and downstream pipeline stages, including the Qdrant payload where `chunk_index` is required.

#### Scenario: ChunkData fields are accessible

- **WHEN** a `ChunkData` instance is created with all fields
- **THEN** all fields SHALL be accessible as typed attributes
- **AND** `chunk_index` SHALL be an integer ≥ 0

#### Scenario: Chunk indices are sequential

- **WHEN** a `DocumentProcessor` implementation produces multiple chunks from a document
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

Each batch embedding API call SHALL be wrapped with tenacity retry. The retry SHALL trigger on HTTP 429 (rate limit) and 5xx errors. The retry strategy SHALL use exponential backoff with `multiplier=1`, `min=1`, `max=8`, and a maximum of 3 attempts. Lightweight local parse calls SHALL NOT be retried because deterministic parsing failures do not benefit from retry.

#### Scenario: Transient 429 error is retried

- **WHEN** the Gemini API returns a 429 error on the first attempt and succeeds on the second
- **THEN** the embedding call SHALL succeed without raising an exception

#### Scenario: Persistent failure after max retries raises exception

- **WHEN** the Gemini API returns 5xx on all 3 attempts
- **THEN** the embedding call SHALL raise an exception after exhausting retries

#### Scenario: Lightweight parse failure is not retried

- **WHEN** the lightweight local parser raises an exception during parsing
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

**[Modified by S3-06]** The ingestion worker task (`app/workers/tasks/ingestion.py`) SHALL be refactored into a thin orchestrator that dispatches to separate handler modules. The orchestrator SHALL execute these stages in sequence: (1) Download source file from SeaweedFS, (2) Inspect file via `PathRouter.inspect_file()` and determine processing path via `PathRouter.determine_path()`, (3) If path is REJECTED, mark the task FAILED with the rejection reason and return, (4) Dispatch to `handle_path_a()` (`app/workers/tasks/handlers/path_a.py`), `handle_path_b()` (`app/workers/tasks/handlers/path_b.py`), or `handle_path_c()` (`app/workers/tasks/handlers/path_c.py`) based on the routing decision, (5) Finalize statuses and create EmbeddingProfile (Tx 2). Each handler module SHALL own its own stages internally: persist (Tx 1), embed, index. The worker task IS the orchestrator; there SHALL NOT be a separate Pipeline abstraction class.

**[Modified by S2-03]** Stage persist (inside each handler) SHALL use `ensure_draft_or_rebind` to acquire a FOR UPDATE lock on the snapshot row before persisting any chunks. The lock SHALL be held through the chunk insert and transaction commit. If the snapshot is no longer DRAFT (published concurrently), the worker SHALL rebind to a new draft via the same method.

**[Modified by S3-06]** The orchestrator SHALL accept an optional `skip_embedding` flag from the `BackgroundTask.result_metadata`. When `skip_embedding=true`, the handler SHALL parse and chunk the source but SHALL NOT call `embedding_service.embed_texts()`, `embed_file()`, or `qdrant_service.upsert_chunks()`. Chunks SHALL be saved with status `PENDING`. The Source SHALL be set to `READY`. The BackgroundTask SHALL be marked COMPLETE with `result_metadata.skip_embedding = true`.

**[Modified by S3-06]** When `skip_embedding=false` (default) and the chunk count after parsing exceeds `batch_embed_chunk_threshold` (default 50), the handler SHALL return a `BatchSubmittedResult` early — before `_finalize_pipeline_success` is called. The handler SHALL create a `BatchJob` inline via `BatchOrchestrator.create_batch_job_for_threshold()`, then submit to Gemini via `BatchOrchestrator.submit_to_gemini()`. The Source SHALL stay `PROCESSING`, the BackgroundTask SHALL stay `PROCESSING`. The calling code in `_process_task` SHALL detect `BatchSubmittedResult` and exit without finalization. The `poll_active_batches` cron SHALL complete the lifecycle.

**[Modified by S4-06]** The orchestrator SHALL read `processing_hint` from the `BackgroundTask.result_metadata` and pass it to `PathRouter.determine_path()`. The orchestrator SHALL dispatch to `handle_path_c()` when the router returns `PATH_C`. The Path A fallback re-dispatch logic SHALL also consider `PATH_C` as a valid re-dispatch target when Document AI is configured and the document qualifies.

#### Scenario: Orchestrator dispatches to Path C handler

- **WHEN** the orchestrator receives a routing decision of `PATH_C` from PathRouter
- **THEN** the orchestrator SHALL call `handle_path_c()` with the downloaded file bytes and pipeline services
- **AND** the Path C handler SHALL execute the Document AI parsing pipeline

#### Scenario: Orchestrator passes processing_hint to router

- **WHEN** the `BackgroundTask.result_metadata` contains `processing_hint: "external"`
- **THEN** the orchestrator SHALL pass `processing_hint="external"` to `PathRouter.determine_path()`
- **AND** the router SHALL use this hint in its routing decision

#### Scenario: Successful end-to-end pipeline execution via Path C

- **WHEN** the ingestion task processes a PDF routed to Path C with status PENDING
- **THEN** the Source status SHALL transition PENDING -> PROCESSING -> READY
- **AND** a DocumentVersion record SHALL be created with `processing_path=PATH_C`
- **AND** Chunk records SHALL be created with status INDEXED
- **AND** vectors SHALL be upserted to Qdrant
- **AND** an EmbeddingProfile record SHALL be created with `pipeline_version="s4-06-path-c"`
- **AND** the BackgroundTask SHALL have status COMPLETE, progress 100

#### Scenario: Successful end-to-end pipeline execution via Path B

- **WHEN** the ingestion task processes a valid text source (e.g., `.md`, `.txt`, `.docx`, `.html`) with status PENDING
- **THEN** the PathRouter SHALL route the source to Path B
- **AND** the Source status SHALL transition PENDING -> PROCESSING -> READY
- **AND** a Document record SHALL be created with status READY
- **AND** a DocumentVersion record SHALL be created with `version_number=1`, `processing_path=PATH_B`, status READY
- **AND** Chunk records SHALL be created with status INDEXED
- **AND** vectors SHALL be upserted to Qdrant
- **AND** an EmbeddingProfile record SHALL be created with `pipeline_version="s2-02-path-b"`
- **AND** the BackgroundTask SHALL have status COMPLETE, progress 100, and `result_metadata` populated

#### Scenario: Successful end-to-end pipeline execution via Path A

- **WHEN** the ingestion task processes a valid Path A source (e.g., image, short PDF, short audio/video) with status PENDING
- **THEN** the PathRouter SHALL route the source to Path A
- **AND** the Source status SHALL transition PENDING -> PROCESSING -> READY
- **AND** a Document record SHALL be created with status READY
- **AND** a DocumentVersion record SHALL be created with `version_number=1`, `processing_path=PATH_A`, status READY
- **AND** exactly one Chunk record SHALL be created with status INDEXED
- **AND** vectors SHALL be upserted to Qdrant (dense + BM25)
- **AND** an EmbeddingProfile record SHALL be created with `pipeline_version="s3-04-path-a"`
- **AND** the BackgroundTask SHALL have status COMPLETE, progress 100, and `result_metadata` populated

#### Scenario: Orchestrator dispatches to Path B handler for text formats

- **WHEN** the orchestrator receives a routing decision of Path B from PathRouter
- **THEN** the orchestrator SHALL call `handle_path_b()` with the downloaded file bytes and pipeline services
- **AND** the Path B handler SHALL execute the existing lightweight parsing pipeline logic

#### Scenario: Orchestrator dispatches to Path A handler for multimodal formats

- **WHEN** the orchestrator receives a routing decision of Path A from PathRouter
- **THEN** the orchestrator SHALL call `handle_path_a()` with the downloaded file bytes and pipeline services

#### Scenario: Path A fallback is re-dispatched by the orchestrator

- **WHEN** the orchestrator dispatches a PDF source to `handle_path_a()`
- **AND** `handle_path_a()` returns a fallback signal because the extracted text exceeds `path_a_text_threshold_pdf`
- **THEN** the orchestrator SHALL re-dispatch to the correct downstream handler for the same source
- **AND** the downstream target SHALL be `handle_path_b()` for the standard local-text fallback case
- **AND** the downstream target SHALL be `handle_path_c()` when `processing_hint="external"` is active and Document AI is configured
- **AND** the final persisted `DocumentVersion.processing_path` SHALL match the actual downstream handler used
- **AND** the final `result_metadata["processing_path"]` SHALL match the actual downstream handler used

#### Scenario: Orchestrator rejects source when PathRouter returns REJECTED

- **WHEN** the PathRouter returns a REJECTED decision (e.g., audio/video exceeding duration limits)
- **THEN** the orchestrator SHALL mark the Source and BackgroundTask as FAILED
- **AND** the `BackgroundTask.error_message` SHALL contain the rejection reason from PathRouter
- **AND** no Document, DocumentVersion, or Chunk records SHALL be created

#### Scenario: Pipeline creates Document and DocumentVersion during ingestion

- **WHEN** the pipeline reaches the persist stage inside a handler
- **THEN** a Document record SHALL be created with `source_id` referencing the source and status PROCESSING
- **AND** a DocumentVersion record SHALL be created with `document_id` referencing the document, `version_number=1`, and `processing_path` matching the handler's path (PATH_A or PATH_B)
- **AND** Chunk records SHALL be bulk-inserted with status PENDING, linked to the DocumentVersion and snapshot

#### Scenario: Skip-embedding path parses and chunks without embedding

- **WHEN** the ingestion task has `result_metadata.skip_embedding = true`
- **THEN** the handler SHALL parse and chunk the source file
- **AND** chunks SHALL be saved to PostgreSQL with status `PENDING`
- **AND** `embedding_service.embed_texts()` SHALL NOT be called
- **AND** `embed_file()` SHALL NOT be called
- **AND** `qdrant_service.upsert_chunks()` SHALL NOT be called
- **AND** the Source status SHALL be set to `READY`
- **AND** the BackgroundTask SHALL be marked COMPLETE
- **AND** `result_metadata` SHALL contain `skip_embedding: true`

#### Scenario: Skip-embedding also applies to Path A sources

- **WHEN** the ingestion task has `result_metadata.skip_embedding = true`
- **AND** the source is routed to Path A
- **THEN** the handler SHALL extract text content and persist one chunk with status `PENDING`
- **AND** `embed_file()` SHALL NOT be called
- **AND** `qdrant_service.upsert_chunks()` SHALL NOT be called
- **AND** the Source status SHALL be set to `READY`

#### Scenario: Auto-threshold routes large source to Batch API

- **WHEN** the ingestion task has `skip_embedding=false` (default)
- **AND** parsing produces a chunk count exceeding `batch_embed_chunk_threshold`
- **THEN** the handler SHALL return a `BatchSubmittedResult`
- **AND** a `BatchJob` SHALL be created and submitted to Gemini
- **AND** the Source SHALL remain in `PROCESSING` status
- **AND** the BackgroundTask SHALL remain in `PROCESSING` status
- **AND** `_finalize_pipeline_success` SHALL NOT be called

#### Scenario: Below-threshold source uses interactive embedding

- **WHEN** the ingestion task has `skip_embedding=false`
- **AND** parsing produces a chunk count at or below `batch_embed_chunk_threshold`
- **THEN** the handler SHALL proceed with interactive `embed_texts()` and Qdrant upsert as normal

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

**[Modified by S3-04]** On any failure after Tx 1 has committed, the **handler** (not the orchestrator) SHALL execute a recovery transaction that marks the DocumentVersion, all associated Chunks, and the Document as FAILED. Each handler SHALL wrap its post-Tx-1 logic in a try/except block and call `mark_persisted_records_failed()` on failure. The Source SHALL be marked FAILED. The BackgroundTask SHALL be marked FAILED with `error_message` populated. Qdrant points SHALL use stable deterministic IDs derived from `chunk_id`, so re-upserts remain idempotent. If the worker cannot prove whether a Qdrant upsert wrote data, it SHALL attempt compensating deletion by those same `chunk_id` values before final failure handling. Failed records in PostgreSQL are NOT deleted; they serve as audit trail.

**[Modified by S4-06]** The Path C handler SHALL follow the same error handling pattern. On failure after Tx 1, the Path C handler SHALL call `mark_persisted_records_failed()` and attempt compensating Qdrant deletion.

#### Scenario: Path C handler failure marks records as FAILED

- **WHEN** the Document AI call or embedding fails after Tx 1 has committed Chunk records in Path C
- **THEN** the Path C handler SHALL catch the exception and call `mark_persisted_records_failed()`
- **AND** the DocumentVersion, Chunks, Document, and Source statuses SHALL be FAILED
- **AND** the BackgroundTask SHALL be FAILED with `error_message` populated

#### Scenario: Failure during embedding marks all records as FAILED

- **WHEN** the Gemini embedding call fails after Tx 1 has committed Chunk records
- **THEN** the handler SHALL catch the exception and call `mark_persisted_records_failed()`
- **AND** the DocumentVersion status SHALL be FAILED
- **AND** all Chunk records for this version SHALL have status FAILED
- **AND** the Document status SHALL be FAILED
- **AND** the Source status SHALL be FAILED
- **AND** no vectors SHALL exist in Qdrant for these chunks

#### Scenario: Failure before Tx 1 leaves no orphaned records

- **WHEN** the pipeline fails during Stage 1 (Download from SeaweedFS) or during handler execution before Tx 1
- **THEN** no Document, DocumentVersion, or Chunk records SHALL exist in PostgreSQL
- **AND** the Source and BackgroundTask SHALL be marked FAILED

#### Scenario: Failed records are preserved for audit

- **WHEN** ingestion fails and records are marked FAILED
- **THEN** the DocumentVersion and Chunk records SHALL remain in PostgreSQL (not deleted)

#### Scenario: Ambiguous Qdrant upsert triggers compensating cleanup

- **WHEN** the Qdrant upsert may have partially succeeded but the worker loses the response or later finalization fails
- **THEN** the handler SHALL attempt to delete the affected Qdrant points by deterministic `chunk_id`
- **AND** a later retry or re-upsert SHALL remain idempotent because the point IDs are stable

#### Scenario: Each handler owns its own cleanup

- **WHEN** the Path A handler fails after Tx 1
- **THEN** the Path A handler itself SHALL execute the failure cleanup (not the orchestrator)
- **AND** cleanup SHALL mark persisted records as FAILED and attempt Qdrant point deletion

- **WHEN** the Path B handler fails after Tx 1
- **THEN** the Path B handler itself SHALL execute the failure cleanup (not the orchestrator)
- **AND** cleanup SHALL mark persisted records as FAILED and attempt Qdrant point deletion

- **WHEN** the Path C handler fails after Tx 1
- **THEN** the Path C handler itself SHALL execute the failure cleanup (not the orchestrator)
- **AND** cleanup SHALL mark persisted records as FAILED and attempt Qdrant point deletion

---

### Requirement: ProcessingPath enum gains PATH_C

**[Added by S4-06]** The `ProcessingPath` enum at `app/db/models/enums.py` SHALL include `PATH_C` as a valid value in addition to existing `PATH_A` and `PATH_B`. An Alembic migration SHALL execute `ALTER TYPE processing_path_enum ADD VALUE IF NOT EXISTS 'path_c'` to add the new value to the PostgreSQL native enum. This migration MUST be non-reversible (PostgreSQL does not support removing enum values).

> Note: The path router's `rejected` outcome is represented as `PathDecision(path=None, rejected=True)`, not as a `ProcessingPath` enum member. `REJECTED` is NOT part of the `ProcessingPath` enum.

#### Scenario: PATH_C is a valid ProcessingPath value

- **WHEN** `ProcessingPath.PATH_C` is referenced in code
- **THEN** it SHALL be a valid enum member with value `"path_c"`

#### Scenario: Database enum includes path_c after migration

- **WHEN** the Alembic migration runs
- **THEN** the `processing_path_enum` type in PostgreSQL SHALL include `"path_c"` as a valid value
- **AND** a `DocumentVersion` record with `processing_path = 'path_c'` SHALL be accepted by the database

---

### Requirement: Result metadata on successful completion

**[Modified by S3-04]** On success, the BackgroundTask `result_metadata` SHALL contain: `chunk_count` (int), `embedding_model` (string), `embedding_dimensions` (int), `processing_path` (string, value `"path_a"`, `"path_b"`, or `"path_c"`), `snapshot_id` (UUID string), `document_id` (UUID string), `document_version_id` (UUID string), `token_count_total` (int, sum of all chunk token counts). `DocumentVersion.processing_path` and `result_metadata["processing_path"]` represent the same outcome in different forms: the database field uses the enum values `PATH_A` / `PATH_B` / `PATH_C`, while `result_metadata["processing_path"]` uses the lowercase string values `"path_a"` / `"path_b"` / `"path_c"`. The `processing_path` value in `result_metadata` SHALL reflect the actual path used: `"path_a"` for Path A handler, `"path_b"` for Path B handler, `"path_c"` for Path C handler. For Path A with threshold fallback to Path B, the value SHALL be `"path_b"` and the persisted `DocumentVersion.processing_path` SHALL be `PATH_B`.

**[Modified by S4-06]** The `processing_path` field now includes `"path_c"` as a valid value. The `processing_path` enum in the database now includes `PATH_C`.

#### Scenario: result_metadata contains processing_path "path_c" for Path C

- **WHEN** the ingestion task completes successfully via Path C
- **THEN** `result_metadata` SHALL contain all 8 specified fields with correct types and values
- **AND** `processing_path` SHALL be `"path_c"`

#### Scenario: result_metadata contains all required fields for Path B

- **WHEN** the ingestion task completes successfully via Path B
- **THEN** `result_metadata` SHALL contain all 8 specified fields with correct types and values
- **AND** `processing_path` SHALL be `"path_b"`

#### Scenario: result_metadata contains all required fields for Path A

- **WHEN** the ingestion task completes successfully via Path A
- **THEN** `result_metadata` SHALL contain all 8 specified fields with correct types and values
- **AND** `processing_path` SHALL be `"path_a"`
- **AND** `chunk_count` SHALL be 1

---

### Requirement: EmbeddingProfile audit record

**[Modified by S3-04]** The pipeline SHALL create one `EmbeddingProfile` record per successful ingestion pass during Tx 2. The record SHALL capture the embedding model, dimensions, task type, and pipeline metadata. The `pipeline_version` field SHALL be parameterized: `"s3-04-path-a"` for Path A ingestion, `"s2-02-path-b"` for Path B ingestion, `"s4-06-path-c"` for Path C ingestion. EmbeddingProfile records SHALL never be updated; each ingestion creates a new record for audit trail. The `_finalize_pipeline_success()` helper SHALL accept `processing_path` and `pipeline_version` parameters from the handler to populate these fields.

**[Modified by S4-06]** Added `"s4-06-path-c"` as the pipeline version for Path C ingestion.

#### Scenario: EmbeddingProfile created on success via Path C

- **WHEN** the ingestion pipeline completes successfully via Path C
- **THEN** exactly one new EmbeddingProfile record SHALL exist in PostgreSQL
- **AND** its `model_name` field SHALL match `settings.embedding_model`
- **AND** its `dimensions` field SHALL match `settings.embedding_dimensions`
- **AND** its `pipeline_version` field SHALL be `"s4-06-path-c"`

#### Scenario: EmbeddingProfile created on success via Path B

- **WHEN** the ingestion pipeline completes successfully via Path B
- **THEN** exactly one new EmbeddingProfile record SHALL exist in PostgreSQL
- **AND** its `model_name` field SHALL match `settings.embedding_model`
- **AND** its `dimensions` field SHALL match `settings.embedding_dimensions`
- **AND** its `pipeline_version` field SHALL be `"s2-02-path-b"`

#### Scenario: EmbeddingProfile created on success via Path A

- **WHEN** the ingestion pipeline completes successfully via Path A
- **THEN** exactly one new EmbeddingProfile record SHALL exist in PostgreSQL
- **AND** its `model_name` field SHALL match `settings.embedding_model`
- **AND** its `dimensions` field SHALL match `settings.embedding_dimensions`
- **AND** its `pipeline_version` field SHALL be `"s3-04-path-a"`

---

### Requirement: Worker service initialization

**[Modified by S3-04]** The arq worker `on_startup` hook SHALL initialize and store in the worker context: a dedicated `storage_http_client` (`httpx.AsyncClient` with `base_url=settings.seaweedfs_filer_url` and `timeout=30.0`), `StorageService` (wrapping the storage HTTP client with `base_path=settings.seaweedfs_sources_path`), `LightweightParser` (renamed from `DoclingParser`), `QdrantService` (async Qdrant client), `EmbeddingService` (GenAI client), `SnapshotService`, `GeminiContentService` (GenAI client for text extraction), `HuggingFaceTokenizer` (for Path A token counting), and `settings`. The worker context SHALL also store Path A configuration values from settings (`path_a_text_threshold_pdf`, `path_a_text_threshold_media`, `path_a_max_pdf_pages`, `path_a_max_audio_duration_sec`, `path_a_max_video_duration_sec`). The `on_startup` hook SHALL call `qdrant_service.ensure_collection()` (idempotent) and `storage_service.ensure_storage_root()` (idempotent). The `on_shutdown` hook SHALL close the Qdrant client connection AND call `await ctx["storage_http_client"].aclose()` to properly clean up the storage HTTP client.

**[Modified by S4-06]** The `on_startup` hook SHALL conditionally instantiate `DocumentAIParser` when `DOCUMENT_AI_PROJECT_ID` is configured. If Document AI is not configured, `document_ai_parser` SHALL be `None` in the worker context. The worker context key SHALL change from `"docling_parser"` to `"document_processor"` (referencing `LightweightParser`). A separate key `"document_ai_parser"` SHALL hold the `DocumentAIParser | None` instance.

A `PipelineServices` dataclass (or equivalent container) SHALL bundle all services and configuration needed by handlers, so that handler signatures remain clean. `PipelineServices` SHALL include: `storage_service`, `document_processor` (type: `DocumentProcessor`, renamed from `docling_parser`), `document_ai_parser` (type: `DocumentAIParser | None`), `qdrant_service`, `embedding_service`, `snapshot_service`, `gemini_content_service`, `tokenizer`, `settings`, and Path A configuration values.

#### Scenario: All services available in worker context after startup

- **WHEN** the arq worker completes startup
- **THEN** `ctx["storage_http_client"]`, `ctx["storage_service"]`, `ctx["document_processor"]`, `ctx["qdrant_service"]`, `ctx["embedding_service"]`, `ctx["snapshot_service"]`, `ctx["gemini_content_service"]`, `ctx["tokenizer"]`, and `ctx["settings"]` SHALL all be present and initialized

#### Scenario: DocumentAIParser conditionally initialized

- **WHEN** the arq worker starts and `DOCUMENT_AI_PROJECT_ID` is configured
- **THEN** `ctx["document_ai_parser"]` SHALL be an initialized `DocumentAIParser` instance

- **WHEN** the arq worker starts and `DOCUMENT_AI_PROJECT_ID` is not configured
- **THEN** `ctx["document_ai_parser"]` SHALL be `None`

#### Scenario: PipelineServices bundles all handler dependencies including Document AI

- **WHEN** a handler is invoked by the orchestrator
- **THEN** the handler SHALL receive a `PipelineServices` instance containing `document_processor`, `document_ai_parser`, and all other required services
- **AND** the handler SHALL NOT access the raw worker context directly

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

### Requirement: PathRouter integration in orchestrator

**[Added by S3-04]** After downloading the source file from SeaweedFS, the orchestrator SHALL call `PathRouter.inspect_file(file_bytes, source_type)` to obtain `FileMetadata`, then call `PathRouter.determine_path(source_type, file_metadata, processing_hint)` to obtain a `PathDecision`. The orchestrator SHALL use the `PathDecision` to dispatch to the appropriate handler or reject the source. PathRouter is responsible only for initial metadata-based routing (page count, duration, source type); token-threshold enforcement remains the responsibility of `handle_path_a()`. If `handle_path_a()` reports a fallback condition, the orchestrator SHALL re-dispatch to the correct downstream handler rather than having the handler call another path directly. The PathRouter is a pure service with no database or network dependencies; it SHALL be called synchronously within the orchestrator.

#### Scenario: Orchestrator calls PathRouter after download

- **WHEN** the orchestrator has downloaded the source file
- **THEN** it SHALL call `inspect_file()` with the file bytes and source type
- **AND** then call `determine_path()` with the source type, file metadata, and effective `processing_hint`
- **AND** use the resulting `PathDecision` to determine the next step

#### Scenario: Explicit external hint routes eligible PDF to Path C

- **WHEN** the orchestrator receives `processing_hint="external"` for a PDF
- **AND** Document AI is configured
- **THEN** `PathRouter.determine_path()` SHALL return `PATH_C`

#### Scenario: External hint falls back when Document AI is unavailable

- **WHEN** the orchestrator receives `processing_hint="external"` for a PDF
- **AND** Document AI is not configured
- **THEN** `PathRouter.determine_path()` SHALL return `PATH_B`
- **AND** the router SHALL log a warning explaining that Path C is unavailable

#### Scenario: PathRouter inspection failure for text formats defaults to Path B

- **WHEN** `inspect_file()` fails to read metadata for a PDF (e.g., corrupt header)
- **THEN** `determine_path()` SHALL return Path B as a conservative fallback

#### Scenario: PathRouter inspection failure for audio/video defaults to Path A

- **WHEN** `inspect_file()` fails to read duration for an audio or video file
- **THEN** `determine_path()` SHALL return Path A (threshold check is the safety net)

#### Scenario: Token threshold checks are evaluated inside Path A

- **WHEN** a source is initially routed to Path A by PathRouter
- **THEN** PathRouter SHALL NOT evaluate `path_a_text_threshold_pdf` or `path_a_text_threshold_media`
- **AND** `handle_path_a()` SHALL evaluate those thresholds after text extraction
- **AND** any fallback to Path B SHALL be signaled back to the orchestrator for re-dispatch

---

### Requirement: Parameterized pipeline_version on EmbeddingProfile

**[Added by S3-04]** The `_finalize_pipeline_success()` function SHALL accept `processing_path` and `pipeline_version` as parameters. Each handler SHALL pass its own values when calling finalization: Path A passes `processing_path=PATH_A` and `pipeline_version="s3-04-path-a"`, Path B passes `processing_path=PATH_B` and `pipeline_version="s2-02-path-b"`, Path C passes `processing_path=PATH_C` and `pipeline_version="s4-06-path-c"`. This ensures the EmbeddingProfile accurately records which pipeline produced the embeddings.

#### Scenario: Path A handler passes correct pipeline_version

- **WHEN** the Path A handler completes successfully and calls finalization
- **THEN** it SHALL pass `pipeline_version="s3-04-path-a"` to `_finalize_pipeline_success()`

#### Scenario: Path B handler passes correct pipeline_version

- **WHEN** the Path B handler completes successfully and calls finalization
- **THEN** it SHALL pass `pipeline_version="s2-02-path-b"` to `_finalize_pipeline_success()`

#### Scenario: Path C handler passes correct pipeline_version

- **WHEN** the Path C handler completes successfully and calls finalization
- **THEN** it SHALL pass `pipeline_version="s4-06-path-c"` to `_finalize_pipeline_success()`

---

## Requirements added by S3-06

### Requirement: skip_embedding query parameter on POST /api/admin/sources

**[Added by S3-06]** The `POST /api/admin/sources` endpoint SHALL accept an optional `skip_embedding` query parameter (boolean, default `false`). When `true`, the ingestion task SHALL be created with `result_metadata.skip_embedding = true`. The worker SHALL read this flag and skip the embedding and Qdrant upsert stages. Chunks SHALL be saved with status `PENDING`. The Source SHALL be set to `READY` (parsed and chunked). The BackgroundTask SHALL be marked COMPLETE. This does NOT mean the source is searchable — `PENDING` chunks are never upserted to Qdrant and cannot be returned by vector search. Those chunks SHALL become searchable only through a later embedding lifecycle such as `POST /api/admin/batch-embed`, which creates a separate `BATCH_EMBEDDING` BackgroundTask and transitions the existing chunk rows from `PENDING` to `INDEXED`.

#### Scenario: skip_embedding=true creates task with flag

- **WHEN** `POST /api/admin/sources?skip_embedding=true` is called with a valid file
- **THEN** the created BackgroundTask SHALL have `result_metadata.skip_embedding = true`
- **AND** the response SHALL be the same as a normal upload (source created, task enqueued)

#### Scenario: skip_embedding=false preserves existing behavior

- **WHEN** `POST /api/admin/sources` is called without `skip_embedding` or with `skip_embedding=false`
- **THEN** the BackgroundTask `result_metadata` SHALL NOT include the `skip_embedding` key
- **AND** the ingestion pipeline SHALL proceed with interactive embedding as normal

#### Scenario: skip_embedding source reaches READY without Qdrant entries

- **WHEN** a source is uploaded with `skip_embedding=true` and the worker completes processing
- **THEN** the Source status SHALL be `READY`
- **AND** all chunks SHALL have status `PENDING`
- **AND** no vectors SHALL exist in Qdrant for these chunks

---

### Requirement: SkipEmbeddingResult and BatchSubmittedResult pipeline result types

**[Added by S3-06]** The ingestion pipeline SHALL define two new dataclass result types to signal early returns from handlers. `SkipEmbeddingResult` SHALL indicate that the handler completed parse+chunk but skipped embedding per the `skip_embedding` flag. `BatchSubmittedResult` SHALL indicate that the handler created a BatchJob and submitted to Gemini instead of performing interactive embedding. Both dataclasses SHALL carry the persisted pipeline identifiers needed by the caller: `snapshot_id`, `document_id`, `document_version_id`, `chunk_ids`, `chunk_count`, `token_count_total`, `processing_path`, and `pipeline_version`. The calling code in `_process_task` SHALL detect these result types via `isinstance()` and handle finalization accordingly: `SkipEmbeddingResult` triggers immediate task completion, `BatchSubmittedResult` exits without finalization (cron completes the lifecycle).

#### Scenario: SkipEmbeddingResult triggers task completion

- **WHEN** a handler returns `SkipEmbeddingResult`
- **THEN** `_process_task` SHALL mark the Source as `READY`
- **AND** SHALL mark the BackgroundTask as COMPLETE with progress `100`
- **AND** SHALL populate `result_metadata` with `skip_embedding: true`, `chunk_count`, `processing_path`, `snapshot_id`, `document_id`, `document_version_id`, and `token_count_total`
- **AND** SHALL NOT call `_finalize_pipeline_success`

#### Scenario: BatchSubmittedResult exits without finalization

- **WHEN** a handler returns `BatchSubmittedResult`
- **THEN** `_process_task` SHALL exit without calling `_finalize_pipeline_success`
- **AND** the BackgroundTask SHALL remain in PROCESSING status
- **AND** the Source SHALL remain in PROCESSING status

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
- **Skip-embedding flow**: upload source with `skip_embedding=true` -> worker parses and chunks -> chunks PENDING, source READY, no Qdrant entries, task COMPLETE.
- **Skip-embedding flag propagation**: verify `result_metadata.skip_embedding` is set on BackgroundTask when upload uses `skip_embedding=true`.
- **Skip-embedding applies to Path A**: verify Path A sources skip `embed_file()` and still persist `PENDING` chunks without Qdrant writes.
- **Auto-threshold detection**: mock chunk count above threshold -> handler returns `BatchSubmittedResult`, no interactive embedding, source stays PROCESSING.
- **Batch threshold boundary**: exactly `batch_embed_chunk_threshold` uses interactive embedding, while `threshold + 1` routes to batch submission.
- **BatchJob creation failure after Tx 1**: auto-threshold path marks persisted Document, DocumentVersion, and Chunk rows FAILED if `create_batch_job_for_threshold()` raises after persistence.
- **Skip-embedding survives Path A -> Path B fallback**: verify PDF fallback to Path B keeps chunks `PENDING`, avoids both embedding paths, and completes the original ingestion task.
- **SkipEmbeddingResult handling**: verify `_process_task` marks task COMPLETE on `SkipEmbeddingResult`.
- **BatchSubmittedResult handling**: verify `_process_task` exits without finalization on `BatchSubmittedResult`.
- **Existing pipeline tests unaffected**: all existing ingestion pipeline tests SHALL continue to pass without modification.

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

---

## Requirements added by S3-05

### Requirement: Source status guard in ingestion worker

**[Added by S3-05]** The ingestion worker SHALL check the source's `status` inside `_process_task()`, after loading the `BackgroundTask` and `Source` rows and before calling `_load_pipeline_services()`. The guard only decides whether processing may continue; it does not add a separate transition path outside `_process_task()`. For non-deleted sources, `_process_task()` continues with the existing worker lifecycle: `BackgroundTask` transitions from `PENDING` to `PROCESSING` to `COMPLETE` or `FAILED`, and `Source` transitions from `PENDING` to `PROCESSING` to `READY` or `FAILED`. If `source.status` is `DELETED`, the worker MUST mark the `BackgroundTask` as FAILED with `error_message` set to `"Source was deleted before processing completed"` and return immediately without executing any pipeline stages. This prevents race conditions where a source is deleted while its ingestion task is in the queue.

#### Scenario: Deleted source is rejected at task start

- **WHEN** the ingestion worker picks up a task for a source with `status = DELETED`
- **THEN** the `BackgroundTask` status SHALL be FAILED
- **AND** `BackgroundTask.error_message` SHALL be "Source was deleted before processing completed"
- **AND** no pipeline stages SHALL execute (no download, no parsing, no embedding, no Qdrant operations)
- **AND** no Document, DocumentVersion, or Chunk records SHALL be created

#### Scenario: Guard runs before pipeline services are loaded

- **WHEN** the ingestion worker enters `_process_task()`
- **THEN** the source status check SHALL occur before `_load_pipeline_services()` is called
- **AND** if the source is DELETED, no service initialization (Qdrant, embedding, etc.) SHALL occur for this task

#### Scenario: Non-deleted source proceeds normally

- **WHEN** the ingestion worker picks up a task for a source with `status = PENDING`
- **THEN** the source status guard SHALL pass
- **AND** the worker SHALL proceed to load pipeline services
- **AND** continue with the normal `_process_task()` transitions (`BackgroundTask -> PROCESSING`, `Source -> PROCESSING`, then final `COMPLETE/FAILED` and `READY/FAILED` outcomes)

#### Scenario: Source deleted between enqueue and processing

- **WHEN** a source is enqueued for ingestion with `status = PENDING`
- **AND** the source is soft-deleted (`status = DELETED`) before the worker picks up the task
- **THEN** the worker SHALL detect `status = DELETED` at the guard check
- **AND** mark the task as FAILED with the descriptive message
- **AND** the source's `status` SHALL remain `DELETED` (not changed to FAILED)
