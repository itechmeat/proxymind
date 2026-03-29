## MODIFIED Requirements

### Requirement: Pipeline orchestration in the worker task

**[Modified by S3-06]** The ingestion worker task (`app/workers/tasks/ingestion.py`) SHALL be refactored into a thin orchestrator that dispatches to separate handler modules. The orchestrator SHALL execute these stages in sequence: (1) Download source file from SeaweedFS, (2) Inspect file via `PathRouter.inspect_file()` and determine processing path via `PathRouter.determine_path()`, (3) If path is REJECTED, mark the task FAILED with the rejection reason and return, (4) Dispatch to `handle_path_a()` (`app/workers/tasks/handlers/path_a.py`), `handle_path_b()` (`app/workers/tasks/handlers/path_b.py`), or `handle_path_c()` (`app/workers/tasks/handlers/path_c.py`) based on the routing decision, (5) Finalize statuses and create EmbeddingProfile (Tx 2). Each handler module SHALL own its own stages internally: persist (Tx 1), embed, index. The worker task IS the orchestrator; there SHALL NOT be a separate Pipeline abstraction class.

**[Modified by S2-03]** Stage persist (inside each handler) SHALL use `ensure_draft_or_rebind` to acquire a FOR UPDATE lock on the snapshot row before persisting any chunks. The lock SHALL be held through the chunk insert and transaction commit. If the snapshot is no longer DRAFT (published concurrently), the worker SHALL rebind to a new draft via the same method.

**[Modified by S3-06]** The orchestrator SHALL accept an optional `skip_embedding` flag from the `BackgroundTask.result_metadata`. When `skip_embedding=true`, the handler SHALL parse and chunk the source but SHALL NOT call `embedding_service.embed_texts()`, `embed_file()`, or `qdrant_service.upsert_chunks()`. Chunks SHALL be saved with status `PENDING`. The Source SHALL be set to `READY`. The BackgroundTask SHALL be marked COMPLETE with `result_metadata.skip_embedding = true`.

**[Modified by S3-06]** When `skip_embedding=false` (default) and the chunk count after parsing exceeds `batch_embed_chunk_threshold` (default 50), the handler SHALL return a `BatchSubmittedResult` early — before `_finalize_pipeline_success` is called. The handler SHALL create a `BatchJob` inline via `BatchOrchestrator.create_batch_job_for_threshold()`, then submit to Gemini via `BatchOrchestrator.submit_to_gemini()`. The Source SHALL stay `PROCESSING`, the BackgroundTask SHALL stay `PROCESSING`. The calling code in `_process_task` SHALL detect `BatchSubmittedResult` and exit without finalization. The `poll_active_batches` cron SHALL complete the lifecycle.

**[Modified by S4-06]** The orchestrator SHALL read `processing_hint` from the `BackgroundTask.result_metadata` and pass it to `PathRouter.determine_path()`. The orchestrator SHALL dispatch to `handle_path_c()` when the router returns `PATH_C`. The Path A fallback re-dispatch logic SHALL also consider `PATH_C` as a valid re-dispatch target when Document AI is configured and the document qualifies.

**[Modified by S9-01]** For Path B and Path C, when `ENRICHMENT_ENABLED=true`, an enrichment stage SHALL be inserted between chunking and embedding.

**[Modified by S9-01]** The handler SHALL call `EnrichmentService.enrich(chunks)` after parsing/chunking and before any embedding work begins. For each successfully enriched chunk, the handler SHALL build `enriched_text` (concatenation of `text_content` + summary + keywords + questions) and persist enrichment data to the Chunk DB columns (`enriched_summary`, `enriched_keywords`, `enriched_questions`, `enriched_text`, `enrichment_model`, `enrichment_pipeline_version`). The `texts_for_embedding` list SHALL use `enriched_text` when available, falling back to `text_content` per chunk.

