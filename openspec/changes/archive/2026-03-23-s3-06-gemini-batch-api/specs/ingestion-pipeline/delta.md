## MODIFIED Requirements

### Requirement: Pipeline orchestration in the worker task

**[Modified by S3-06]** The ingestion worker task (`app/workers/tasks/ingestion.py`) SHALL be refactored into a thin orchestrator that dispatches to separate handler modules. The orchestrator SHALL execute these stages in sequence: (1) Download source file from SeaweedFS, (2) Inspect file via `PathRouter.inspect_file()` and determine processing path via `PathRouter.determine_path()`, (3) If path is REJECTED, mark the task FAILED with the rejection reason and return, (4) Dispatch to `handle_path_a()` (`app/workers/tasks/handlers/path_a.py`) or `handle_path_b()` (`app/workers/tasks/handlers/path_b.py`) based on the routing decision, (5) Finalize statuses and create EmbeddingProfile (Tx 2). Each handler module SHALL own its own stages internally: persist (Tx 1), embed, index. The worker task IS the orchestrator; there SHALL NOT be a separate Pipeline abstraction class.

**[Modified by S2-03]** Stage persist (inside each handler) SHALL use `ensure_draft_or_rebind` to acquire a FOR UPDATE lock on the snapshot row before persisting any chunks. The lock SHALL be held through the chunk insert and transaction commit. If the snapshot is no longer DRAFT (published concurrently), the worker SHALL rebind to a new draft via the same method.

**[Modified by S3-06]** The orchestrator SHALL accept an optional `skip_embedding` flag from the `BackgroundTask.result_metadata`. When `skip_embedding=true`, the handler SHALL parse and chunk the source but SHALL NOT call `embedding_service.embed_texts()`, `embed_file()`, or `qdrant_service.upsert_chunks()`. Chunks SHALL be saved with status `PENDING`. The Source SHALL be set to `READY`. The BackgroundTask SHALL be marked COMPLETE with `result_metadata.skip_embedding = true`.

**[Modified by S3-06]** When `skip_embedding=false` (default) and the chunk count after parsing exceeds `batch_embed_chunk_threshold` (default 50), the handler SHALL return a `BatchSubmittedResult` early — before `_finalize_pipeline_success` is called. The handler SHALL first persist the parsed chunks in PostgreSQL with status `PENDING`, then create a `BatchJob` inline via `BatchOrchestrator.create_batch_job_for_threshold()`, then submit to Gemini via `BatchOrchestrator.submit_to_gemini()`. The Source SHALL stay `PROCESSING`, the BackgroundTask SHALL stay `PROCESSING`. The calling code in `_process_task` SHALL detect `BatchSubmittedResult` and exit without finalization. The `poll_active_batches` cron SHALL complete the lifecycle.

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

#### Scenario: Skip-embedding path parses and chunks without embedding

- **WHEN** the ingestion task has `result_metadata.skip_embedding = true`
- **THEN** the handler SHALL parse and chunk the source file
- **AND** chunks SHALL be saved to PostgreSQL with status `PENDING`
- **AND** `embedding_service.embed_texts()` SHALL NOT be called
- **AND** `qdrant_service.upsert_chunks()` SHALL NOT be called
- **AND** the Source status SHALL be set to `READY`
- **AND** the BackgroundTask SHALL be marked COMPLETE
- **AND** `result_metadata` SHALL contain `skip_embedding: true`

#### Scenario: Auto-threshold routes large source to Batch API

- **WHEN** the ingestion task has `skip_embedding=false` (default)
- **AND** parsing produces a chunk count exceeding `batch_embed_chunk_threshold`
- **THEN** the handler SHALL return a `BatchSubmittedResult`
- **AND** the persisted chunk rows SHALL already exist in PostgreSQL with status `PENDING`
- **AND** a `BatchJob` SHALL be created and submitted to Gemini
- **AND** the Source SHALL remain in `PROCESSING` status
- **AND** the BackgroundTask SHALL remain in `PROCESSING` status
- **AND** `_finalize_pipeline_success` SHALL NOT be called

#### Scenario: Below-threshold source uses interactive embedding

- **WHEN** the ingestion task has `skip_embedding=false`
- **AND** parsing produces a chunk count at or below `batch_embed_chunk_threshold`
- **THEN** the handler SHALL proceed with interactive `embed_texts()` and Qdrant upsert as normal

---

## ADDED Requirements

### Requirement: skip_embedding query parameter on POST /api/admin/sources

**[Added by S3-06]** The `POST /api/admin/sources` endpoint SHALL accept an optional `skip_embedding` query parameter (boolean, default `false`). When `true`, the ingestion task SHALL be created with `result_metadata.skip_embedding = true`. The worker SHALL read this flag and skip the embedding and Qdrant upsert stages. Chunks SHALL be saved with status `PENDING`. The Source SHALL be set to `READY` (parsed and chunked). The BackgroundTask SHALL be marked COMPLETE. This does NOT mean the source is searchable — `PENDING` chunks are never upserted to Qdrant and cannot be returned by vector search. Those chunks SHALL become searchable only through a later embedding lifecycle such as `POST /api/admin/batch-embed`, which creates a separate `BATCH_EMBEDDING` BackgroundTask and transitions the existing chunk rows from `PENDING` to `INDEXED` after successful Qdrant upsert.

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

### CI tests (deterministic)

The following stable behavior MUST be covered by CI tests before archive:

- **Skip-embedding flow**: upload source with `skip_embedding=true` -> worker parses and chunks -> chunks PENDING, source READY, no Qdrant entries, task COMPLETE.
- **Skip-embedding flag propagation**: verify `result_metadata.skip_embedding` is set on BackgroundTask when upload uses `skip_embedding=true`.
- **Auto-threshold detection**: mock chunk count above threshold -> handler returns `BatchSubmittedResult`, no interactive embedding, source stays PROCESSING.
- **Below-threshold proceeds normally**: mock chunk count at or below threshold -> handler proceeds with interactive embedding.
- **SkipEmbeddingResult handling**: verify `_process_task` marks task COMPLETE on `SkipEmbeddingResult`.
- **BatchSubmittedResult handling**: verify `_process_task` exits without finalization on `BatchSubmittedResult`.
- **Existing pipeline tests unaffected**: all existing ingestion pipeline tests SHALL continue to pass without modification.
