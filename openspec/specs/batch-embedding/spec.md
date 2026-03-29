## ADDED Requirements

### Requirement: BatchEmbeddingClient service

The system SHALL provide a `BatchEmbeddingClient` service at `app/services/batch_embedding.py` that wraps the `google-genai` SDK batch API for document-ingestion bulk embedding operations. The client SHALL expose three methods: `create_embedding_batch(requests)` to submit a batch embedding job to Gemini, `get_batch_status(batch_name)` to poll batch status, and `get_batch_results(batch_name)` to retrieve completed batch results. The client SHALL use the same `genai.Client` instance pattern as `EmbeddingService` (lazy singleton, thread-safe). The client SHALL map SDK responses to internal dataclasses — Gemini SDK types SHALL NOT leak across the service boundary.

#### Scenario: Create embedding batch submits to Gemini

- **WHEN** `create_embedding_batch()` is called with a list of text-chunk embedding requests
- **THEN** the client SHALL submit a batch job to the Gemini Batch API
- **AND** return a batch operation name (string identifier) for polling

#### Scenario: Get batch status returns mapped internal status

- **WHEN** `get_batch_status()` is called with a valid batch operation name
- **THEN** the client SHALL return an internal status dataclass (not a Gemini SDK type)
- **AND** the status SHALL be mapped from Gemini states to internal `BatchStatus` values

#### Scenario: Get batch results parses completed batch

- **WHEN** `get_batch_results()` is called for a completed batch
- **THEN** the client SHALL return a list of result items containing chunk embeddings
- **AND** each result item SHALL include the embedding vector and a correlation identifier (custom_id or positional index)

#### Scenario: SDK types do not leak across boundary

- **WHEN** any method on `BatchEmbeddingClient` returns a result
- **THEN** the return type SHALL be an internal dataclass defined in the batch embedding module
- **AND** no Gemini SDK types SHALL appear in the return signature

---

### Requirement: BatchEmbeddingClient status mapping

The `BatchEmbeddingClient` SHALL map Gemini batch states to internal `BatchStatus` values according to: Gemini PENDING/QUEUED maps to `processing`, Gemini RUNNING/ACTIVE maps to `processing`, Gemini SUCCEEDED maps to `complete`, Gemini FAILED maps to `failed`, Gemini EXPIRED maps to `failed`, Gemini CANCELLED maps to `cancelled`. The `last_polled_at` timestamp SHALL be updated on every successful poll regardless of state change.

#### Scenario: Gemini PENDING maps to processing

- **WHEN** Gemini reports batch state as PENDING or QUEUED
- **THEN** the mapped `BatchStatus` SHALL be `processing`

#### Scenario: Gemini SUCCEEDED maps to complete

- **WHEN** Gemini reports batch state as SUCCEEDED
- **THEN** the mapped `BatchStatus` SHALL be `complete`

#### Scenario: Gemini FAILED maps to failed

- **WHEN** Gemini reports batch state as FAILED
- **THEN** the mapped `BatchStatus` SHALL be `failed`

#### Scenario: Gemini EXPIRED maps to failed

- **WHEN** Gemini reports batch state as EXPIRED
- **THEN** the mapped `BatchStatus` SHALL be `failed`

#### Scenario: Gemini CANCELLED maps to cancelled

- **WHEN** Gemini reports batch state as CANCELLED
- **THEN** the mapped `BatchStatus` SHALL be `cancelled`

---

### Requirement: BatchEmbeddingClient retry policy

Each `BatchEmbeddingClient` method that calls the Gemini API SHALL be wrapped with tenacity retry. The retry SHALL trigger on HTTP 429 (rate limit) and 5xx errors. The retry strategy SHALL use exponential backoff with `multiplier=1`, `min=1`, `max=8`, and a maximum of 3 attempts. This matches the existing retry policy used by `EmbeddingService`.

#### Scenario: Transient 429 error is retried

- **WHEN** the Gemini Batch API returns a 429 error on the first attempt and succeeds on the second
- **THEN** the call SHALL succeed without raising an exception

