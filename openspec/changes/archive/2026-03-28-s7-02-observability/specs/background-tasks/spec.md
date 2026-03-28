## MODIFIED Requirements

### Requirement: arq worker infrastructure

**[Modified by S7-02]** The system SHALL provide an arq worker entry point at `app/workers/main.py` defining `WorkerSettings` with: `functions` (registered task handlers), `redis_settings` (from application configuration), `max_jobs` (default 10), `job_timeout` (default 600 seconds). The worker SHALL create its own async DB engine and session factory via the arq `on_startup` hook and dispose the engine via `on_shutdown`. The worker SHALL NOT share a connection pool with the API process. The `on_startup` hook SHALL also initialize OpenTelemetry telemetry with `service_name="proxymind-worker"`. The `on_shutdown` hook SHALL call `shutdown_telemetry()` before engine disposal and SHALL still dispose the engine even if telemetry shutdown raises.

#### Scenario: WorkerSettings is importable

- **WHEN** `from app.workers.main import WorkerSettings` is executed
- **THEN** the import SHALL succeed
- **AND** `WorkerSettings.functions` SHALL contain the ingestion task handler

#### Scenario: Worker creates independent DB engine

- **WHEN** the arq worker starts via `on_startup`
- **THEN** a new async DB engine and session factory SHALL be created
- **AND** they SHALL be stored in the arq context dict under `db_engine` and `db_session_factory`
- **AND** the implementation MAY keep `session_factory` as a compatibility alias for existing task code

#### Scenario: Worker disposes DB engine on shutdown

- **WHEN** the arq worker shuts down via `on_shutdown`
- **THEN** `engine.dispose()` SHALL be called

#### Scenario: Worker initializes telemetry on startup

- **WHEN** the arq worker starts via `on_startup`
- **THEN** `init_telemetry()` SHALL be called with `enabled=settings.otel_enabled`, `endpoint=settings.otel_exporter_otlp_endpoint`, and `service_name="proxymind-worker"`

#### Scenario: Worker shuts down telemetry on shutdown

- **WHEN** the arq worker shuts down via `on_shutdown`
- **THEN** `shutdown_telemetry()` SHALL be called before `engine.dispose()`
- **AND** a telemetry shutdown exception SHALL be logged and SHALL NOT prevent `engine.dispose()`

---

### Requirement: Correlation ID propagation from API to worker

**[Added by S7-02]** When the API enqueues an arq job, it SHALL pass `correlation_id=request_id_var.get()` as a regular keyword argument in the job payload. The `correlation_id` value is the current request's `X-Request-ID` from contextvars. arq serializes kwargs into the job payload; the worker task receives `correlation_id` as a function kwarg (not via `ctx` -- arq's ctx dict is worker-constructed only).

#### Scenario: API passes correlation_id when enqueuing

- **WHEN** the API enqueues an arq job (e.g., ingestion task) during an HTTP request
- **THEN** the enqueue call SHALL include `correlation_id=request_id_var.get()` as a keyword argument
- **AND** the value SHALL be the current request's `X-Request-ID`

#### Scenario: correlation_id is None outside request context

- **WHEN** the API enqueues an arq job outside an HTTP request context (e.g., during startup)
- **THEN** `correlation_id` SHALL be `None` (the default of `request_id_var`)

---

### Requirement: Worker task correlation ID binding

**[Added by S7-02]** Task functions SHALL accept an optional `correlation_id` keyword argument. When present, the worker SHALL bind it to structlog context and to `request_id_var` for the duration of the task execution via a scoped helper/context manager. When absent (e.g., for cron-triggered tasks), the worker SHALL generate its own UUID and bind that instead.

#### Scenario: Task receives and binds correlation_id

- **WHEN** the worker executes a task with `correlation_id="abc-123"` in its kwargs
- **THEN** `request_id_var` SHALL be set to `"abc-123"` for the task duration
- **AND** structlog entries emitted during the task SHALL include `request_id="abc-123"`

#### Scenario: Task without correlation_id generates its own

- **WHEN** the worker executes a task without a `correlation_id` kwarg (or with `correlation_id=None`)
- **THEN** the worker SHALL generate a new UUID
- **AND** `request_id_var` SHALL be set to the generated UUID for the task duration
- **AND** structlog entries SHALL include the generated `request_id`

#### Scenario: correlation_id scoped to single task

- **WHEN** the worker executes task A with `correlation_id="aaa"` then task B with `correlation_id="bbb"`
- **THEN** during task A, `request_id_var` SHALL be `"aaa"`
- **AND** during task B, `request_id_var` SHALL be `"bbb"`
- **AND** the previous task's correlation_id SHALL NOT leak

#### Scenario: correlation_id is cleared after task completion

- **WHEN** a task finishes, whether successfully or with an error
- **THEN** the worker SHALL clear the request-scoped logging context before the next task starts
- **AND** the completed task's correlation_id SHALL NOT affect subsequent tasks

---

## Test Coverage

### CI tests (deterministic)

- **Worker on_startup telemetry test**: mock `init_telemetry`, verify it is called with `service_name="proxymind-worker"` during `on_startup`.
- **Worker on_shutdown telemetry test**: mock `shutdown_telemetry`, verify it is called during `on_shutdown` before engine disposal.
- **Correlation ID enqueue test**: mock `arq_pool.enqueue_job`, trigger an API action that enqueues a job, verify `correlation_id` kwarg is passed.
- **Correlation ID binding test**: simulate a task invocation with `correlation_id="test-id"`, verify `request_id_var.get()` returns `"test-id"` during execution.
- **Correlation ID generation test**: simulate a task invocation without `correlation_id`, verify `request_id_var.get()` returns a valid UUID.
