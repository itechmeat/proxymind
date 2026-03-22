## MODIFIED Requirements

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