#### Scenario: Persistent failure after max retries raises exception

- **WHEN** the Gemini Batch API returns 5xx on all 3 attempts
- **THEN** the call SHALL raise an exception after exhausting retries

#### Scenario: Non-transient errors are not retried

- **WHEN** the Gemini Batch API returns a 400 (bad request) error
- **THEN** the exception SHALL propagate immediately without retry

---

### Requirement: BatchOrchestrator submit_to_gemini

The system SHALL provide a document-ingestion-specific `BatchOrchestrator` service at `app/services/batch_orchestrator.py` that orchestrates the batch lifecycle. The `submit_to_gemini()` method SHALL accept a `background_task_id`, `texts`, and `chunk_ids` loaded by the caller (either the `process_batch_embed` worker or the auto-threshold Path B handler). It SHALL find the existing `BatchJob` by `background_task_id`, validate that the supplied ordered `chunk_ids` match `BatchJob.result_metadata["chunk_ids"]` written at BatchJob creation time, call `BatchEmbeddingClient.create_embedding_batch()`, and update the `BatchJob` with the Gemini batch operation name. This method SHALL NOT query chunks on its own; the caller owns chunk loading so submission order remains explicit and deterministic. Caller-side validation SHALL enforce `batch_max_items_per_request` before `submit_to_gemini()` is reached; API-triggered `/api/admin/batch-embed` requests SHALL reject oversize submissions with 422 rather than splitting (splitting is deferred to a future story when actual Gemini limits are encountered).

#### Scenario: Submit validates caller-supplied chunk ordering

- **WHEN** `submit_to_gemini()` is called with caller-loaded `texts` and `chunk_ids`
- **THEN** the orchestrator SHALL validate those `chunk_ids` against `BatchJob.result_metadata["chunk_ids"]`
- **AND** SHALL submit the items to Gemini in that same order

#### Scenario: Chunk IDs stored for result correlation

- **WHEN** a batch is submitted to Gemini
- **THEN** `BatchJob.result_metadata` SHALL contain `{"chunk_ids": [...]}` with chunk UUIDs in submission order

#### Scenario: API-triggered large batch exceeding max_items_per_request is rejected

- **WHEN** caller-side validation sees a total PENDING chunk count above `batch_max_items_per_request` (default 1000)
- **THEN** `/api/admin/batch-embed` SHALL reject with 422 Unprocessable Entity
- **AND** the error message SHALL indicate the limit and suggest splitting the source_ids into smaller groups

#### Scenario: BatchJob updated with Gemini operation name

- **WHEN** Gemini accepts the batch submission
- **THEN** `BatchJob.batch_operation_name` SHALL be updated with the Gemini-returned identifier
- **AND** `BatchJob.status` SHALL be `processing`
- **AND** `BatchJob.request_count` SHALL be set to the total number of submitted items

---

### Requirement: BatchOrchestrator dedup guard

Before creating a Gemini batch, the `BatchOrchestrator` SHALL check for an existing in-flight batch linked to the same `background_task_id` with status `pending` or `processing`. If found, the orchestrator SHALL return the existing `BatchJob` and join its polling cycle instead of creating a duplicate Gemini batch. This guard protects against manual re-enqueue, operational recovery scripts, or future changes to the arq retry policy.

#### Scenario: Existing in-flight batch prevents duplicate creation

- **WHEN** `submit_to_gemini()` is called for a BatchJob whose `background_task_id` already has an in-flight batch
- **THEN** the orchestrator SHALL return the existing BatchJob
- **AND** no new Gemini batch SHALL be created

#### Scenario: No in-flight batch proceeds with submission

- **WHEN** `submit_to_gemini()` is called and no in-flight batch exists for the `background_task_id`
- **THEN** the orchestrator SHALL proceed to submit a new batch to Gemini

---

### Requirement: BatchOrchestrator result application with finalization

