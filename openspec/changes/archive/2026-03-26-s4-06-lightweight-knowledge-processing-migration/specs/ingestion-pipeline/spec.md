# ingestion-pipeline (delta)

**Story:** S4-06 — Lightweight Knowledge Processing Migration
**Status:** MODIFIED capability
**Test coverage requirement:** All stable behavior introduced or modified by this change MUST be covered by CI tests before archive.

---

## MODIFIED Requirements

### Requirement: Pipeline orchestration in the worker task

**[Modified by S3-06]** The ingestion worker task (`app/workers/tasks/ingestion.py`) SHALL be refactored into a thin orchestrator that dispatches to separate handler modules. The orchestrator SHALL execute these stages in sequence: (1) Download source file from SeaweedFS, (2) Inspect file via `PathRouter.inspect_file()` and determine processing path via `PathRouter.determine_path()`, (3) If path is REJECTED, mark the task FAILED with the rejection reason and return, (4) Dispatch to `handle_path_a()` (`app/workers/tasks/handlers/path_a.py`), `handle_path_b()` (`app/workers/tasks/handlers/path_b.py`), or `handle_path_c()` (`app/workers/tasks/handlers/path_c.py`) based on the routing decision, (5) Finalize statuses and create EmbeddingProfile (Tx 2). Each handler module SHALL own its own stages internally: persist (Tx 1), embed, index. The worker task IS the orchestrator; there SHALL NOT be a separate Pipeline abstraction class.

**[Modified by S2-03]** Stage persist (inside each handler) SHALL use `ensure_draft_or_rebind` to acquire a FOR UPDATE lock on the snapshot row before persisting any chunks. The lock SHALL be held through the chunk insert and transaction commit. If the snapshot is no longer DRAFT (published concurrently), the worker SHALL rebind to a new draft via the same method.

**[Modified by S3-06]** The orchestrator SHALL accept an optional `skip_embedding` flag from the `BackgroundTask.result_metadata`. When `skip_embedding=true`, the handler SHALL parse and chunk the source but SHALL NOT call `embedding_service.embed_texts()`, `embed_file()`, or `qdrant_service.upsert_chunks()`. Chunks SHALL be saved with status `PENDING`. The Source SHALL be set to `READY`. The BackgroundTask SHALL be marked COMPLETE with `result_metadata.skip_embedding = true`.

**[Modified by S3-06]** When `skip_embedding=false` (default) and the chunk count after parsing exceeds `batch_embed_chunk_threshold` (default 50), the handler SHALL return a `BatchSubmittedResult` early -- before `_finalize_pipeline_success` is called. The handler SHALL create a `BatchJob` inline via `BatchOrchestrator.create_batch_job_for_threshold()`, then submit to Gemini via `BatchOrchestrator.submit_to_gemini()`. The Source SHALL stay `PROCESSING`, the BackgroundTask SHALL stay `PROCESSING`. The calling code in `_process_task` SHALL detect `BatchSubmittedResult` and exit without finalization. The `poll_active_batches` cron SHALL complete the lifecycle.

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

#### Scenario: Successful end-to-end pipeline execution via Path B (unchanged)

- **WHEN** the ingestion task processes a valid text source (e.g., `.md`, `.txt`, `.docx`, `.html`) with status PENDING
- **THEN** the PathRouter SHALL route the source to Path B
- **AND** the Source status SHALL transition PENDING -> PROCESSING -> READY
- **AND** a Document record SHALL be created with status READY
- **AND** a DocumentVersion record SHALL be created with `version_number=1`, `processing_path=PATH_B`, status READY
- **AND** Chunk records SHALL be created with status INDEXED
- **AND** vectors SHALL be upserted to Qdrant
- **AND** an EmbeddingProfile record SHALL be created with `pipeline_version="s2-02-path-b"`
- **AND** the BackgroundTask SHALL have status COMPLETE, progress 100, and `result_metadata` populated

#### Scenario: Successful end-to-end pipeline execution via Path A (unchanged)

