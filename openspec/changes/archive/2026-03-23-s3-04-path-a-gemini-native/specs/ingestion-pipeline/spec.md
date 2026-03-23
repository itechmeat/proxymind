## MODIFIED Requirements

### Requirement: Pipeline orchestration in the worker task

**[Modified by S3-04]** The ingestion worker task (`app/workers/tasks/ingestion.py`) SHALL be refactored into a thin orchestrator that dispatches to separate handler modules. The orchestrator SHALL execute these stages in sequence: (1) Download source file from SeaweedFS, (2) Inspect file via `PathRouter.inspect_file()` and determine processing path via `PathRouter.determine_path()`, (3) If path is REJECTED, mark the task FAILED with the rejection reason and return, (4) Dispatch to `handle_path_a()` (`app/workers/tasks/handlers/path_a.py`) or `handle_path_b()` (`app/workers/tasks/handlers/path_b.py`) based on the routing decision, (5) Finalize statuses and create EmbeddingProfile (Tx 2). Each handler module SHALL own its own stages internally: persist (Tx 1), embed, index. The worker task IS the orchestrator; there SHALL NOT be a separate Pipeline abstraction class.

**[Modified by S2-03]** Stage persist (inside each handler) SHALL use `ensure_draft_or_rebind` to acquire a FOR UPDATE lock on the snapshot row before persisting any chunks. The lock SHALL be held through the chunk insert and transaction commit. If the snapshot is no longer DRAFT (published concurrently), the worker SHALL rebind to a new draft via the same method.

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
- **AND** the Path B handler SHALL execute the existing Docling-based pipeline logic

#### Scenario: Orchestrator dispatches to Path A handler for multimodal formats

- **WHEN** the orchestrator receives a routing decision of Path A from PathRouter
- **THEN** the orchestrator SHALL call `handle_path_a()` with the downloaded file bytes and pipeline services

#### Scenario: Path A fallback is re-dispatched by the orchestrator

- **WHEN** the orchestrator dispatches a PDF source to `handle_path_a()`
- **AND** `handle_path_a()` returns a fallback signal because the extracted text exceeds `path_a_text_threshold_pdf`
- **THEN** the orchestrator SHALL call `handle_path_b()` for the same source
- **AND** the final persisted `DocumentVersion.processing_path` SHALL be `PATH_B`
- **AND** the final `result_metadata["processing_path"]` SHALL be `"path_b"`

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

---

### Requirement: All-or-nothing error handling with failure cleanup

**[Modified by S3-04]** On any failure after Tx 1 has committed, the **handler** (not the orchestrator) SHALL execute a recovery transaction that marks the DocumentVersion, all associated Chunks, and the Document as FAILED. Each handler SHALL wrap its post-Tx-1 logic in a try/except block and call `mark_persisted_records_failed()` on failure. The Source SHALL be marked FAILED. The BackgroundTask SHALL be marked FAILED with `error_message` populated. Qdrant points SHALL use stable deterministic IDs derived from `chunk_id`, so re-upserts remain idempotent. If the worker cannot prove whether a Qdrant upsert wrote data, it SHALL attempt compensating deletion by those same `chunk_id` values before final failure handling. Failed records in PostgreSQL are NOT deleted; they serve as audit trail.

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

---

### Requirement: Result metadata on successful completion

**[Modified by S3-04]** On success, the BackgroundTask `result_metadata` SHALL contain: `chunk_count` (int), `embedding_model` (string), `embedding_dimensions` (int), `processing_path` (string, value `"path_a"` or `"path_b"`), `snapshot_id` (UUID string), `document_id` (UUID string), `document_version_id` (UUID string), `token_count_total` (int, sum of all chunk token counts). `DocumentVersion.processing_path` and `result_metadata["processing_path"]` represent the same outcome in different forms: the database field uses the enum values `PATH_A` / `PATH_B`, while `result_metadata["processing_path"]` uses the lowercase string values `"path_a"` / `"path_b"`. The `processing_path` value in `result_metadata` SHALL reflect the actual path used: `"path_a"` for Path A handler, `"path_b"` for Path B handler. For Path A with threshold fallback to Path B, the value SHALL be `"path_b"` and the persisted `DocumentVersion.processing_path` SHALL be `PATH_B`.

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

**[Modified by S3-04]** The pipeline SHALL create one `EmbeddingProfile` record per successful ingestion pass during Tx 2. The record SHALL capture the embedding model, dimensions, task type, and pipeline metadata. The `pipeline_version` field SHALL be parameterized: `"s3-04-path-a"` for Path A ingestion, `"s2-02-path-b"` for Path B ingestion. EmbeddingProfile records SHALL never be updated; each ingestion creates a new record for audit trail. The `_finalize_pipeline_success()` helper SHALL accept `processing_path` and `pipeline_version` parameters from the handler to populate these fields.

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

