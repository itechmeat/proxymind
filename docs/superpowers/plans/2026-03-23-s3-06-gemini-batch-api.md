# S3-06: Gemini Batch API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Gemini Batch API support for bulk embedding operations — reducing costs by 50% for large-scale ingestion.

**Architecture:** Two entry points — explicit bulk endpoint (`POST /api/admin/batch-embed`) and auto-threshold for large per-source ingestion. Both use the same `BatchEmbeddingClient` → `BatchOrchestrator` → Qdrant pipeline. Polling via arq cron task.

**Tech Stack:** Python 3.14+, FastAPI, SQLAlchemy 2.0+, Alembic, arq, google-genai SDK, Qdrant, PostgreSQL, pytest

**Spec:** `docs/superpowers/specs/2026-03-23-s3-06-gemini-batch-api-design.md`

**Architectural scope note:** This story extends the worker/task model significantly — new task type (`BATCH_EMBEDDING`), new worker startup services (`BatchEmbeddingClient`, `BatchOrchestrator`), new cron job, and modifications to the ingestion finalization invariants. It is not a localized "add batch client" change — it touches the task lifecycle, DI graph, and state machine of sources/chunks/snapshots. Each task is structured to be independently testable, but the implementer should understand the full picture.

**Pre-implementation:** Read `docs/development.md` before writing any code. Self-review against it after.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/app/db/models/enums.py` | Add `BATCH_EMBEDDING` to `BackgroundTaskType` |
| Modify | `backend/app/db/models/operations.py` | Extend `BatchJob` with new columns |
| Create | `backend/migrations/versions/NNN_s3_06_batch_api.py` | Alembic migration |
| Modify | `backend/app/core/config.py` | Add batch settings |
| Create | `backend/app/services/batch_embedding.py` | Gemini Batch API client |
| Create | `backend/app/services/batch_orchestrator.py` | Batch lifecycle orchestration |
| Create | `backend/app/api/batch_schemas.py` | Pydantic schemas for batch endpoints |
| Modify | `backend/app/api/admin.py` | `skip_embedding` param + batch-embed + batch-jobs endpoints |
| Modify | `backend/app/api/dependencies.py` | Dependency providers for new services |
| Modify | `backend/app/api/schemas.py` | Add `skip_embedding` to upload metadata if needed |
| Modify | `backend/app/services/source.py` | Pass `skip_embedding` through to task |
| Modify | `backend/app/workers/tasks/handlers/path_b.py` | Skip embed+Qdrant when `skip_embedding=true` |
| Modify | `backend/app/workers/tasks/handlers/path_a.py` | Skip embed+Qdrant when `skip_embedding=true` |
| Modify | `backend/app/workers/tasks/ingestion.py` | `skip_embedding` + auto-threshold + `BatchSubmittedResult` |
| Modify | `backend/app/workers/tasks/pipeline.py` | Add `SkipEmbeddingResult` / `BatchSubmittedResult` types |
| Create | `backend/app/workers/tasks/batch_embed.py` | `process_batch_embed` arq task |
| Create | `backend/app/workers/tasks/batch_poll.py` | `poll_active_batches` arq cron |
| Modify | `backend/app/workers/main.py` | Register new tasks + cron + BatchEmbeddingClient in ctx |
| Modify | `backend/tests/unit/test_task_status.py` | Update expected enum members |
| Create | `backend/tests/unit/services/test_batch_embedding.py` | BatchEmbeddingClient unit tests |
| Create | `backend/tests/unit/services/test_batch_orchestrator.py` | BatchOrchestrator unit tests |
| Create | `backend/tests/unit/test_batch_embed_api.py` | Batch endpoint unit tests |
| Create | `backend/tests/unit/workers/test_skip_embedding.py` | Skip-embedding flow unit tests |
| Create | `backend/tests/unit/workers/test_batch_poll.py` | Poll cron unit tests |
| Create | `backend/tests/integration/test_batch_flow.py` | End-to-end batch integration tests |

---

## Task 1: Schema Extension — Enums + Migration + Config

**Files:**
- Modify: `backend/app/db/models/enums.py:127-128`
- Modify: `backend/app/db/models/operations.py:36-58`
- Create: `backend/migrations/versions/NNN_s3_06_batch_api.py`
- Modify: `backend/app/core/config.py:48-49`
- Modify: `backend/tests/unit/test_task_status.py:4-5`

- [ ] **Step 1: Update BackgroundTaskType enum**

In `backend/app/db/models/enums.py`, add `BATCH_EMBEDDING`:

```python
class BackgroundTaskType(StrEnum):
    INGESTION = "INGESTION"
    BATCH_EMBEDDING = "BATCH_EMBEDDING"
```

- [ ] **Step 2: Update test_task_status.py**

```python
def test_background_task_type_enum_values() -> None:
    assert [member.value for member in BackgroundTaskType] == ["INGESTION", "BATCH_EMBEDDING"]
```

- [ ] **Step 3: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/unit/test_task_status.py -v`
Expected: PASS

- [ ] **Step 4: Extend BatchJob model with new columns**

In `backend/app/db/models/operations.py`, add columns to `BatchJob`:

```python
from sqlalchemy import ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

class BatchJob(PrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "batch_jobs"

    agent_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    knowledge_base_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    batch_operation_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation_type: Mapped[BatchOperationType] = mapped_column(
        pg_enum(BatchOperationType, name="batch_operation_type_enum"),
        nullable=False,
    )
    status: Mapped[BatchStatus] = mapped_column(
        pg_enum(BatchStatus, name="batch_status_enum"),
        nullable=False,
    )
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # --- S3-06: New columns ---
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    source_ids: Mapped[list[uuid.UUID] | None] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=True,
    )
    background_task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("background_tasks.id"), nullable=True, index=True,
    )
    request_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    succeeded_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    failed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(nullable=True)
```

- [ ] **Step 5: Add batch settings to config**

In `backend/app/core/config.py`, add after `min_dense_similarity`:

```python
batch_embed_chunk_threshold: int = Field(default=50, ge=1)
batch_poll_interval_seconds: int = Field(default=30, ge=5)
batch_max_items_per_request: int = Field(default=1000, ge=1)
```

- [ ] **Step 6: Write unit test for new config fields**

In `backend/tests/unit/test_config.py`, add (follows existing `_base_settings()` pattern):

```python
def test_batch_config_defaults() -> None:
    settings = Settings(**_base_settings())
    assert settings.batch_embed_chunk_threshold == 50
    assert settings.batch_poll_interval_seconds == 30
    assert settings.batch_max_items_per_request == 1000
```