In this story, batch result application is specific to document-ingestion jobs whose successful embeddings are indexed in Qdrant and then finalized into `Document`, `DocumentVersion`, `EmbeddingProfile`, `KnowledgeSnapshot`, `BackgroundTask`, and `Source` state. On batch completion, the `BatchOrchestrator.apply_results(batch_job, results)` method SHALL correlate results to chunks via stored `chunk_ids` (using `custom_id` first, falling back to positional matching with length validation). For succeeded items: upsert vector + payload to Qdrant, set `chunk.status = INDEXED`. For failed items: leave `chunk.status = PENDING`, log error in `result_metadata`. The method SHALL update `BatchJob.succeeded_count` and `failed_count`. If all items succeeded: `BatchJob.status = complete`. If some failed: `BatchJob.status = complete` (partial failures tracked in metadata). If all failed: `BatchJob.status = failed`. After result application, the orchestrator SHALL finalize related records using shared logic with `_finalize_pipeline_success`: `Document` to READY, `DocumentVersion` to READY, create `EmbeddingProfile` record, update `KnowledgeSnapshot.chunk_count`, `BackgroundTask` to COMPLETE (or FAILED if all items failed), Source to READY (for auto-threshold path where source was PROCESSING).

#### Scenario: All items succeeded

- **WHEN** a Gemini batch completes and all items succeeded
- **THEN** all chunks SHALL be upserted to Qdrant with status INDEXED
- **AND** `BatchJob.status` SHALL be `complete`
- **AND** `BatchJob.succeeded_count` SHALL equal the total item count
- **AND** `BatchJob.failed_count` SHALL be 0
- **AND** `Document` and `DocumentVersion` SHALL be READY
- **AND** an `EmbeddingProfile` record SHALL be created
- **AND** `KnowledgeSnapshot.chunk_count` SHALL be updated
- **AND** `BackgroundTask` SHALL be COMPLETE

#### Scenario: Partial failure

- **WHEN** a Gemini batch completes and 90 of 100 items succeeded
- **THEN** succeeded chunks SHALL be upserted to Qdrant with status INDEXED
- **AND** failed chunks SHALL remain with status PENDING
- **AND** `BatchJob.status` SHALL be `complete`
- **AND** `BatchJob.succeeded_count` SHALL be 90
- **AND** `BatchJob.failed_count` SHALL be 10
- **AND** `BatchJob.result_metadata` SHALL contain `failed_items` with per-item error details

#### Scenario: All items failed

- **WHEN** a Gemini batch completes and all items failed
- **THEN** no chunks SHALL be upserted to Qdrant
- **AND** all chunks SHALL remain with status PENDING
- **AND** `BatchJob.status` SHALL be `failed`
- **AND** `BackgroundTask` SHALL be FAILED

#### Scenario: Result correlation via custom_id

- **WHEN** Gemini batch results include `custom_id` set to chunk UUIDs
- **THEN** the orchestrator SHALL use `custom_id` to correlate results to chunks

#### Scenario: Result correlation falls back to positional matching

- **WHEN** Gemini batch results do not include `custom_id`
- **THEN** the orchestrator SHALL use positional matching with the stored `chunk_ids` list
- **AND** SHALL validate that `len(results) == len(chunk_ids)` before applying

---

### Requirement: BatchOrchestrator poll_and_complete

The `BatchOrchestrator.poll_and_complete(session, *, batch_job)` method SHALL own one poll cycle for an existing in-flight `BatchJob`. It SHALL require a database session and a loaded `BatchJob` instance with `status=processing`. The method SHALL poll Gemini via `BatchEmbeddingClient.get_batch_status()`, update `BatchJob` progress counters and timestamps, and then follow one of three branches: (1) if Gemini still reports processing, persist the updated polling metadata and return; (2) if Gemini reports failed or cancelled, mark the `BatchJob` terminal, update the linked `BackgroundTask` terminal status, persist, and return; (3) if Gemini reports success, fetch results via `BatchEmbeddingClient.get_batch_results()`, apply them through the orchestrator's result-application logic, and return the updated `BatchJob`. Unexpected exceptions from polling, result retrieval, or result application SHALL bubble to the caller so `poll_active_batches` can log the failure and continue with other jobs.