**[Modified by S3-04]** The arq worker `on_startup` hook SHALL initialize and store in the worker context: a dedicated `storage_http_client` (`httpx.AsyncClient` with `base_url=settings.seaweedfs_filer_url` and `timeout=30.0`), `StorageService` (wrapping the storage HTTP client with `base_path=settings.seaweedfs_sources_path`), `DoclingParser`, `QdrantService` (async Qdrant client), `EmbeddingService` (GenAI client), `SnapshotService`, `GeminiContentService` (GenAI client for text extraction), `HuggingFaceTokenizer` (for Path A token counting), and `settings`. The worker context SHALL also store Path A configuration values from settings (`path_a_text_threshold_pdf`, `path_a_text_threshold_media`, `path_a_max_pdf_pages`, `path_a_max_audio_duration_sec`, `path_a_max_video_duration_sec`). The `on_startup` hook SHALL call `qdrant_service.ensure_collection()` (idempotent) and `storage_service.ensure_storage_root()` (idempotent). The `on_shutdown` hook SHALL close the Qdrant client connection AND call `await ctx["storage_http_client"].aclose()` to properly clean up the storage HTTP client.

A `PipelineServices` dataclass (or equivalent container) SHALL bundle all services and configuration needed by handlers, so that handler signatures remain clean. `PipelineServices` SHALL include: `storage_service`, `docling_parser`, `qdrant_service`, `embedding_service`, `snapshot_service`, `gemini_content_service`, `tokenizer`, `settings`, and Path A configuration values.

#### Scenario: All services available in worker context after startup

- **WHEN** the arq worker completes startup
- **THEN** `ctx["storage_http_client"]`, `ctx["storage_service"]`, `ctx["docling_parser"]`, `ctx["qdrant_service"]`, `ctx["embedding_service"]`, `ctx["snapshot_service"]`, `ctx["gemini_content_service"]`, `ctx["tokenizer"]`, and `ctx["settings"]` SHALL all be present and initialized

#### Scenario: PipelineServices bundles all handler dependencies

- **WHEN** a handler is invoked by the orchestrator
- **THEN** the handler SHALL receive a `PipelineServices` instance containing all required services and configuration
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

## ADDED Requirements

### Requirement: PathRouter integration in orchestrator

**[Added by S3-04]** After downloading the source file from SeaweedFS, the orchestrator SHALL call `PathRouter.inspect_file(file_bytes, source_type)` to obtain `FileMetadata`, then call `PathRouter.determine_path(source_type, file_metadata)` to obtain a `PathDecision`. The orchestrator SHALL use the `PathDecision` to dispatch to the appropriate handler or reject the source. PathRouter is responsible only for initial metadata-based routing (page count, duration, source type); token-threshold enforcement remains the responsibility of `handle_path_a()`. If `handle_path_a()` reports a fallback condition, the orchestrator SHALL re-dispatch to `handle_path_b()` rather than having the handler call Path B directly. The PathRouter is a pure service with no database or network dependencies; it SHALL be called synchronously within the orchestrator.

#### Scenario: Orchestrator calls PathRouter after download

- **WHEN** the orchestrator has downloaded the source file
- **THEN** it SHALL call `inspect_file()` with the file bytes and source type
- **AND** then call `determine_path()` with the source type and file metadata
- **AND** use the resulting `PathDecision` to determine the next step

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

**[Added by S3-04]** The `_finalize_pipeline_success()` function SHALL accept `processing_path` and `pipeline_version` as parameters. Each handler SHALL pass its own values when calling finalization: Path A passes `processing_path=PATH_A` and `pipeline_version="s3-04-path-a"`, Path B passes `processing_path=PATH_B` and `pipeline_version="s2-02-path-b"`. This ensures the EmbeddingProfile accurately records which pipeline produced the embeddings.

#### Scenario: Path A handler passes correct pipeline_version

- **WHEN** the Path A handler completes successfully and calls finalization
- **THEN** it SHALL pass `pipeline_version="s3-04-path-a"` to `_finalize_pipeline_success()`

#### Scenario: Path B handler passes correct pipeline_version

- **WHEN** the Path B handler completes successfully and calls finalization
- **THEN** it SHALL pass `pipeline_version="s2-02-path-b"` to `_finalize_pipeline_success()`