- [ ] **Step 7: Run test**

Run: `cd backend && python -m pytest tests/unit/test_config.py -v -k batch`
Expected: PASS

- [ ] **Step 8: Create Alembic migration**

Run: `cd backend && alembic revision --autogenerate -m "s3_06_batch_api_extend_batch_jobs"`

Then manually edit the generated migration to:
1. Add the `ALTER TYPE` for `BATCH_EMBEDDING` enum value in a separate step with autocommit:

```python
def upgrade() -> None:
    # Must run outside transaction for PostgreSQL native enum
    op.execute("ALTER TYPE background_task_type_enum ADD VALUE IF NOT EXISTS 'BATCH_EMBEDDING'")

    op.add_column("batch_jobs", sa.Column("snapshot_id", sa.UUID(), nullable=True))
    op.add_column("batch_jobs", sa.Column("source_ids", sa.ARRAY(sa.UUID()), nullable=True))
    op.add_column("batch_jobs", sa.Column("background_task_id", sa.UUID(), nullable=True))
    op.add_column("batch_jobs", sa.Column("request_count", sa.Integer(), nullable=True))
    op.add_column("batch_jobs", sa.Column("succeeded_count", sa.Integer(), nullable=True))
    op.add_column("batch_jobs", sa.Column("failed_count", sa.Integer(), nullable=True))
    op.add_column("batch_jobs", sa.Column("result_metadata", sa.dialects.postgresql.JSONB(), nullable=True))
    op.add_column("batch_jobs", sa.Column("last_polled_at", sa.DateTime(), nullable=True))

    op.create_index("ix_batch_jobs_snapshot_id", "batch_jobs", ["snapshot_id"])
    op.create_index("ix_batch_jobs_background_task_id", "batch_jobs", ["background_task_id"])
    op.create_index("ix_batch_jobs_source_ids", "batch_jobs", ["source_ids"], postgresql_using="gin")
    op.create_foreign_key(
        "fk_batch_jobs_background_task_id",
        "batch_jobs", "background_tasks",
        ["background_task_id"], ["id"],
    )
```

**Important:** The `ALTER TYPE ... ADD VALUE` cannot run inside a transaction. Use `op.execute()` directly — Alembic handles this if the migration runs with autocommit for DDL, or add at the top of upgrade: `from alembic import context; context.get_context().connection.execution_options(isolation_level="AUTOCOMMIT")` before the ALTER TYPE.

- [ ] **Step 9: Run migration**

Run: `cd backend && alembic upgrade head`
Expected: Migration applies successfully

- [ ] **Step 10: Run existing integration tests to verify no regression**

Run: `cd backend && python -m pytest tests/integration/test_background_task_migration.py -v`
Expected: PASS

- [ ] **Step 11: Commit**

```
feat(batch): extend batch_jobs schema and add BATCH_EMBEDDING task type (S3-06)
```

---

## Task 2: BatchEmbeddingClient — Gemini SDK Wrapper

**Files:**
- Create: `backend/app/services/batch_embedding.py`
- Create: `backend/tests/unit/services/test_batch_embedding.py`

**Prerequisite:** Before implementing, verify the `google-genai` SDK batch API shape. Check `from google.genai import types` for batch-related types. The SDK may use `client.batches.create()` or a different API. If the SDK doesn't support batch embedding directly, adapt the client to use whatever API is available (REST fallback or file-based). Document findings in a code comment.

- [ ] **Step 1: Write failing tests for BatchEmbeddingClient**

```python
# backend/tests/unit/services/test_batch_embedding.py
from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.enums import BatchStatus


class TestBatchEmbeddingClient:
    def test_create_embedding_batch_returns_operation_name(self):
        """Submit a batch and get back an operation name."""
        from app.services.batch_embedding import BatchEmbeddingClient

        mock_client = MagicMock()
        mock_batch_response = SimpleNamespace(name="operations/batch-123")
        mock_client.batches.create.return_value = mock_batch_response

        client = BatchEmbeddingClient(
            model="gemini-embedding-2-preview",
            dimensions=3072,
            client=mock_client,
        )
        texts = ["chunk text 1", "chunk text 2"]
        chunk_ids = [uuid.uuid7(), uuid.uuid7()]

        result = client.create_embedding_batch(texts, chunk_ids)

        assert result.operation_name == "operations/batch-123"
        assert result.item_count == 2
        mock_client.batches.create.assert_called_once()

    def test_get_batch_status_returns_mapped_status(self):
        from app.services.batch_embedding import BatchEmbeddingClient

        mock_client = MagicMock()
        mock_client.batches.get.return_value = SimpleNamespace(
            name="operations/batch-123",
            state="JOB_STATE_SUCCEEDED",
        )

        client = BatchEmbeddingClient(
            model="gemini-embedding-2-preview",
            dimensions=3072,
            client=mock_client,
        )
        status = client.get_batch_status("operations/batch-123")

        assert status.internal_status == BatchStatus.COMPLETE

    def test_map_gemini_state_to_batch_status(self):
        from app.services.batch_embedding import map_gemini_state

        assert map_gemini_state("JOB_STATE_SUCCEEDED") == BatchStatus.COMPLETE
        assert map_gemini_state("JOB_STATE_FAILED") == BatchStatus.FAILED
        assert map_gemini_state("JOB_STATE_ACTIVE") == BatchStatus.PROCESSING
        assert map_gemini_state("JOB_STATE_CANCELLED") == BatchStatus.CANCELLED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/services/test_batch_embedding.py -v`
Expected: ImportError — module not found

- [ ] **Step 3: Implement BatchEmbeddingClient**

Create `backend/app/services/batch_embedding.py`:

```python
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass

from google import genai
from google.genai import types

from app.db.models.enums import BatchStatus

# Mapping from Gemini batch job states to internal BatchStatus.
# Exact enum names verified against google-genai SDK.
# If SDK uses different names, update this mapping.
_GEMINI_STATE_MAP: dict[str, BatchStatus] = {
    "JOB_STATE_ACTIVE": BatchStatus.PROCESSING,
    "JOB_STATE_PENDING": BatchStatus.PROCESSING,
    "JOB_STATE_RUNNING": BatchStatus.PROCESSING,
    "JOB_STATE_SUCCEEDED": BatchStatus.COMPLETE,
    "JOB_STATE_FAILED": BatchStatus.FAILED,
    "JOB_STATE_EXPIRED": BatchStatus.FAILED,
    "JOB_STATE_CANCELLED": BatchStatus.CANCELLED,
}


def map_gemini_state(state: str) -> BatchStatus:
    return _GEMINI_STATE_MAP.get(state, BatchStatus.PROCESSING)


@dataclass(slots=True, frozen=True)
class BatchCreateResult:
    operation_name: str
    item_count: int


@dataclass(slots=True, frozen=True)
class BatchStatusResult:
    operation_name: str
    internal_status: BatchStatus
    raw_state: str


@dataclass(slots=True, frozen=True)
class BatchEmbeddingResult:
    chunk_id: uuid.UUID
    vector: list[float] | None
    error: str | None


class BatchEmbeddingClient:
    """Thin wrapper around google-genai batch API for embedding operations."""

    def __init__(
        self,
        *,
        model: str,
        dimensions: int,
        api_key: str | None = None,
        client: genai.Client | None = None,
    ) -> None:
        self._model = model
        self._dimensions = dimensions
        self._api_key = api_key
        self._client = client
        self._client_lock = threading.Lock()

    def create_embedding_batch(
        self,
        texts: list[str],
        chunk_ids: list[uuid.UUID],
    ) -> BatchCreateResult:
        """Submit a batch of embedding requests to Gemini.

        Each text is associated with a chunk_id for result mapping.
        The chunk_id is stored in the request's custom_id field.
        """
        client = self._get_client()

        # Build batch requests — each with a custom_id for result correlation.
        # NOTE: The exact API shape must be verified against the SDK.
        # This implementation assumes client.batches.create() accepts
        # a list of EmbedContentRequest-like objects.
        requests = []
        for text, chunk_id in zip(texts, chunk_ids, strict=True):
            requests.append(
                types.EmbedContentRequest(
                    model=self._model,
                    contents=[text],
                    config=types.EmbedContentConfig(
                        task_type="RETRIEVAL_DOCUMENT",
                        output_dimensionality=self._dimensions,
                    ),
                )
            )

        response = client.batches.create(
            model=self._model,
            src=requests,
            config=types.CreateBatchJobConfig(
                display_name=f"proxymind-embed-{uuid.uuid4().hex[:8]}",
            ),
        )

        return BatchCreateResult(
            operation_name=response.name,
            item_count=len(texts),
        )

    def get_batch_status(self, operation_name: str) -> BatchStatusResult:
        client = self._get_client()
        response = client.batches.get(name=operation_name)
        return BatchStatusResult(
            operation_name=response.name,
            internal_status=map_gemini_state(response.state),
            raw_state=response.state,
        )

    def get_batch_results(
        self,
        operation_name: str,
        chunk_ids: list[uuid.UUID],
    ) -> list[BatchEmbeddingResult]:
        """Retrieve results from a completed batch.

        Correlation strategy:
        1. If SDK supports custom_id per request, match by custom_id → chunk_id.
        2. Otherwise, use positional matching (same order as submission).
        3. ALWAYS validate: len(responses) == len(chunk_ids). If mismatch,
           mark all as failed rather than risk wrong chunk → vector mapping.

        chunk_ids MUST be the same ordered list stored in BatchJob.result_metadata
        at submission time — NOT re-queried from DB (order may differ).
        """
        client = self._get_client()
        response = client.batches.get(name=operation_name)

        results: list[BatchEmbeddingResult] = []
        responses = response.responses  # exact shape verified during SDK spike

        # Safety check: response count must match request count
        if len(responses) != len(chunk_ids):
            return [
                BatchEmbeddingResult(
                    chunk_id=cid,
                    vector=None,
                    error=f"Response count mismatch: expected {len(chunk_ids)}, got {len(responses)}",
                )
                for cid in chunk_ids
            ]

        for i, chunk_id in enumerate(chunk_ids):
            try:
                embedding = responses[i]
                values = list(embedding.embeddings[0].values)
                if len(values) != self._dimensions:
                    raise ValueError(
                        f"Dimension mismatch: expected {self._dimensions}, got {len(values)}"
                    )
                results.append(BatchEmbeddingResult(
                    chunk_id=chunk_id,
                    vector=values,
                    error=None,
                ))
            except (IndexError, AttributeError, TypeError, ValueError) as exc:
                results.append(BatchEmbeddingResult(
                    chunk_id=chunk_id,
                    vector=None,
                    error=str(exc),
                ))

        return results

    def _get_client(self) -> genai.Client:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    if not self._api_key:
                        raise ValueError("GEMINI_API_KEY is required for batch operations")
                    self._client = genai.Client(api_key=self._api_key)
        return self._client
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/unit/services/test_batch_embedding.py -v`
Expected: PASS (tests use mocked SDK client)

- [ ] **Step 5: Commit**

```
feat(batch): add BatchEmbeddingClient with Gemini SDK wrapper (S3-06)
```

---

## Task 3: BatchOrchestrator — Submit, Dedup, Apply

**Files:**
- Create: `backend/app/services/batch_orchestrator.py`
- Create: `backend/tests/unit/services/test_batch_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/services/test_batch_orchestrator.py
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models.enums import BatchOperationType, BatchStatus


class TestBatchOrchestratorSubmit:
    @pytest.mark.asyncio
    async def test_submit_to_gemini_calls_client_and_updates_batch_job(self):
        from app.services.batch_orchestrator import BatchOrchestrator

        existing_batch_job = SimpleNamespace(
            id=uuid.uuid7(),
            batch_operation_name=None,  # not yet submitted
            status=BatchStatus.PENDING,
            item_count=5,
            started_at=None,
        )
        mock_session = AsyncMock()
        mock_session.scalar = AsyncMock(return_value=existing_batch_job)
        mock_session.commit = AsyncMock()

        mock_client = MagicMock()
        mock_client.create_embedding_batch.return_value = SimpleNamespace(
            operation_name="operations/batch-abc",
            item_count=5,
        )

        orchestrator = BatchOrchestrator(batch_client=mock_client)
        result = await orchestrator.submit_to_gemini(
            session=mock_session,
            background_task_id=uuid.uuid7(),
            texts=[f"text {i}" for i in range(5)],
            chunk_ids=[uuid.uuid7() for _ in range(5)],
        )

        assert result.batch_operation_name == "operations/batch-abc"
        mock_client.create_embedding_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_submit_to_gemini_dedup_skips_if_already_submitted(self):
        from app.services.batch_orchestrator import BatchOrchestrator

        existing_batch_job = SimpleNamespace(
            id=uuid.uuid7(),
            batch_operation_name="operations/existing-123",  # already submitted
            status=BatchStatus.PROCESSING,
            item_count=5,
        )
        mock_session = AsyncMock()
        mock_session.scalar = AsyncMock(return_value=existing_batch_job)

        mock_client = MagicMock()

        orchestrator = BatchOrchestrator(batch_client=mock_client)
        result = await orchestrator.submit_to_gemini(
            session=mock_session,
            background_task_id=uuid.uuid7(),
            texts=["text"],
            chunk_ids=[uuid.uuid7()],
        )

        assert result.batch_operation_name == "operations/existing-123"
        assert result.is_existing is True
        mock_client.create_embedding_batch.assert_not_called()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd backend && python -m pytest tests/unit/services/test_batch_orchestrator.py -v`