#### Scenario: Poll cycle for processing batch updates polling metadata

- **WHEN** `poll_and_complete()` polls Gemini and the batch is still running
- **THEN** the `BatchJob` SHALL remain in `processing`
- **AND** `last_polled_at`, `processed_count`, `succeeded_count`, and `failed_count` SHALL be updated

#### Scenario: Poll cycle finalizes failed batch

- **WHEN** `poll_and_complete()` polls Gemini and the batch reports FAILED or CANCELLED
- **THEN** the `BatchJob` SHALL be marked terminal
- **AND** the linked `BackgroundTask` SHALL be marked FAILED or CANCELLED
- **AND** the method SHALL persist the terminal state without applying results

#### Scenario: Poll cycle finalizes successful batch

- **WHEN** `poll_and_complete()` polls Gemini and the batch reports SUCCEEDED
- **THEN** the method SHALL load completed results from Gemini
- **AND** SHALL apply them through the orchestrator's result-application logic
- **AND** SHALL return the finalized `BatchJob`

---

### Requirement: BatchJob result_metadata schema

The `BatchJob.result_metadata` JSONB field SHALL have a documented, story-specific schema. For API-triggered `/api/admin/batch-embed` jobs, creation-time metadata SHALL include at least `chunk_ids` in submission order. For auto-threshold ingestion jobs, creation-time metadata SHALL include `chunk_ids` plus the persisted document-finalization fields needed after polling: `document_id`, `document_version_id`, `token_count_total`, `processing_path`, and `pipeline_version`. After polling completes, the orchestrator MAY append `failed_items`. `BackgroundTask.result_metadata` is a separate payload and remains the owner of user-facing task context such as `source_ids`, `knowledge_base_id`, and `snapshot_id`.

#### Scenario: API-triggered batch job stores ordered chunk IDs

- **WHEN** `/api/admin/batch-embed` creates a `BatchJob`
- **THEN** `BatchJob.result_metadata` SHALL contain `chunk_ids` in the exact submission order used later for Gemini result correlation

#### Scenario: Auto-threshold batch job stores finalization fields

- **WHEN** Path B auto-threshold ingestion creates a `BatchJob`
- **THEN** `BatchJob.result_metadata` SHALL include `chunk_ids`, `document_id`, `document_version_id`, `token_count_total`, `processing_path`, and `pipeline_version`

#### Scenario: Completed batch records failed items in metadata

- **WHEN** a polled Gemini batch finishes with partial failures
- **THEN** the orchestrator SHALL append `failed_items` to `BatchJob.result_metadata`

---

### Requirement: POST /api/admin/batch-embed endpoint

The system SHALL provide a `POST /api/admin/batch-embed` endpoint that triggers batch embedding for specified sources. The request body SHALL contain `source_ids` (array of UUIDs). The `agent_id` and `knowledge_base_id` SHALL be derived from the sources. The endpoint SHALL validate: all source_ids exist and have status READY, all sources have at least one chunk with status PENDING, all sources belong to the same agent_id/knowledge_base_id, all PENDING chunks for the given source_ids belong to the same snapshot_id (reject with 400 if chunks span multiple snapshots). The endpoint SHALL create a `BackgroundTask` (type=BATCH_EMBEDDING, status=PENDING, source_id=NULL) and a `BatchJob` (status=pending, operation_type=embedding) synchronously, then enqueue the `process_batch_embed` arq task. The response SHALL be 202 Accepted with `task_id`, `batch_job_id`, `chunk_count`, and `message`.

#### Scenario: Valid batch-embed request returns 202

- **WHEN** `POST /api/admin/batch-embed` is called with valid source_ids that have PENDING chunks
- **THEN** the response status SHALL be 202
- **AND** the response SHALL contain `task_id`, `batch_job_id`, `chunk_count`, and `message`
- **AND** a `BackgroundTask` with type BATCH_EMBEDDING SHALL exist in PostgreSQL
- **AND** a `BatchJob` with status pending SHALL exist in PostgreSQL