- **WHEN** the ingestion task processes a valid Path A source (e.g., image, short PDF, short audio/video) with status PENDING
- **THEN** the PathRouter SHALL route the source to Path A
- **AND** the Source status SHALL transition PENDING -> PROCESSING -> READY
- **AND** a Document record SHALL be created with status READY
- **AND** a DocumentVersion record SHALL be created with `version_number=1`, `processing_path=PATH_A`, status READY
- **AND** exactly one Chunk record SHALL be created with status INDEXED
- **AND** vectors SHALL be upserted to Qdrant (dense + BM25)
- **AND** an EmbeddingProfile record SHALL be created with `pipeline_version="s3-04-path-a"`
- **AND** the BackgroundTask SHALL have status COMPLETE, progress 100, and `result_metadata` populated

---

### Requirement: Result metadata on successful completion

**[Modified by S3-04]** On success, the BackgroundTask `result_metadata` SHALL contain: `chunk_count` (int), `embedding_model` (string), `embedding_dimensions` (int), `processing_path` (string, value `"path_a"`, `"path_b"`, or `"path_c"`), `snapshot_id` (UUID string), `document_id` (UUID string), `document_version_id` (UUID string), `token_count_total` (int, sum of all chunk token counts). `DocumentVersion.processing_path` and `result_metadata["processing_path"]` represent the same outcome in different forms: the database field uses the enum values `PATH_A` / `PATH_B` / `PATH_C`, while `result_metadata["processing_path"]` uses the lowercase string values `"path_a"` / `"path_b"` / `"path_c"`. The `processing_path` value in `result_metadata` SHALL reflect the actual path used: `"path_a"` for Path A handler, `"path_b"` for Path B handler, `"path_c"` for Path C handler. For Path A with threshold fallback to Path B, the value SHALL be `"path_b"` and the persisted `DocumentVersion.processing_path` SHALL be `PATH_B`.

**[Modified by S4-06]** The `processing_path` field now includes `"path_c"` as a valid value. The `processing_path` enum in the database now includes `PATH_C`.

#### Scenario: result_metadata contains processing_path "path_c" for Path C

- **WHEN** the ingestion task completes successfully via Path C
- **THEN** `result_metadata` SHALL contain all 8 specified fields with correct types and values
- **AND** `processing_path` SHALL be `"path_c"`

#### Scenario: result_metadata contains all required fields for Path B (unchanged)

- **WHEN** the ingestion task completes successfully via Path B
- **THEN** `result_metadata` SHALL contain all 8 specified fields with correct types and values
- **AND** `processing_path` SHALL be `"path_b"`

#### Scenario: result_metadata contains all required fields for Path A (unchanged)

- **WHEN** the ingestion task completes successfully via Path A
- **THEN** `result_metadata` SHALL contain all 8 specified fields with correct types and values
- **AND** `processing_path` SHALL be `"path_a"`
- **AND** `chunk_count` SHALL be 1

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

#### Scenario: Qdrant collection ensured on startup (unchanged)

- **WHEN** the arq worker starts
- **THEN** `ensure_collection()` SHALL be called during startup to verify collection readiness

#### Scenario: Storage root ensured on startup (unchanged)

- **WHEN** the arq worker starts
- **THEN** `ensure_storage_root()` SHALL be called during startup to verify SeaweedFS Filer availability

---

### Requirement: All-or-nothing error handling with failure cleanup

**[Modified by S3-04]** On any failure after Tx 1 has committed, the **handler** (not the orchestrator) SHALL execute a recovery transaction that marks the DocumentVersion, all associated Chunks, and the Document as FAILED. Each handler SHALL wrap its post-Tx-1 logic in a try/except block and call `mark_persisted_records_failed()` on failure. The Source SHALL be marked FAILED. The BackgroundTask SHALL be marked FAILED with `error_message` populated. Qdrant points SHALL use stable deterministic IDs derived from `chunk_id`, so re-upserts remain idempotent. If the worker cannot prove whether a Qdrant upsert wrote data, it SHALL attempt compensating deletion by those same `chunk_id` values before final failure handling. Failed records in PostgreSQL are NOT deleted; they serve as audit trail.

**[Modified by S4-06]** The Path C handler SHALL follow the same error handling pattern. On failure after Tx 1, the Path C handler SHALL call `mark_persisted_records_failed()` and attempt compensating Qdrant deletion.

#### Scenario: Path C handler failure marks records as FAILED

- **WHEN** the Document AI call or embedding fails after Tx 1 has committed Chunk records in Path C
- **THEN** the Path C handler SHALL catch the exception and call `mark_persisted_records_failed()`
- **AND** the DocumentVersion, Chunks, Document, and Source statuses SHALL be FAILED
- **AND** the BackgroundTask SHALL be FAILED with `error_message` populated

