## ADDED Requirements

### Requirement: AuditService writes audit records for every chat response

The system SHALL provide an `AuditService` class in `backend/app/services/audit.py` that writes a record to the `audit_logs` table after every chat response finalization. The `audit_logs` table already exists (migration 001). A new Alembic migration SHALL add a `status` column (`String(32)`, nullable) to distinguish terminal states. The `AuditService` SHALL expose a single async method `log_response()` that accepts all required fields via keyword arguments and persists an `AuditLog` record. The method SHALL commit the record to the database and increment the `audit_logs_total` Prometheus counter. On success, a structlog info event `audit.response_logged` SHALL be emitted with `audit_id`, `session_id`, `message_id`, and `snapshot_id`.

#### Scenario: Audit record created with all fields on complete response

- **WHEN** `AuditService.log_response()` is called after a successful chat response
- **THEN** an `AuditLog` record SHALL be persisted with all of the following fields:
  - `agent_id` (UUID)
  - `session_id` (UUID)
  - `message_id` (UUID)
  - `snapshot_id` (UUID or null)
  - `source_ids` (list of UUIDs)
  - `config_commit_hash` (string)
  - `config_content_hash` (string)
  - `model_name` (string or null)
  - `token_count_prompt` (integer)
  - `token_count_completion` (integer)
  - `retrieval_chunks_count` (integer)
  - `latency_ms` (integer)
  - `status` (string: `"complete"`, `"partial"`, or `"failed"` — distinguishes the terminal state of the response)
- **AND** `await db.commit()` SHALL be called

#### Scenario: Audit record created for partial response (disconnect)

- **WHEN** `AuditService.log_response()` is called after a client disconnect during streaming
- **THEN** an `AuditLog` record SHALL be persisted
- **AND** `status` SHALL be `"partial"`
- **AND** `latency_ms` SHALL be 0 (unknown at disconnect time)
- **AND** `token_count_prompt` and `token_count_completion` MAY be 0 or partial values

#### Scenario: Audit record created for failed response

- **WHEN** `AuditService.log_response()` is called after a chat response failure (LLM error, timeout)
- **THEN** an `AuditLog` record SHALL be persisted with available fields
- **AND** `model_name` MAY be null if the LLM was never called

#### Scenario: Prometheus counter incremented on audit write

- **WHEN** `AuditService.log_response()` successfully persists a record
- **THEN** the `audit_logs_total` Prometheus counter SHALL be incremented by 1

#### Scenario: Structlog event emitted on audit write

- **WHEN** `AuditService.log_response()` successfully persists a record
- **THEN** a structlog info event `audit.response_logged` SHALL be emitted
- **AND** the log entry SHALL include `audit_id`, `session_id`, `message_id`, and `snapshot_id`

#### Scenario: Null snapshot_id accepted

- **WHEN** `AuditService.log_response()` is called with `snapshot_id=None` (e.g., session created before any snapshot)
- **THEN** the record SHALL be persisted with `snapshot_id` as null
- **AND** no error SHALL be raised

---

### Requirement: Config hashes sourced from PersonaContext

The `AuditService` SHALL receive `config_commit_hash` and `config_content_hash` as parameters. These values are already computed by `PersonaLoader` and available via `PersonaContext`. No new `ConfigHasher` service is needed. `config_commit_hash` is resolved from the `GIT_COMMIT_SHA` environment variable (set during Docker build). `config_content_hash` is a SHA-256 of sorted, concatenated contents of `persona/*.md` + `config/*.md`.

#### Scenario: Config hashes passed from ChatService to AuditService

- **WHEN** `ChatService._log_audit()` calls `AuditService.log_response()`
- **THEN** `config_commit_hash` SHALL be read from `message.config_commit_hash` (already persisted on the assistant message)
- **AND** `config_content_hash` SHALL be read from `message.config_content_hash`

#### Scenario: Empty config hashes when unavailable

- **WHEN** config hashes are not available (e.g., no persona loaded)
- **THEN** `config_commit_hash` and `config_content_hash` SHALL default to empty strings
- **AND** the audit record SHALL still be created

---

### Requirement: ChatService._log_audit private method

`ChatService` SHALL provide a private `_log_audit()` method that delegates to `AuditService.log_response()` with the correct field mapping from chat domain objects. When `_audit_service` is `None`, `_log_audit` SHALL be a no-op. When `AuditService.log_response()` raises an exception, `_log_audit` SHALL catch it, log an error event `audit.log_failed`, and SHALL NOT propagate the exception to the caller.

#### Scenario: _log_audit delegates to AuditService with correct field mapping

- **WHEN** `_log_audit()` is called with a `chat_session`, `message`, `snapshot_id`, `retrieved_chunks_count`, and `latency_ms`
- **THEN** it SHALL call `AuditService.log_response()` with:
  - `agent_id` from `chat_session.agent_id`
  - `session_id` from `chat_session.id`
  - `message_id` from `message.id`
  - `source_ids` from `message.source_ids` (or empty list if null)
  - `model_name` from `message.model_name`
  - `token_count_prompt` from `message.token_count_prompt` (or 0 if null)
  - `token_count_completion` from `message.token_count_completion` (or 0 if null)
  - `config_commit_hash` from `message.config_commit_hash` (or empty string if null)
  - `config_content_hash` from `message.config_content_hash` (or empty string if null)

#### Scenario: _log_audit is no-op when audit_service is None

- **WHEN** `ChatService` is instantiated with `audit_service=None`
- **AND** `_log_audit()` is called
- **THEN** the method SHALL return without error and without calling any external service

#### Scenario: _log_audit catches and logs exceptions

- **WHEN** `AuditService.log_response()` raises an exception (e.g., database error)
- **THEN** `_log_audit()` SHALL catch the exception
- **AND** SHALL log a structlog error event `audit.log_failed` with `session_id`, `message_id`, and the error description
- **AND** SHALL NOT propagate the exception

---

## Test Coverage

### CI tests (deterministic)

- **AuditService.log_response unit test**: mock `AsyncSession`, verify `session.add()` is called with an `AuditLog` record containing all expected fields, verify `session.commit()` is awaited.
- **AuditService Prometheus counter test**: verify `audit_logs_total` counter increments by 1 after a successful `log_response()` call.
- **_log_audit delegation test**: mock `AuditService`, verify `_log_audit` maps `chat_session` and `message` fields correctly to `log_response()` kwargs.
- **_log_audit no-op test**: verify `_log_audit` returns without error when `_audit_service` is `None`.
- **_log_audit exception handling test**: verify `_log_audit` catches exceptions from `AuditService.log_response()` and logs `audit.log_failed`.