#### Scenario: Sources with no PENDING chunks are rejected

- **WHEN** `POST /api/admin/batch-embed` is called with source_ids whose chunks are all INDEXED
- **THEN** the response status SHALL be 422

#### Scenario: Sources from different scopes are rejected

- **WHEN** `POST /api/admin/batch-embed` is called with source_ids belonging to different agent_id/knowledge_base_id scopes
- **THEN** the response status SHALL be 422

#### Scenario: Chunks spanning multiple snapshots are rejected

- **WHEN** `POST /api/admin/batch-embed` is called with source_ids whose PENDING chunks belong to different snapshot_ids
- **THEN** the response status SHALL be 422

#### Scenario: Non-existent source_id is rejected

- **WHEN** `POST /api/admin/batch-embed` is called with a source_id that does not exist
- **THEN** the response status SHALL be 422

#### Scenario: Source not in READY status is rejected

- **WHEN** `POST /api/admin/batch-embed` is called with a source_id whose status is PROCESSING
- **THEN** the response status SHALL be 422

---

### Requirement: Source-level dedup on batch-embed endpoint

Before accepting a batch-embed request, the system SHALL check for any existing in-flight `BatchJob` (status `pending` or `processing`) whose `source_ids` overlap with the requested source_ids (using array overlap `&&` operator). If an overlapping in-flight batch exists, the endpoint SHALL reject with 409 Conflict and message "Active batch already exists for these sources".

#### Scenario: Overlapping in-flight batch returns 409

- **WHEN** `POST /api/admin/batch-embed` is called with source_ids that overlap with an in-flight BatchJob
- **THEN** the response status SHALL be 409
- **AND** the response message SHALL indicate an active batch already exists

#### Scenario: No overlapping batch proceeds normally

- **WHEN** `POST /api/admin/batch-embed` is called with source_ids that have no overlapping in-flight batches
- **THEN** the endpoint SHALL proceed to create the BatchJob and enqueue the task

---

### Requirement: GET /api/admin/batch-jobs endpoint

The system SHALL provide a `GET /api/admin/batch-jobs` endpoint that lists batch jobs with optional filtering. The endpoint SHALL accept query parameters: `status`, `operation_type`, `limit`, `offset`. The response SHALL contain `items` (array of batch job summaries) and `total` (integer count). Each item SHALL include: `id`, `operation_type`, `status`, `item_count`, `processed_count`, `succeeded_count`, `failed_count`, `created_at`, `last_polled_at`.

#### Scenario: List batch jobs returns paginated results

- **WHEN** `GET /api/admin/batch-jobs` is called with `limit=10&offset=0`
- **THEN** the response SHALL contain up to 10 items and a `total` count

#### Scenario: Filter by status

- **WHEN** `GET /api/admin/batch-jobs?status=processing` is called
- **THEN** all returned items SHALL have status `processing`

#### Scenario: Empty list returns zero items

- **WHEN** `GET /api/admin/batch-jobs` is called and no batch jobs exist
- **THEN** `items` SHALL be an empty array and `total` SHALL be 0

---

### Requirement: GET /api/admin/batch-jobs/:id endpoint

The system SHALL provide a `GET /api/admin/batch-jobs/{batch_job_id}` endpoint that returns detailed batch job information including all fields and the current `result_metadata` payload.

#### Scenario: Existing batch job returns full detail

- **WHEN** `GET /api/admin/batch-jobs/{id}` is called with a valid batch job ID
- **THEN** the response status SHALL be 200
- **AND** the response SHALL include all BatchJob fields including `result_metadata`

#### Scenario: Non-existent batch job returns 404

- **WHEN** `GET /api/admin/batch-jobs/{id}` is called with a UUID that does not exist
- **THEN** the response status SHALL be 404

---

### Requirement: poll_active_batches cron task

The system SHALL register a `poll_active_batches` cron function in arq WorkerSettings that runs every `batch_poll_interval_seconds` (default 30). The cron task SHALL query all `BatchJob` records with status `processing`, call `BatchOrchestrator.poll_and_complete(session, *, batch_job)` for each, and log results. When no active batches exist, the single SELECT query SHALL return empty with no API calls and negligible cost. On batch completion (Gemini SUCCEEDED), the task SHALL trigger result application via the orchestrator.