Expected: ImportError

- [ ] **Step 3: Implement BatchOrchestrator**

Create `backend/app/services/batch_orchestrator.py`:

```python
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.enums import BatchOperationType, BatchStatus
from app.db.models.operations import BatchJob
from app.services.batch_embedding import BatchEmbeddingClient, BatchEmbeddingResult

logger = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class SubmitResult:
    batch_job_id: uuid.UUID
    batch_operation_name: str
    item_count: int
    is_existing: bool


class BatchOrchestrator:
    def __init__(self, *, batch_client: BatchEmbeddingClient) -> None:
        self._batch_client = batch_client

    async def submit_to_gemini(
        self,
        *,
        session: AsyncSession,
        background_task_id: uuid.UUID,
        texts: list[str],
        chunk_ids: list[uuid.UUID],
    ) -> SubmitResult:
        """Submit an existing BatchJob to Gemini.

        For the bulk endpoint: BatchJob is created synchronously in the API handler.
        For auto-threshold: BatchJob is created by create_batch_job_for_threshold().
        This method picks up the existing BatchJob and sends to Gemini.
        """
        # Dedup guard — find the existing BatchJob for this task
        batch_job = await session.scalar(
            select(BatchJob).where(
                BatchJob.background_task_id == background_task_id,
                BatchJob.status.in_([BatchStatus.PENDING, BatchStatus.PROCESSING]),
            ).limit(1)
        )
        if batch_job is None:
            raise RuntimeError(f"No pending BatchJob found for task {background_task_id}")

        # If already submitted (has operation_name), skip — dedup
        if batch_job.batch_operation_name:
            logger.info("batch.dedup.already_submitted", batch_job_id=str(batch_job.id))
            return SubmitResult(
                batch_job_id=batch_job.id,
                batch_operation_name=batch_job.batch_operation_name,
                item_count=batch_job.item_count or 0,
                is_existing=True,
            )

        # Call Gemini Batch API
        batch_job.started_at = datetime.now(UTC)
        try:
            create_result = self._batch_client.create_embedding_batch(texts, chunk_ids)
        except Exception as exc:
            batch_job.status = BatchStatus.FAILED
            batch_job.error_message = str(exc)
            batch_job.completed_at = datetime.now(UTC)
            await session.commit()
            raise

        # Update with Gemini operation name
        batch_job.batch_operation_name = create_result.operation_name
        batch_job.status = BatchStatus.PROCESSING
        await session.commit()

        logger.info(
            "batch.submitted",
            batch_job_id=str(batch_job.id),
            operation_name=create_result.operation_name,
            item_count=create_result.item_count,
        )

        return SubmitResult(
            batch_job_id=batch_job.id,
            batch_operation_name=create_result.operation_name,
            item_count=create_result.item_count,
            is_existing=False,
        )

    def create_batch_job_for_threshold(
        self,
        *,
        session: AsyncSession,
        agent_id: uuid.UUID,
        knowledge_base_id: uuid.UUID,
        snapshot_id: uuid.UUID,
        source_ids: list[uuid.UUID],
        background_task_id: uuid.UUID,
        chunk_ids: list[uuid.UUID],
        item_count: int,
    ) -> BatchJob:
        """Create BatchJob synchronously for auto-threshold path.

        For the bulk endpoint, BatchJob is created in the API handler.
        For auto-threshold, it's created here in the worker before Gemini submission.
        """
        batch_job = BatchJob(
            id=uuid.uuid7(),
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            snapshot_id=snapshot_id,
            source_ids=source_ids,
            background_task_id=background_task_id,
            operation_type=BatchOperationType.EMBEDDING,
            status=BatchStatus.PENDING,
            item_count=item_count,
            request_count=item_count,
            result_metadata={"chunk_ids": [str(cid) for cid in chunk_ids]},
        )
        session.add(batch_job)
        return batch_job

    async def poll_and_complete(
        self,
        *,
        session: AsyncSession,
        batch_job: BatchJob,
        qdrant_service,
    ) -> bool:
        """Poll batch status. Returns True if batch is terminal (complete/failed)."""
        if not batch_job.batch_operation_name:
            return False

        status_result = self._batch_client.get_batch_status(batch_job.batch_operation_name)
        batch_job.last_polled_at = datetime.now(UTC)

        if status_result.internal_status == BatchStatus.PROCESSING:
            await session.commit()
            return False

        if status_result.internal_status in (BatchStatus.FAILED, BatchStatus.CANCELLED):
            batch_job.status = status_result.internal_status
            batch_job.error_message = f"Gemini batch {status_result.raw_state}"
            batch_job.completed_at = datetime.now(UTC)
            await session.commit()
            return True

        if status_result.internal_status == BatchStatus.COMPLETE:
            await self._apply_results(
                session=session,
                batch_job=batch_job,
                qdrant_service=qdrant_service,
            )
            return True

        return False

    async def _apply_results(
        self,
        *,
        session: AsyncSession,
        batch_job: BatchJob,
        qdrant_service,
    ) -> None:
        """Parse batch results and upsert embeddings to Qdrant."""
        from sqlalchemy import update
        from app.db.models.knowledge import Chunk, KnowledgeSnapshot, Source
        from app.db.models.background_task import BackgroundTask
        from app.db.models.enums import (
            BackgroundTaskStatus, ChunkStatus, SourceStatus,
        )
        from app.services.qdrant import QdrantChunkPoint

        # Load source records for source_type and language enrichment
        sources = (await session.scalars(
            select(Source).where(Source.id.in_(batch_job.source_ids or []))
        )).all()
        source_map = {s.id: s for s in sources}

        # CRITICAL: Use stored chunk_ids from BatchJob.result_metadata for correlation.
        # Do NOT re-query chunks and build a new list — DB query order may differ
        # from submission order, breaking positional result mapping.
        stored_metadata = batch_job.result_metadata or {}
        stored_chunk_ids = [uuid.UUID(cid) for cid in stored_metadata.get("chunk_ids", [])]
        if not stored_chunk_ids:
            logger.error("batch.apply.no_stored_chunk_ids", batch_job_id=str(batch_job.id))
            batch_job.status = BatchStatus.FAILED
            batch_job.error_message = "No stored chunk_ids for result correlation"
            batch_job.completed_at = datetime.now(UTC)
            await session.commit()
            return

        # Load chunks by stored IDs, preserving stored order via a lookup map
        chunk_rows = (await session.scalars(
            select(Chunk).where(Chunk.id.in_(stored_chunk_ids))
        )).all()
        chunk_map = {c.id: c for c in chunk_rows}
        chunks = [chunk_map[cid] for cid in stored_chunk_ids if cid in chunk_map]

        results = self._batch_client.get_batch_results(
            batch_job.batch_operation_name,
            stored_chunk_ids,
        )

        succeeded = 0
        failed = 0
        failed_items: list[dict] = []
        qdrant_points: list[QdrantChunkPoint] = []
        default_language = "english"  # from settings, passed via orchestrator init

        for chunk, result in zip(chunks, results, strict=True):
            source = source_map.get(chunk.source_id)
            if result.vector is not None:
                chunk.status = ChunkStatus.INDEXED
                qdrant_points.append(QdrantChunkPoint(
                    chunk_id=chunk.id,
                    vector=result.vector,
                    snapshot_id=chunk.snapshot_id,
                    source_id=chunk.source_id,
                    document_version_id=chunk.document_version_id,
                    agent_id=chunk.agent_id,
                    knowledge_base_id=chunk.knowledge_base_id,
                    text_content=chunk.text_content,
                    chunk_index=chunk.chunk_index,
                    token_count=chunk.token_count,
                    anchor_page=chunk.anchor_page,
                    anchor_chapter=chunk.anchor_chapter,
                    anchor_section=chunk.anchor_section,
                    anchor_timecode=chunk.anchor_timecode,
                    source_type=source.source_type if source else "unknown",
                    language=(source.language if source and source.language else default_language),
                    status=ChunkStatus.INDEXED,
                ))
                succeeded += 1
            else:
                failed += 1
                failed_items.append({
                    "chunk_id": str(chunk.id),
                    "error": result.error,
                })

        if qdrant_points:
            await qdrant_service.upsert_chunks(qdrant_points)

        batch_job.succeeded_count = succeeded
        batch_job.failed_count = failed
        batch_job.processed_count = succeeded + failed
        batch_job.status = BatchStatus.FAILED if succeeded == 0 and failed > 0 else BatchStatus.COMPLETE
        batch_job.completed_at = datetime.now(UTC)
        if failed_items:
            batch_job.result_metadata = {"failed_items": failed_items}

        # --- Shared finalization (mirrors _finalize_pipeline_success) ---

        # Update KnowledgeSnapshot.chunk_count
        if succeeded > 0 and batch_job.snapshot_id:
            await session.execute(
                update(KnowledgeSnapshot)
                .where(KnowledgeSnapshot.id == batch_job.snapshot_id)
                .values(chunk_count=KnowledgeSnapshot.chunk_count + succeeded)
            )

        # Update Document and DocumentVersion → READY
        # (same as _finalize_pipeline_success does for interactive flow)
        from app.db.models.knowledge import Document, DocumentVersion, EmbeddingProfile
        from app.db.models.enums import DocumentStatus, DocumentVersionStatus, TaskType
        doc_version_ids = {c.document_version_id for c in chunks if c.status == ChunkStatus.INDEXED}
        if doc_version_ids:
            await session.execute(
                update(DocumentVersion)
                .where(DocumentVersion.id.in_(doc_version_ids))
                .values(status=DocumentVersionStatus.READY)
            )
            doc_ids_result = await session.scalars(
                select(DocumentVersion.document_id)
                .where(DocumentVersion.id.in_(doc_version_ids))
            )
            doc_ids = set(doc_ids_result.all())
            if doc_ids:
                await session.execute(
                    update(Document)
                    .where(Document.id.in_(doc_ids))
                    .values(status=DocumentStatus.READY)
                )

        # Create EmbeddingProfile (same as interactive finalization)
        if succeeded > 0:
            session.add(EmbeddingProfile(
                id=uuid.uuid7(),
                model_name=self._batch_client._model,
                dimensions=self._batch_client._dimensions,
                task_type=TaskType.RETRIEVAL,
                pipeline_version="s3-06-batch",
                knowledge_base_id=batch_job.knowledge_base_id,
                snapshot_id=batch_job.snapshot_id,
            ))

        # Finalize linked BackgroundTask
        if batch_job.background_task_id:
            bg_task = await session.get(BackgroundTask, batch_job.background_task_id)
            if bg_task and bg_task.status == BackgroundTaskStatus.PROCESSING:
                bg_task.status = BackgroundTaskStatus.COMPLETE if succeeded > 0 else BackgroundTaskStatus.FAILED
                bg_task.completed_at = datetime.now(UTC)
                bg_task.progress = 100
                bg_task.result_metadata = {
                    **(bg_task.result_metadata or {}),
                    "batch_job_id": str(batch_job.id),
                    "chunk_count": succeeded,
                    "embedding_model": self._batch_client._model,
                    "embedding_dimensions": self._batch_client._dimensions,
                }

        # For auto-threshold path: update source PROCESSING → READY
        for source in sources:
            if source.status == SourceStatus.PROCESSING:
                source.status = SourceStatus.READY

        await session.commit()

        logger.info(
            "batch.completed",
            batch_job_id=str(batch_job.id),
            succeeded=succeeded,
            failed=failed,
        )
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/unit/services/test_batch_orchestrator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```
feat(batch): add BatchOrchestrator with submit, dedup, and result application (S3-06)
```

---

## Task 4: Skip-Embedding Flow — Upload + Worker

**Files:**
- Modify: `backend/app/services/source.py`
- Modify: `backend/app/workers/tasks/pipeline.py`
- Modify: `backend/app/workers/tasks/handlers/path_b.py`
- Modify: `backend/app/workers/tasks/handlers/path_a.py`
- Modify: `backend/app/workers/tasks/ingestion.py`
- Create: `backend/tests/unit/workers/test_skip_embedding.py`

- [ ] **Step 1: Add SkipEmbeddingResult to pipeline.py**

In `backend/app/workers/tasks/pipeline.py`, add:

```python
@dataclass(slots=True, frozen=True)
class SkipEmbeddingResult:
    """Returned when skip_embedding=true: chunks created but not embedded."""
    snapshot_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_ids: list[uuid.UUID]
    chunk_count: int
    token_count_total: int
    processing_path: ProcessingPath
    pipeline_version: str
