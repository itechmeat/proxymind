## MODIFIED Requirements

### Requirement: Pipeline orchestration in the worker task

The ingestion worker task (`app/workers/tasks/ingestion.py`) SHALL replace the noop handler with a real pipeline that executes these stages in sequence: (1) Download source file from MinIO, (2) Parse and chunk via DoclingParser, (3) Persist draft snapshot + Document + DocumentVersion + Chunk records in PostgreSQL (Tx 1), (4) Generate embeddings via EmbeddingService, (5) Upsert vectors to Qdrant via QdrantService, (6) Finalize statuses and create EmbeddingProfile (Tx 2). The worker task IS the orchestrator; there SHALL NOT be a separate Pipeline abstraction class.

**[MODIFIED by S2-03]** Stage 3 (Persist) SHALL use `ensure_draft_or_rebind` to acquire a FOR UPDATE lock on the snapshot row before persisting any chunks. The lock SHALL be held through the chunk insert and transaction commit. If the snapshot is no longer DRAFT (published concurrently), the worker SHALL rebind to a new draft via the same method.

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

**[ADDED by S2-03]** Before persisting chunks in Stage 3 (Tx 1), the ingestion worker MUST call `SnapshotService.ensure_draft_or_rebind(session, snapshot_id, agent_id, knowledge_base_id)` to obtain a FOR UPDATE-locked DRAFT snapshot. The worker SHALL use the returned snapshot's ID for all chunk records. The FOR UPDATE lock SHALL be held through the chunk insert and the transaction commit. The lock is released when the transaction commits.

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

The pipeline SHALL use two distinct transaction scopes. Tx 1 (Stage 3) SHALL persist the draft snapshot, Document, DocumentVersion, and Chunk records, and COMMIT before any external API calls. **[MODIFIED by S2-03]** Tx 1 SHALL acquire a FOR UPDATE lock on the snapshot row via `ensure_draft_or_rebind` before inserting chunks and hold it through the commit. Tx 2 (Stage 6) SHALL, only after successful Qdrant upsert, update Chunk statuses to INDEXED; update DocumentVersion, Document, and Source to READY; create the EmbeddingProfile; and mark the task COMPLETE.

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

## Test Coverage

### CI tests (deterministic, mocked external services)

The following stable behavior MUST be covered by CI tests before archive:

- **DoclingParser unit tests**: mock Docling DocumentConverter and HybridChunker. Verify chunk extraction, anchor metadata mapping, token counting. Cover edge cases: empty document, single-paragraph document, document with heading hierarchy.
- **EmbeddingService unit tests**: mock GenAI SDK. Verify batching logic (texts split into groups of `embedding_batch_size`), retry behavior on 429/5xx, dimension validation.
- **Pipeline orchestration unit tests**: mock all services (DoclingParser, EmbeddingService, QdrantService, StorageService, SnapshotService). Verify correct call sequence, progress updates, status transitions for Source/Document/DocumentVersion/Chunk, error propagation and failure cleanup, draft snapshot auto-creation, result_metadata population.
- **Integration tests with real PG**: run the pipeline with mocked GenAI and real Docling (local library for MD/TXT). Verify all PG records are created with correct statuses, relationships, and field values.
- **Snapshot locking integration tests with real PG** [ADDED by S2-03]: verify that the ingestion worker calls `ensure_draft_or_rebind` before chunk persistence. Verify that chunks are inserted under the FOR UPDATE lock. Verify the rebind scenario: when the snapshot has been published between `get_or_create_draft` and chunk insert, the worker rebinds to a new draft and the published snapshot receives no new chunks.

### Evals (non-CI, real providers)

- Embedding quality evaluation with real Gemini Embedding 2 calls is out of scope for CI. Manual verification covers: upload MD file, verify chunks in PG, verify vectors in Qdrant, vector search returns results.