#### Scenario: Cron polls processing batches

- **WHEN** `poll_active_batches` runs and 2 batch jobs have status `processing`
- **THEN** the cron task SHALL call `poll_and_complete()` for each of the 2 batch jobs

#### Scenario: No active batches results in no API calls

- **WHEN** `poll_active_batches` runs and no batch jobs have status `processing`
- **THEN** only a single SELECT query SHALL execute
- **AND** no Gemini API calls SHALL be made

#### Scenario: Completed batch triggers result application

- **WHEN** `poll_active_batches` polls a batch and Gemini reports SUCCEEDED
- **THEN** the orchestrator SHALL parse results, upsert embeddings to Qdrant, update chunk statuses, and finalize related records

#### Scenario: Failed batch is marked failed

- **WHEN** `poll_active_batches` polls a batch and Gemini reports FAILED
- **THEN** `BatchJob.status` SHALL be set to `failed`
- **AND** `BatchJob.error_message` SHALL be populated
- **AND** all chunks SHALL remain with status PENDING
- **AND** the linked `BackgroundTask` SHALL be set to FAILED

---

### Requirement: process_batch_embed worker task

The system SHALL provide a `process_batch_embed` arq task that picks up an existing `BatchJob` (created synchronously by the API handler) and submits it to Gemini. The task SHALL load the `BackgroundTask`, load the associated `BatchJob`, read the ordered `chunk_ids` from `BatchJob.result_metadata`, load those exact chunk rows, verify they are still `PENDING`, and call `BatchOrchestrator.submit_to_gemini()` with the caller-loaded `texts` and `chunk_ids`. The task SHALL NOT create a new `BatchJob` — it only submits the existing one. After submission, the task stays in PROCESSING state; the `poll_active_batches` cron completes the lifecycle.

#### Scenario: Worker submits existing BatchJob to Gemini

- **WHEN** `process_batch_embed` is invoked with a task_id
- **THEN** it SHALL load the BackgroundTask and its associated BatchJob
- **AND** call `submit_to_gemini()` on the existing BatchJob
- **AND** the BackgroundTask SHALL remain in PROCESSING status

#### Scenario: Worker does not create a new BatchJob

- **WHEN** `process_batch_embed` executes
- **THEN** no new `BatchJob` records SHALL be created in PostgreSQL
- **AND** only the existing BatchJob (created by the API handler) SHALL be used

---

### Requirement: Batch configuration settings

The system SHALL add three configuration settings to `app/core/config.py`: `batch_embed_chunk_threshold` (int, default 50) controlling the chunk count above which per-source ingestion auto-switches to the Batch API, `batch_poll_interval_seconds` (int, default 30) controlling the cron poll interval for active batch jobs, and `batch_max_items_per_request` (int, default 1000) controlling the maximum items per single Gemini batch submission.

#### Scenario: Default threshold is 50

- **WHEN** the `batch_embed_chunk_threshold` setting is not overridden
- **THEN** its value SHALL be 50

#### Scenario: Default poll interval is 30 seconds

- **WHEN** the `batch_poll_interval_seconds` setting is not overridden
- **THEN** its value SHALL be 30

#### Scenario: Default max items per request is 1000

- **WHEN** the `batch_max_items_per_request` setting is not overridden
- **THEN** its value SHALL be 1000

#### Scenario: Settings are configurable via environment

- **WHEN** `BATCH_EMBED_CHUNK_THRESHOLD` environment variable is set to 100
- **THEN** the `batch_embed_chunk_threshold` setting SHALL be 100

---

### Requirement: Batch jobs schema extension