```

- [ ] **Step 2: Modify SourceService to pass skip_embedding**

In `backend/app/services/source.py`, modify `create_source_and_task` to accept `skip_embedding: bool = False` and store it in `result_metadata`:

```python
async def create_source_and_task(
    self,
    *,
    source_id: uuid.UUID,
    metadata: SourceUploadMetadata,
    source_type: SourceType,
    file_path: str,
    file_size_bytes: int,
    mime_type: str | None,
    skip_embedding: bool = False,
) -> SourceTaskBundle:
    # ... existing source creation ...
    task = BackgroundTask(
        # ... existing fields ...
        result_metadata={"skip_embedding": True} if skip_embedding else None,
    )
```

- [ ] **Step 3: Modify handle_path_b to support skip_embedding**

In `backend/app/workers/tasks/handlers/path_b.py`, add `skip_embedding` parameter. When True, skip the embedding and Qdrant upsert steps (lines 96-129 of original), return `SkipEmbeddingResult` instead of `PathBResult`:

After chunk creation (line 94 `await session.commit()`), add:

```python
if skip_embedding:
    return SkipEmbeddingResult(
        snapshot_id=snapshot_id,
        document_id=document.id,
        document_version_id=document_version.id,
        chunk_ids=[chunk.id for chunk in chunk_rows],
        chunk_count=len(chunk_rows),
        token_count_total=persisted_state.token_count_total,
        processing_path=ProcessingPath.PATH_B,
        pipeline_version="s3-06-skip-embed",
    )