**[Modified by S9-01]** When the batch threshold is exceeded, enrichment SHALL complete and any successful enrichment data SHALL be persisted to the Chunk DB columns before `BatchOrchestrator.create_batch_job_for_threshold()` and `BatchOrchestrator.submit_to_gemini()` are called. The `batch_orchestrator._apply_results` handler SHALL read those persisted enrichment columns when building the Qdrant payload on batch completion.

**[Modified by S9-01]** Enrichment failure SHALL be fail-open at both levels. If enrichment fails for an individual chunk, that chunk SHALL proceed with original `text_content` and `NULL` enrichment columns. If `EnrichmentService.enrich()` is unavailable or raises for the whole batch, the pipeline SHALL continue by processing all chunks with original `text_content` and no enrichment rather than failing the entire source.

**[Modified by S9-01]** Path A SHALL explicitly skip enrichment regardless of the `ENRICHMENT_ENABLED` flag because Path A `text_content` is already LLM-generated. When `ENRICHMENT_ENABLED=false`, the enrichment stage SHALL be skipped entirely and the pipeline SHALL behave exactly as before.

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

#### Scenario: Path B enrichment runs when enabled

- **WHEN** a source is routed to Path B
- **AND** `ENRICHMENT_ENABLED=true`
- **THEN** the handler SHALL call `EnrichmentService.enrich(chunks)` after chunking and before embedding
- **AND** successfully enriched chunks SHALL have `enriched_text` used for both dense embedding and BM25 sparse vector generation
- **AND** enrichment data SHALL be persisted to the Chunk DB columns before embedding begins

#### Scenario: Path C enrichment runs when enabled

- **WHEN** a source is routed to Path C
- **AND** `ENRICHMENT_ENABLED=true`
- **THEN** the handler SHALL call `EnrichmentService.enrich(chunks)` after Document AI parsing and chunking and before embedding
- **AND** successfully enriched chunks SHALL have `enriched_text` used for both dense embedding and BM25 sparse vector generation
- **AND** enrichment data SHALL be persisted to the Chunk DB columns before embedding begins

#### Scenario: Path A skips enrichment regardless of feature flag

- **WHEN** a source is routed to Path A
- **AND** `ENRICHMENT_ENABLED=true`
- **THEN** the handler SHALL NOT call `EnrichmentService.enrich()`
- **AND** the chunk SHALL be embedded using the original `text_content` only
- **AND** no enrichment columns SHALL be populated on the Chunk DB row

#### Scenario: Enrichment disabled preserves existing pipeline behavior

- **WHEN** `ENRICHMENT_ENABLED=false`
- **THEN** the enrichment stage SHALL be skipped entirely for all paths
- **AND** the pipeline SHALL behave identically to the pre-enrichment implementation

#### Scenario: Enrichment failure is fail-open per chunk

- **WHEN** `ENRICHMENT_ENABLED=true`
- **AND** `EnrichmentService.enrich()` fails for a specific chunk (timeout, invalid response)
- **THEN** the failed chunk SHALL proceed with original `text_content` for embedding
- **AND** the failed chunk's enrichment DB columns SHALL remain NULL
- **AND** the pipeline SHALL NOT fail — other successfully enriched chunks SHALL use their `enriched_text`

#### Scenario: Batch flow reads enrichment from Chunk DB on completion

- **WHEN** a Path B or Path C source exceeds `batch_embed_chunk_threshold`
- **AND** `ENRICHMENT_ENABLED=true`
- **AND** enrichment data has been persisted to Chunk DB columns before batch submission
- **THEN** `batch_orchestrator._apply_results` SHALL read `enriched_text`, `enriched_summary`, `enriched_keywords`, `enriched_questions`, `enrichment_model`, and `enrichment_pipeline_version` from the Chunk DB rows
- **AND** the Qdrant payload SHALL include the enrichment fields read from the database
- **AND** the BM25 sparse vector SHALL use `enriched_text` (when available) as input

---