The existing `batch_jobs` table SHALL be extended via Alembic migration with the following columns: `snapshot_id` (UUID, nullable), `source_ids` (UUID ARRAY, nullable), `background_task_id` (UUID FK to background_tasks.id, nullable), `request_count` (INTEGER, nullable), `succeeded_count` (INTEGER, nullable), `failed_count` (INTEGER, nullable), `result_metadata` (JSONB, nullable), `last_polled_at` (TIMESTAMP with timezone, nullable). A GIN index SHALL be added on `batch_jobs.source_ids` to optimize the array overlap (`&&`) query used in source-level dedup.

#### Scenario: Migration adds new columns

- **WHEN** the Alembic migration is applied
- **THEN** the `batch_jobs` table SHALL contain all new columns with correct types and nullability

#### Scenario: GIN index exists on source_ids

- **WHEN** the migration is applied and table indexes are inspected
- **THEN** a GIN index SHALL exist on `batch_jobs.source_ids`

#### Scenario: Foreign key links to background_tasks

- **WHEN** a BatchJob is created with a `background_task_id` referencing a valid BackgroundTask
- **THEN** the FK constraint SHALL be satisfied

---

## Test Coverage

### CI tests (deterministic, mocked external services)

The following stable behavior MUST be covered by CI tests before archive:

- **BatchEmbeddingClient unit tests**: mock `google-genai` SDK. Verify create batch, poll status, parse results. Cover all Gemini state-to-BatchStatus mappings. Verify retry on 429/5xx, no retry on 400. Verify SDK types do not leak across boundary.
- **BatchOrchestrator unit tests**: mock client + DB. Verify submit flow (chunk aggregation, Gemini call, BatchJob update). Verify dedup guard (existing in-flight batch skips creation). Verify result application (all succeed, partial failure, all fail). Verify finalization of Document/DocumentVersion/EmbeddingProfile/KnowledgeSnapshot/BackgroundTask.
- **Batch-embed endpoint integration tests with real PG**: verify 202 response with correct fields. Verify BatchJob created synchronously. Verify validation (non-existent source, wrong status, no PENDING chunks, cross-scope, multi-snapshot). Verify source-level dedup returns 409.
- **Batch jobs list/detail endpoint tests**: verify pagination, filtering, 404 for non-existent.
- **poll_active_batches unit tests**: verify cron polls processing batches, no API calls when empty, completion triggers result application.
- **process_batch_embed unit tests**: verify worker loads existing BatchJob, calls submit_to_gemini, does not create new BatchJob.
- **Configuration tests**: verify default values and environment variable override for all three settings.
- **Migration tests**: verify new columns, GIN index, FK constraint on `batch_jobs`.

### Evals (non-CI, real providers)

- Smoke test: submit small batch (5 chunks) to real Gemini Batch API, verify embeddings match interactive API output.
- Cost verification: compare billing for batch vs interactive for same payload.
- Latency observation: measure actual batch completion time vs SLO.

---

## ADDED Requirements

### Requirement: Parent-aware payload parity between immediate and batch embedding

For story S9-02, Gemini Batch embedding SHALL preserve the same parent-aware child payload contract as immediate embedding. Batch submission SHALL continue to embed child-based text, and batch completion SHALL rebuild the Qdrant child payload using the persisted parent metadata from PostgreSQL.

#### Definitions

- **Qualifying long-form document:** a Path B or Path C source whose parsed child chunks meet both configured hierarchy thresholds after initial flat chunking: total parsed token count greater than or equal to `PARENT_CHILD_MIN_DOCUMENT_TOKENS` and child chunk count greater than or equal to `PARENT_CHILD_MIN_FLAT_CHUNKS`. Current defaults are `1500` tokens and `6` child chunks. Structural anchors improve grouping but are not required.
- **Non-qualifying flat source:** any source that stays below either hierarchy threshold or does not enter the Path B / Path C hierarchy flow. Its batch payload keeps the fixed parent-aware field set, but every parent field is null.

#### Parent-aware payload contract

The parent-aware child payload contract uses the same flat Qdrant child payload fields in both immediate and Gemini Batch flows. For qualifying long-form documents, the rebuilt child payload SHALL contain:

- `parent_id: string | null` (`UUID` serialized as string)
- `parent_text_content: string | null`
- `parent_token_count: integer | null`
- `parent_anchor_page: integer | null`
- `parent_anchor_chapter: string | null`
- `parent_anchor_section: string | null`
- `parent_anchor_timecode: string | null`

The minimal PostgreSQL schema mapping for these fields is:

- `chunks.parent_id -> chunk_parents.id`
- `chunk_parents.text_content -> parent_text_content`
- `chunk_parents.token_count -> parent_token_count`
- `chunk_parents.anchor_page -> parent_anchor_page`
- `chunk_parents.anchor_chapter -> parent_anchor_chapter`
- `chunk_parents.anchor_section -> parent_anchor_section`
- `chunk_parents.anchor_timecode -> parent_anchor_timecode`

Example qualifying child payload in Qdrant:

```json
{
  "chunk_id": "0195c0b1-6f6d-7bd9-9d5d-7b95d0205c55",
  "text_content": "Matched child excerpt",
  "parent_id": "0195c0b1-71b2-7c24-b5a9-4f20d5dc57a5",
  "parent_text_content": "Full parent section text",
  "parent_token_count": 1180,
  "parent_anchor_page": 24,
  "parent_anchor_chapter": "Chapter 3",
  "parent_anchor_section": "Retrieval",
  "parent_anchor_timecode": null
}
```

Example non-qualifying flat child payload in Qdrant:

```json
{
  "chunk_id": "0195c0b1-6f6d-7bd9-9d5d-7b95d0205c55",
  "text_content": "Flat child excerpt",
  "parent_id": null,
  "parent_text_content": null,
  "parent_token_count": null,
  "parent_anchor_page": null,
  "parent_anchor_chapter": null,
  "parent_anchor_section": null,
  "parent_anchor_timecode": null
}
```

#### Scenario: Batch submission keeps child-based embedding input

- **WHEN** a qualifying long-form document is routed through Gemini Batch embedding
- **THEN** the submitted embedding text SHALL remain the child-based embedding input used by the immediate path
- **AND** parent text SHALL NOT replace the child embedding input

#### Scenario: Batch completion rebuilds parent-aware child payload

- **WHEN** Gemini Batch embedding completes for qualifying long-form child chunks
- **THEN** batch result application SHALL rebuild Qdrant child points with the same parent metadata fields used by immediate embedding

#### Scenario: Batch completion handles missing parent metadata

- **WHEN** Gemini Batch completion needs to rebuild a qualifying child payload and the referenced parent metadata cannot be loaded from PostgreSQL
- **THEN** batch completion SHALL fail closed instead of writing a partial parent-aware child payload
- **AND** the `BatchJob` SHALL transition from `PROCESSING` to `FAILED`
- **AND** the linked ingestion `BackgroundTask` SHALL transition from `PROCESSING` to `FAILED`
- **AND** the failure metadata SHALL record the error message and completion timestamp

#### Scenario: Batch completion handles Qdrant update failures

- **WHEN** Gemini Batch completion rebuilds qualifying child payloads and the Qdrant upsert fails
- **THEN** batch completion SHALL perform best-effort cleanup for any child points attempted in that failing upsert
- **AND** the `BatchJob` SHALL transition from `PROCESSING` to `FAILED`
- **AND** the linked ingestion `BackgroundTask` SHALL transition from `PROCESSING` to `FAILED`
- **AND** no automatic retry or backoff SHALL be introduced by this change
- **AND** the failure SHALL be recorded in the batch/job error metadata for later operator diagnosis

#### Scenario: Immediate and batch payload contracts stay aligned

- **WHEN** the same qualifying long-form source is indexed once through immediate embedding and once through Gemini Batch embedding
- **THEN** both execution modes SHALL produce the same parent-aware child payload shape in Qdrant

#### Scenario: Flat chunks keep the same fixed payload shape in batch mode

- **WHEN** a non-qualifying flat source is indexed through Gemini Batch embedding
- **THEN** the resulting child payload SHALL use the same fixed parent-aware field set as the immediate path
- **AND** all parent metadata fields SHALL be null