```

Apply same pattern to `handle_path_a` in `path_a.py`.

- [ ] **Step 4: Modify ingestion.py to detect skip_embedding**

In `_run_ingestion_pipeline`, read `skip_embedding` from task metadata and pass to handlers:

```python
skip_embedding = bool(
    task.result_metadata.get("skip_embedding") if task.result_metadata else False
)
```

Pass `skip_embedding=skip_embedding` to `handle_path_a` and `handle_path_b`.

When result is `SkipEmbeddingResult`, finalize differently — set source to READY, chunks stay PENDING, no `_finalize_pipeline_success`:

```python
if isinstance(result, SkipEmbeddingResult):
    await _finalize_skip_embedding(session, task, source, result)
    return
```

Implement `_finalize_skip_embedding` that sets source=READY, document=READY, document_version=READY, task=COMPLETE with metadata.

- [ ] **Step 5: Modify upload_source endpoint to accept skip_embedding**

In `backend/app/api/admin.py`, add query parameter to `upload_source`:

```python
async def upload_source(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    metadata: Annotated[str, Form(...)],
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
    source_service: Annotated[SourceService, Depends(get_source_service)],
    skip_embedding: Annotated[bool, Query()] = False,
) -> SourceUploadResponse:
```

Pass `skip_embedding=skip_embedding` to `source_service.create_source_and_task(...)`.

- [ ] **Step 6: Write tests for skip-embedding flow**

```python
# backend/tests/unit/workers/test_skip_embedding.py
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.models.enums import ChunkStatus, ProcessingPath
from app.workers.tasks.pipeline import SkipEmbeddingResult


class TestSkipEmbeddingPathB:
    @pytest.mark.asyncio
    async def test_path_b_skip_embedding_returns_skip_result(self):
        """When skip_embedding=True, path_b returns SkipEmbeddingResult
        without calling embedding_service or qdrant_service."""
        from app.workers.tasks.handlers.path_b import handle_path_b

        # ... setup mocks for session, task, source, services ...
        # ... call handle_path_b with skip_embedding=True ...
        # ... assert result is SkipEmbeddingResult ...
        # ... assert embedding_service.embed_texts not called ...
        # ... assert qdrant_service.upsert_chunks not called ...
```

- [ ] **Step 7: Run tests**

Run: `cd backend && python -m pytest tests/unit/workers/test_skip_embedding.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```
feat(batch): add skip_embedding flag to upload flow and ingestion worker (S3-06)
```

---

## Task 5: Batch-Embed Endpoint + Worker Task

**Files:**
- Create: `backend/app/api/batch_schemas.py`
- Modify: `backend/app/api/admin.py`
- Modify: `backend/app/api/dependencies.py`
- Create: `backend/app/workers/tasks/batch_embed.py`
- Modify: `backend/app/workers/main.py`
- Create: `backend/tests/unit/test_batch_embed_api.py`

- [ ] **Step 1: Create batch schemas**

```python
# backend/app/api/batch_schemas.py
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class BatchEmbedRequest(BaseModel):
    source_ids: list[uuid.UUID] = Field(min_length=1)


class BatchEmbedResponse(BaseModel):
    task_id: uuid.UUID
    batch_job_id: uuid.UUID | None
    chunk_count: int
    message: str


class BatchJobResponse(BaseModel):
    id: uuid.UUID
    operation_type: str
    status: str
    item_count: int | None
    processed_count: int | None
    succeeded_count: int | None
    failed_count: int | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    last_polled_at: datetime | None


class BatchJobListResponse(BaseModel):
    items: list[BatchJobResponse]
    total: int


class BatchJobDetailResponse(BatchJobResponse):
    snapshot_id: uuid.UUID | None
    source_ids: list[uuid.UUID] | None
    result_metadata: dict | None
```

- [ ] **Step 2: Add dependency for batch task enqueue**

In `backend/app/api/dependencies.py`, add `enqueue_batch_embed` to `ArqTaskEnqueuer`:

```python
async def enqueue_batch_embed(self, task_id: uuid.UUID) -> str:
    job = await self._arq_pool.enqueue_job("process_batch_embed", str(task_id))
    if job is None:
        raise RuntimeError("arq returned no job handle")
    return job.job_id
```

Update `TaskEnqueuer` protocol to include this method.

- [ ] **Step 3: Add batch-embed endpoint to admin router**

In `backend/app/api/admin.py`:

```python
@router.post(
    "/batch-embed",
    response_model=BatchEmbedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def batch_embed(
    payload: BatchEmbedRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    task_enqueuer: Annotated[TaskEnqueuer, Depends(get_task_enqueuer)],
    agent_id: uuid.UUID = DEFAULT_AGENT_ID,
    knowledge_base_id: uuid.UUID = DEFAULT_KNOWLEDGE_BASE_ID,
) -> BatchEmbedResponse:
    # 1. Validate sources exist, are READY, have PENDING chunks
    # 2. Validate all chunks belong to same snapshot_id
    # 3. Source-level dedup check (409 if overlap with active batch)
    # 4. Create BackgroundTask(BATCH_EMBEDDING, source_id=None, agent_id=agent_id,
    #    result_metadata={"source_ids": [...], "knowledge_base_id": str(...), "snapshot_id": str(...)})
    #    NOTE: BackgroundTask has agent_id (TenantMixin) but NOT knowledge_base_id.
    # 5. Create BatchJob SYNCHRONOUSLY (status=pending, linked to BackgroundTask).
    #    Store ordered chunk_ids in BatchJob.result_metadata for result correlation.
    #    This guarantees batch_job_id exists at response time.
    # 6. Enqueue process_batch_embed
    # 7. Return 202 with both task_id and batch_job_id
```

- [ ] **Step 4: Add GET /batch-jobs and GET /batch-jobs/:id endpoints**

```python
@router.get("/batch-jobs", response_model=BatchJobListResponse)
async def list_batch_jobs(
    session: Annotated[AsyncSession, Depends(get_session)],
    batch_status: BatchStatus | None = None,
    operation_type: BatchOperationType | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> BatchJobListResponse:
    # Query batch_jobs with filters, return paginated list
    ...

@router.get("/batch-jobs/{batch_job_id}", response_model=BatchJobDetailResponse)
async def get_batch_job(
    batch_job_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BatchJobDetailResponse:
    ...
```

- [ ] **Step 5: Create process_batch_embed worker task**

```python
# backend/app/workers/tasks/batch_embed.py
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import BackgroundTask, Chunk
from app.db.models.enums import BackgroundTaskStatus, ChunkStatus

logger = structlog.get_logger(__name__)


async def process_batch_embed(ctx: dict[str, Any], task_id: str) -> None:
    session_factory = ctx["session_factory"]
    batch_orchestrator = ctx["batch_orchestrator"]

    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        logger.warning("worker.batch_embed.invalid_task_id", task_id=task_id)
        return

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_uuid)
        if task is None or task.status is not BackgroundTaskStatus.PENDING:
            return

        task.status = BackgroundTaskStatus.PROCESSING
        task.started_at = datetime.now(UTC)
        await session.commit()

        # Extract metadata — knowledge_base_id is in result_metadata
        # because BackgroundTask has TenantMixin (agent_id) but NOT KnowledgeScopeMixin
        metadata = task.result_metadata or {}
        source_ids_raw = metadata.get("source_ids", [])
        source_ids = [uuid.UUID(sid) for sid in source_ids_raw]
        knowledge_base_id = uuid.UUID(metadata["knowledge_base_id"])

        # Query PENDING chunks for these sources
        chunks = (await session.scalars(
            select(Chunk).where(
                Chunk.source_id.in_(source_ids),
                Chunk.status == ChunkStatus.PENDING,
            ).order_by(Chunk.source_id, Chunk.chunk_index)
        )).all()

        if not chunks:
            task.status = BackgroundTaskStatus.COMPLETE
            task.completed_at = datetime.now(UTC)
            task.error_message = "No pending chunks found"
            await session.commit()
            return

        # Derive snapshot_id from chunks (validated at API level to be uniform)
        snapshot_id = chunks[0].snapshot_id

        # BatchJob was already created synchronously by the API handler.
        # Worker picks it up and submits to Gemini.
        try:
            await batch_orchestrator.submit_to_gemini(
                session=session,
                background_task_id=task.id,
                texts=[c.text_content for c in chunks],
                chunk_ids=[c.id for c in chunks],
            )
            # Task stays PROCESSING — cron poll will complete it
        except Exception as exc:
            task.status = BackgroundTaskStatus.FAILED
            task.error_message = str(exc)
            task.completed_at = datetime.now(UTC)
            await session.commit()
```

- [ ] **Step 6: Register in worker main.py**

In `backend/app/workers/main.py`:
- Import `process_batch_embed`
- Add to `WorkerSettings.functions`
- Add `BatchEmbeddingClient` and `BatchOrchestrator` to worker context in `on_startup`

- [ ] **Step 7: Write endpoint tests**

```python
# backend/tests/unit/test_batch_embed_api.py
# Test: POST /batch-embed with valid source_ids → 202
# Test: POST /batch-embed with nonexistent source → 404
# Test: POST /batch-embed with no pending chunks → 422
# Test: POST /batch-embed dedup → 409
# Test: GET /batch-jobs → list
# Test: GET /batch-jobs/:id → detail
```

- [ ] **Step 8: Run tests**

Run: `cd backend && python -m pytest tests/unit/test_batch_embed_api.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```
feat(batch): add batch-embed endpoint and worker task (S3-06)
```

---

## Task 6: Poll Active Batches — Cron Task

**Files:**
- Create: `backend/app/workers/tasks/batch_poll.py`
- Modify: `backend/app/workers/main.py`
- Create: `backend/tests/unit/workers/test_batch_poll.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/unit/workers/test_batch_poll.py
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models.enums import BatchStatus


class TestPollActiveBatches:
    @pytest.mark.asyncio
    async def test_poll_no_active_batches_does_nothing(self):
        """When no batches are processing, poll exits cleanly."""
        from app.workers.tasks.batch_poll import poll_active_batches

        mock_session = AsyncMock()
        mock_session.scalars = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        mock_factory = MagicMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        ctx = {
            "session_factory": mock_factory,
            "batch_orchestrator": MagicMock(),
            "qdrant_service": MagicMock(),
        }
        await poll_active_batches(ctx)
        # No exception = success

    @pytest.mark.asyncio
    async def test_poll_completes_succeeded_batch(self):
        """When batch is SUCCEEDED, poll_and_complete is called."""
        # ... mock batch_orchestrator.poll_and_complete returning True ...
```

- [ ] **Step 2: Run tests**

Expected: ImportError

- [ ] **Step 3: Implement poll_active_batches**

```python
# backend/app/workers/tasks/batch_poll.py
from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.enums import BatchStatus
from app.db.models.operations import BatchJob

logger = structlog.get_logger(__name__)