#### Scenario: Each handler owns its own cleanup (expanded)

- **WHEN** the Path A handler fails after Tx 1
- **THEN** the Path A handler itself SHALL execute the failure cleanup

- **WHEN** the Path B handler fails after Tx 1
- **THEN** the Path B handler itself SHALL execute the failure cleanup

- **WHEN** the Path C handler fails after Tx 1
- **THEN** the Path C handler itself SHALL execute the failure cleanup

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

#### Scenario: EmbeddingProfile created on success via Path B (unchanged)

- **WHEN** the ingestion pipeline completes successfully via Path B
- **THEN** exactly one new EmbeddingProfile record SHALL exist in PostgreSQL
- **AND** its `pipeline_version` field SHALL be `"s2-02-path-b"`

#### Scenario: EmbeddingProfile created on success via Path A (unchanged)

- **WHEN** the ingestion pipeline completes successfully via Path A
- **THEN** exactly one new EmbeddingProfile record SHALL exist in PostgreSQL
- **AND** its `pipeline_version` field SHALL be `"s3-04-path-a"`

---

### Requirement: ProcessingPath enum gains PATH_C

**[Added by S4-06]** The `ProcessingPath` enum at `app/db/models/enums.py` SHALL include `PATH_C` as a valid value in addition to existing `PATH_A` and `PATH_B`. An Alembic migration SHALL execute `ALTER TYPE processing_path_enum ADD VALUE IF NOT EXISTS 'path_c'` to add the new value to the PostgreSQL native enum. This migration MUST be non-reversible (PostgreSQL does not support removing enum values).

> Note: The path router's "rejected" outcome is represented as `PathDecision(path=None, rejected=True)`, not as a `ProcessingPath` enum member. `REJECTED` is NOT part of the `ProcessingPath` enum.

#### Scenario: PATH_C is a valid ProcessingPath value

- **WHEN** `ProcessingPath.PATH_C` is referenced in code
- **THEN** it SHALL be a valid enum member with value `"path_c"`

#### Scenario: Database enum includes path_c after migration

- **WHEN** the Alembic migration runs
- **THEN** the `processing_path_enum` type in PostgreSQL SHALL include `"path_c"` as a valid value
- **AND** a `DocumentVersion` record with `processing_path = 'path_c'` SHALL be accepted by the database

---

### Requirement: Path routing gains processing_hint parameter and PATH_C support

**[Added by S4-06]** The `PathRouter.determine_path()` method SHALL accept an optional `processing_hint` parameter (default `"auto"`). The routing logic SHALL be extended:

- When `processing_hint="external"` and the source is a PDF and Document AI is configured: return `PATH_C`
- When `processing_hint="external"` and Document AI is NOT configured: return `PATH_B` and log a warning (the router owns the warning because the router is where the decision happens)
- When `processing_hint="external"` and the source is not a PDF: ignore the hint (DOCX/HTML/MD/TXT always use Path B)
- When `processing_hint="auto"` (default): existing routing logic applies (PATH_A or PATH_B based on file type and size)

The router SHALL accept a `document_ai_available: bool` parameter (or equivalent) to know whether Document AI is configured, without depending on the `DocumentAIParser` instance directly.

#### Scenario: Explicit external hint routes PDF to Path C

- **WHEN** `determine_path()` is called with a PDF source, `processing_hint="external"`, and Document AI configured
- **THEN** the result SHALL be `PATH_C`

#### Scenario: External hint with unconfigured Document AI falls back to Path B

- **WHEN** `determine_path()` is called with a PDF source, `processing_hint="external"`, and Document AI NOT configured
- **THEN** the result SHALL be `PATH_B`
- **AND** a warning SHALL be logged indicating Document AI is not available

#### Scenario: External hint ignored for non-PDF formats

- **WHEN** `determine_path()` is called with a DOCX source and `processing_hint="external"`
- **THEN** the hint SHALL be ignored
- **AND** the routing SHALL follow the standard logic (PATH_B for text formats)

#### Scenario: Auto hint uses existing routing logic

- **WHEN** `determine_path()` is called with `processing_hint="auto"`
- **THEN** routing SHALL follow the existing PATH_A / PATH_B logic unchanged
