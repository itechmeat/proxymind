## ADDED Requirements

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

---

## Test Coverage

### CI tests (deterministic)

The following stable behavior MUST be covered by CI tests before archive:

- **Deleted source guard**: enqueue task for a source, soft-delete the source, run the worker -> task is FAILED with "Source was deleted before processing completed".
- **Non-deleted source passes guard**: enqueue task for a PENDING source -> guard passes, pipeline proceeds.
- **Guard placement**: verify the status check occurs before any service initialization or file download.