async def poll_active_batches(ctx: dict[str, Any]) -> None:
    session_factory = ctx["session_factory"]
    batch_orchestrator = ctx["batch_orchestrator"]
    qdrant_service = ctx["qdrant_service"]

    async with session_factory() as session:
        active_batches = (await session.scalars(
            select(BatchJob).where(
                BatchJob.status == BatchStatus.PROCESSING,
            )
        )).all()

        if not active_batches:
            return

        logger.info("batch.poll.active_count", count=len(active_batches))

        for batch_job in active_batches:
            try:
                completed = await batch_orchestrator.poll_and_complete(
                    session=session,
                    batch_job=batch_job,
                    qdrant_service=qdrant_service,
                )
                if completed:
                    logger.info(
                        "batch.poll.completed",
                        batch_job_id=str(batch_job.id),
                        status=batch_job.status.value,
                    )
            except Exception:
                logger.exception(
                    "batch.poll.error",
                    batch_job_id=str(batch_job.id),
                )
```

- [ ] **Step 4: Register as cron in WorkerSettings**

In `backend/app/workers/main.py`:

```python
from arq.cron import cron
from app.workers.tasks.batch_poll import poll_active_batches

class WorkerSettings:
    functions = [process_ingestion, process_batch_embed]
    cron_jobs = [
        cron(poll_active_batches, second={0, 30}),  # Every 30 seconds
    ]
    # NOTE: arq cron() is evaluated at import time, so the interval is static
    # (not configurable via batch_poll_interval_seconds at runtime).
    # For ProxyMind's scale this is acceptable. If dynamic intervals are needed
    # later, switch to a repeating job pattern.
    # ... rest unchanged
```

- [ ] **Step 5: Run tests**

Run: `cd backend && python -m pytest tests/unit/workers/test_batch_poll.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```
feat(batch): add poll_active_batches cron task (S3-06)
```

---

## Task 7: Auto-Threshold in Per-Source Ingestion

**Files:**
- Modify: `backend/app/workers/tasks/pipeline.py`
- Modify: `backend/app/workers/tasks/ingestion.py`
- Modify: `backend/app/workers/tasks/handlers/path_b.py`

- [ ] **Step 1: Add BatchSubmittedResult type**

In `backend/app/workers/tasks/pipeline.py`:

```python
@dataclass(slots=True, frozen=True)
class BatchSubmittedResult:
    """Returned when auto-threshold triggers batch mode."""
    snapshot_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_ids: list[uuid.UUID]
    chunk_count: int
    batch_job_id: uuid.UUID
```

- [ ] **Step 2: Modify path_b to detect threshold and submit batch**

In `handle_path_b`, after chunk creation, before embedding:

```python
# Auto-threshold: if chunk_count exceeds threshold, use batch API
if (
    not skip_embedding
    and len(chunk_rows) > services.settings.batch_embed_chunk_threshold
    and services.batch_orchestrator is not None  # only if batch is configured
):
    submit_result = await services.batch_orchestrator.submit_batch(
        session=session,
        texts=[c.text_content for c in chunk_data],
        chunk_ids=[c.id for c in chunk_rows],
        agent_id=source.agent_id,
        knowledge_base_id=source.knowledge_base_id,
        snapshot_id=snapshot_id,
        source_ids=[source.id],
        background_task_id=task.id,  # need task passed to handler
    )
    return BatchSubmittedResult(
        snapshot_id=snapshot_id,
        document_id=document.id,
        document_version_id=document_version.id,
        chunk_ids=[c.id for c in chunk_rows],
        chunk_count=len(chunk_rows),
        batch_job_id=submit_result.batch_job_id,
    )
```

- [ ] **Step 3: Handle BatchSubmittedResult in ingestion.py**

In `_run_ingestion_pipeline`, when result is `BatchSubmittedResult`:

```python
if isinstance(result, BatchSubmittedResult):
    # Task and source stay PROCESSING — cron poll completes them
    task.progress = 50
    task.result_metadata = {
        "batch_job_id": str(result.batch_job_id),
        "chunk_count": result.chunk_count,
    }
    await session.commit()
    return  # Early exit — no finalization
```

- [ ] **Step 4: Add batch_orchestrator to PipelineServices**

In `pipeline.py`, add optional field:

```python
@dataclass(slots=True)
class PipelineServices:
    # ... existing fields ...
    batch_orchestrator: BatchOrchestrator | None = None
```

Wire it in `ingestion.py:_load_pipeline_services` from worker context (use `ctx.get("batch_orchestrator")`).

- [ ] **Step 5: Write tests**

Test that chunk_count > threshold returns `BatchSubmittedResult` and does NOT call `embedding_service.embed_texts`.

- [ ] **Step 6: Run tests**

Run: `cd backend && python -m pytest tests/unit/workers/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```
feat(batch): add auto-threshold batch mode for large sources (S3-06)
```

---

## Task 8: Integration Tests

**Files:**
- Create: `backend/tests/integration/test_batch_flow.py`

- [ ] **Step 1: Write integration tests**

Test the full flow with mocked Gemini API but real DB:

```python
# backend/tests/integration/test_batch_flow.py
"""Integration tests for Gemini Batch API flow (S3-06).

Uses real PostgreSQL, mocked Gemini Batch API and Qdrant.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

# Test: upload source with skip_embedding=true → source READY, chunks PENDING
# Test: POST /batch-embed → 202, BackgroundTask created
# Test: POST /batch-embed with active batch for same sources → 409
# Test: poll completes batch → chunks INDEXED
# Test: GET /batch-jobs → lists batch
# Test: GET /batch-jobs/:id → detail with result_metadata
```

- [ ] **Step 2: Run integration tests**

Run: `cd backend && python -m pytest tests/integration/test_batch_flow.py -v`
Expected: PASS

- [ ] **Step 3: Run full test suite**

Run: `cd backend && python -m pytest -v`
Expected: All tests pass, no regressions

- [ ] **Step 4: Commit**

```
test(batch): add integration tests for batch embed flow (S3-06)
```

---

## Task 9: Final Verification + Cleanup

- [ ] **Step 1: Re-read docs/development.md and self-review**

Verify all code follows development standards.

- [ ] **Step 2: Run full test suite**

Run: `cd backend && python -m pytest -v`
Expected: All pass

- [ ] **Step 3: Run linter**

Run: `cd backend && ruff check . && ruff format --check .`
Expected: Clean

- [ ] **Step 4: Verify package versions**

Check `pyproject.toml` — no new dependencies needed (google-genai >= 1.14.0 already includes batch API).

- [ ] **Step 5: Final commit if any cleanup needed**

```
chore(batch): cleanup and final review (S3-06)
```
