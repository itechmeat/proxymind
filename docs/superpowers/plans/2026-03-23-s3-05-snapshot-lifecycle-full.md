# S3-05: Snapshot Lifecycle (Full) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the snapshot lifecycle with rollback, draft testing, and source soft delete.

**Architecture:** Three independent features extending existing `SnapshotService` and admin API. Rollback reuses the `_do_activate()` pattern with auto-target selection. Draft test calls `QdrantService` search methods directly (bypassing `RetrievalService`). Source soft delete cascades chunk removal to drafts only, preserving published data.

**Tech Stack:** FastAPI, SQLAlchemy 2.x (async), Qdrant client, Pydantic v2, pytest (async integration tests)

**Spec:** `docs/superpowers/specs/2026-03-23-s3-05-snapshot-lifecycle-full-design.md`

**Pre-implementation:** Read `docs/development.md` before writing code (CLAUDE.md requirement).

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/services/snapshot.py` | Modify | Add `rollback()` method |
| `backend/app/services/source_delete.py` | Create | Soft delete logic with draft cascade |
| `backend/app/api/admin.py` | Modify | Add rollback, draft test, source delete endpoints |
| `backend/app/api/snapshot_schemas.py` | Modify | Add `RollbackResponse`, `DraftTestRequest`, `DraftTestResponse` |
| `backend/app/api/source_schemas.py` | Create | `SourceDeleteResponse` schema |
| `backend/app/api/dependencies.py` | Modify | Add `get_embedding_service` dependency factory |
| `backend/app/workers/tasks/ingestion.py` | Modify | Add source status guard |
| `backend/tests/integration/test_snapshot_lifecycle.py` | Modify | Add rollback service tests |
| `backend/tests/integration/test_snapshot_api.py` | Modify | Add rollback + draft test API tests |
| `backend/tests/integration/test_source_soft_delete.py` | Create | Soft delete service + API tests |

---

## Task 1: Rollback — Service Method

**Files:**
- Modify: `backend/app/services/snapshot.py` (add `rollback()` after `activate()` ~line 256)
- Modify: `backend/tests/integration/test_snapshot_lifecycle.py` (add rollback tests)

- [ ] **Step 0: Fix `_create_snapshot` helper to preserve `activated_at` for PUBLISHED status**

The existing helper at `backend/tests/integration/test_snapshot_lifecycle.py:50` discards `activated_at` when `status != ACTIVE`:
```python
activated_at=activated_at if status is SnapshotStatus.ACTIVE else None,
```

Change to preserve `activated_at` for PUBLISHED too (demoted snapshots retain their timestamp):
```python
activated_at=activated_at if status in {SnapshotStatus.ACTIVE, SnapshotStatus.PUBLISHED} else None,
```

**IMPORTANT: Also fix the `_create_snapshot` helper in `backend/tests/integration/test_snapshot_api.py`** — it has its own copy of this helper (check ~line 22). Apply the identical change: `activated_at=activated_at if status in {SnapshotStatus.ACTIVE, SnapshotStatus.PUBLISHED} else None`. Without this fix, the rollback API tests in Task 2 will fail because snapshot A (PUBLISHED) won't have `activated_at` set.

- [ ] **Step 1: Write failing test — rollback happy path**

Add to `backend/tests/integration/test_snapshot_lifecycle.py`:

```python
@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_rollback_reactivates_previous_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Rollback on active snapshot should reactivate the most recently demoted published snapshot."""
    # Setup: A was active, then B was activated (A demoted to published with activated_at preserved)
    snapshot_a_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 1, tzinfo=UTC),  # previously active, demoted
    )
    snapshot_b_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.ACTIVE,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    async with session_factory() as session:
        service = SnapshotService(session)
        rolled_back_from, rolled_back_to = await service.rollback(snapshot_b_id)

    assert rolled_back_from.id == snapshot_b_id
    assert rolled_back_from.status == SnapshotStatus.PUBLISHED
    assert rolled_back_to.id == snapshot_a_id
    assert rolled_back_to.status == SnapshotStatus.ACTIVE

    # Verify agent pointer updated
    async with session_factory() as session:
        agent = await session.get(Agent, DEFAULT_AGENT_ID)
        assert agent.active_snapshot_id == snapshot_a_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/integration/test_snapshot_lifecycle.py::test_rollback_reactivates_previous_snapshot -v`
Expected: FAIL — `AttributeError: 'SnapshotService' object has no attribute 'rollback'`

- [ ] **Step 3: Implement `rollback()` in SnapshotService**

Add to `backend/app/services/snapshot.py` after the `activate()` method (~line 256):

```python
async def rollback(
    self,
    snapshot_id: UUID,
    *,
    agent_id: UUID | None = None,
    knowledge_base_id: UUID | None = None,
    session: AsyncSession | None = None,
) -> tuple[KnowledgeSnapshot, KnowledgeSnapshot]:
    """Roll back the active snapshot to the most recently demoted published snapshot.

    Returns (rolled_back_from, rolled_back_to) tuple.
    """
    db_session = self._resolve_session(session)

    current = await self._get_snapshot_for_update(
        db_session,
        snapshot_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )
    if current is None:
        raise SnapshotNotFoundError(f"Snapshot {snapshot_id} not found")
    if current.status != SnapshotStatus.ACTIVE:
        raise SnapshotConflictError(
            f"Only the active snapshot can be rolled back (current status: {current.status.value})"
        )

    # Derive scope from the locked current snapshot — never from params alone.
    # This prevents cross-scope rollback if params are omitted or wrong.
    resolved_agent_id = current.agent_id
    resolved_kb_id = current.knowledge_base_id

    # Find the most recently demoted published snapshot (by activated_at)
    scope_filter = [
        KnowledgeSnapshot.status == SnapshotStatus.PUBLISHED,
        KnowledgeSnapshot.activated_at.is_not(None),
        KnowledgeSnapshot.agent_id == resolved_agent_id,
        KnowledgeSnapshot.knowledge_base_id == resolved_kb_id,
    ]

    target_stmt = (
        select(KnowledgeSnapshot)
        .where(*scope_filter)
        .order_by(KnowledgeSnapshot.activated_at.desc())
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    target = (await db_session.execute(target_stmt)).scalar_one_or_none()

    if target is None:
        raise SnapshotConflictError(
            "No previously activated snapshot available for rollback"
        )

    # Demote current active → published
    current.status = SnapshotStatus.PUBLISHED

    # Activate target
    await self._do_activate(db_session, target)

    await self._commit_snapshot_change(
        db_session,
        target,
        concurrent_detail="Another rollback or activation happened concurrently",
    )

    await db_session.refresh(current)
    return current, target
```

Note: import `select` from sqlalchemy if not already imported (check line 3 of snapshot.py).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/integration/test_snapshot_lifecycle.py::test_rollback_reactivates_previous_snapshot -v`
Expected: PASS

- [ ] **Step 5: Write failing test — rollback on non-active**

```python
@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_rollback_non_active_raises_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
    )
    async with session_factory() as session:
        service = SnapshotService(session)
        with pytest.raises(SnapshotConflictError, match="Only the active snapshot"):
            await service.rollback(snapshot_id)
```

- [ ] **Step 6: Run test — should pass (already handled)**

Run: `cd backend && python -m pytest tests/integration/test_snapshot_lifecycle.py::test_rollback_non_active_raises_conflict -v`
Expected: PASS (validation is in the implementation)

- [ ] **Step 7: Write failing test — rollback with no previous**

```python
@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_rollback_no_previous_raises_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """If no PUBLISHED snapshot has activated_at, rollback should fail."""
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.ACTIVE,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    async with session_factory() as session:
        service = SnapshotService(session)
        with pytest.raises(SnapshotConflictError, match="No previously activated"):
            await service.rollback(snapshot_id)
```

- [ ] **Step 8: Run test — should pass**

Run: `cd backend && python -m pytest tests/integration/test_snapshot_lifecycle.py::test_rollback_no_previous_raises_conflict -v`
Expected: PASS

- [ ] **Step 9: Write failing test — rollback not found**

```python
@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_rollback_not_found_raises_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = SnapshotService(session)
        with pytest.raises(SnapshotNotFoundError):
            await service.rollback(uuid.uuid4())
```

- [ ] **Step 10: Run test — should pass**

Run: `cd backend && python -m pytest tests/integration/test_snapshot_lifecycle.py::test_rollback_not_found_raises_error -v`
Expected: PASS

- [ ] **Step 11: Run all snapshot lifecycle tests**

Run: `cd backend && python -m pytest tests/integration/test_snapshot_lifecycle.py -v`
Expected: ALL PASS (existing + new)

- [ ] **Step 12: Commit (only if user explicitly requests)**

Proposed message: `feat(snapshot): add rollback service method with auto-target selection (S3-05)`
Files: `backend/app/services/snapshot.py`, `backend/tests/integration/test_snapshot_lifecycle.py`

---

## Task 2: Rollback — API Endpoint

**Files:**
- Modify: `backend/app/api/snapshot_schemas.py` (add `RollbackResponse`)
- Modify: `backend/app/api/admin.py` (add rollback endpoint after activate ~line 240)
- Modify: `backend/tests/integration/test_snapshot_api.py` (add rollback API tests)

- [ ] **Step 1: Add RollbackResponse schema**

Add to `backend/app/api/snapshot_schemas.py`:

```python
class RollbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rolled_back_from: SnapshotResponse
    rolled_back_to: SnapshotResponse
```

- [ ] **Step 2: Write failing API test — rollback happy path**

Add to `backend/tests/integration/test_snapshot_api.py`:

```python
@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_rollback_endpoint_returns_200(
    session_factory: async_sessionmaker[AsyncSession],
    api_client: AsyncClient,
) -> None:
    snapshot_a_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    snapshot_b_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.ACTIVE,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    response = await api_client.post(f"/api/admin/snapshots/{snapshot_b_id}/rollback")
    assert response.status_code == 200

    body = response.json()
    assert body["rolled_back_from"]["id"] == str(snapshot_b_id)
    assert body["rolled_back_from"]["status"] == "published"
    assert body["rolled_back_to"]["id"] == str(snapshot_a_id)
    assert body["rolled_back_to"]["status"] == "active"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/integration/test_snapshot_api.py::test_rollback_endpoint_returns_200 -v`
Expected: FAIL — 404 (endpoint doesn't exist)

- [ ] **Step 4: Implement rollback endpoint**

Add to `backend/app/api/admin.py` after the activate endpoint (~line 240):

```python
@router.post(
    "/snapshots/{snapshot_id}/rollback",
    response_model=RollbackResponse,
    status_code=200,
)
async def rollback_snapshot(
    snapshot_id: uuid.UUID,
    agent_id: uuid.UUID = Query(default=DEFAULT_AGENT_ID),
    knowledge_base_id: uuid.UUID = Query(default=DEFAULT_KNOWLEDGE_BASE_ID),
    snapshot_service: SnapshotService = Depends(get_snapshot_service),
) -> RollbackResponse:
    try:
        rolled_back_from, rolled_back_to = await snapshot_service.rollback(
            snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
        )
    except (SnapshotNotFoundError, SnapshotConflictError, SnapshotValidationError) as error:
        _raise_snapshot_http_error(error)

    return RollbackResponse(
        rolled_back_from=SnapshotResponse.model_validate(rolled_back_from),
        rolled_back_to=SnapshotResponse.model_validate(rolled_back_to),
    )
```

Update imports at top of `admin.py`:
- Add `RollbackResponse` to the `snapshot_schemas` import

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/integration/test_snapshot_api.py::test_rollback_endpoint_returns_200 -v`
Expected: PASS

- [ ] **Step 6: Write error case tests**

```python
@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_rollback_endpoint_returns_404_for_unknown(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post(f"/api/admin/snapshots/{uuid.uuid4()}/rollback")
    assert response.status_code == 404


@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_rollback_endpoint_returns_409_for_non_active(
    session_factory: async_sessionmaker[AsyncSession],
    api_client: AsyncClient,
) -> None:
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
    )
    response = await api_client.post(f"/api/admin/snapshots/{snapshot_id}/rollback")
    assert response.status_code == 409


@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_rollback_endpoint_returns_409_when_no_previous(
    session_factory: async_sessionmaker[AsyncSession],
    api_client: AsyncClient,
) -> None:
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.ACTIVE,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    response = await api_client.post(f"/api/admin/snapshots/{snapshot_id}/rollback")
    assert response.status_code == 409
    assert "No previously activated" in response.json()["detail"]


@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_concurrent_rollback_one_succeeds_one_fails(
    session_factory: async_sessionmaker[AsyncSession],
    api_client: AsyncClient,
) -> None:
    """Two concurrent rollback requests: one should succeed, one should get 409."""
    import asyncio

    snapshot_a_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    snapshot_b_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.ACTIVE,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    results = await asyncio.gather(
        api_client.post(f"/api/admin/snapshots/{snapshot_b_id}/rollback"),
        api_client.post(f"/api/admin/snapshots/{snapshot_b_id}/rollback"),
    )
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 409], f"Expected one 200 and one 409, got {statuses}"
```

- [ ] **Step 7: Run all API tests**

Run: `cd backend && python -m pytest tests/integration/test_snapshot_api.py -v`
Expected: ALL PASS

- [ ] **Step 8: Commit (only if user explicitly requests)**

Proposed message: `feat(api): add rollback endpoint POST /api/admin/snapshots/{id}/rollback (S3-05)`
Files: `backend/app/api/snapshot_schemas.py`, `backend/app/api/admin.py`, `backend/tests/integration/test_snapshot_api.py`

---

## Task 3: Draft Test — Schemas + Endpoint

**Files:**
- Modify: `backend/app/api/snapshot_schemas.py` (add `DraftTestRequest`, `DraftTestResponse`, `DraftTestResult`)
- Modify: `backend/app/api/admin.py` (add test endpoint)
- Modify: `backend/app/api/dependencies.py` (add `get_embedding_service`)
- Modify: `backend/tests/conftest.py` (register mock `embedding_service` in test app)
- Modify: `backend/tests/integration/test_snapshot_api.py` (add draft test API tests)

**IMPORTANT — test app fixture:** The test `api_client` is built from an app fixture that currently sets `app.state.qdrant_service` but NOT `app.state.embedding_service`. FastAPI resolves all `Depends()` before calling the handler, so even 422/404 tests will fail if `get_embedding_service` can't resolve. Before writing tests, register a mock `embedding_service` in the test app fixture (check `backend/tests/conftest.py` ~line 205 for the existing pattern with `qdrant_service`). Use `unittest.mock.AsyncMock` for the `EmbeddingService` interface.

**Happy path draft test:** Add a test using dependency overrides to inject mock `EmbeddingService` + mock `QdrantService` that return controlled results. Follow the pattern in `backend/tests/unit/test_admin_keyword_search.py:31` for dependency override setup. This allows deterministic testing without external providers.

- [ ] **Step 1: Add draft test schemas**

Add to `backend/app/api/snapshot_schemas.py`:

```python
from enum import StrEnum


class RetrievalMode(StrEnum):
    HYBRID = "hybrid"
    DENSE = "dense"
    SPARSE = "sparse"


class DraftTestRequest(BaseModel):
    query: str
    top_n: int = Field(default=5, ge=1, le=100)
    mode: RetrievalMode = RetrievalMode.HYBRID

    @field_validator("query")
    @classmethod
    def strip_query(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("query must not be empty")
        return v


class DraftTestAnchor(BaseModel):
    page: int | None = None
    chapter: str | None = None
    section: str | None = None
    timecode: str | None = None


class DraftTestResult(BaseModel):
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    source_title: str | None = None
    text_content: str
    score: float
    anchor: DraftTestAnchor


class DraftTestResponse(BaseModel):
    snapshot_id: uuid.UUID
    snapshot_name: str
    query: str
    mode: RetrievalMode
    results: list[DraftTestResult]
    total_chunks_in_draft: int
```

- [ ] **Step 2: Write failing API test — draft test happy path**

Add to `backend/tests/integration/test_snapshot_api.py`. Note: this test requires Qdrant + embedding service to be mocked or available. Since CI tests are deterministic and do NOT call external providers, mock the embedding service and Qdrant search:

```python
@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_draft_test_endpoint_returns_422_for_non_draft(
    session_factory: async_sessionmaker[AsyncSession],
    api_client: AsyncClient,
) -> None:
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
    )
    response = await api_client.post(
        f"/api/admin/snapshots/{snapshot_id}/test",
        json={"query": "test query"},
    )
    assert response.status_code == 422


@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_draft_test_endpoint_returns_422_for_empty_draft(
    session_factory: async_sessionmaker[AsyncSession],
    api_client: AsyncClient,
) -> None:
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        chunk_statuses=[],
        chunk_count_override=0,
    )
    response = await api_client.post(
        f"/api/admin/snapshots/{snapshot_id}/test",
        json={"query": "test query"},
    )
    assert response.status_code == 422


@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_draft_test_endpoint_returns_404_for_unknown(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post(
        f"/api/admin/snapshots/{uuid.uuid4()}/test",
        json={"query": "test query"},
    )
    assert response.status_code == 404
```

- [ ] **Step 2b: Write happy-path test with dependency overrides**

Add to `backend/tests/unit/test_admin_draft_test.py` (new file, follows pattern from `test_admin_keyword_search.py`):

```python
"""Deterministic happy-path test for draft test endpoint using dependency overrides."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.api.dependencies import (
    get_embedding_service,
    get_qdrant_service,
    get_snapshot_service,
)
from app.db.models.enums import SnapshotStatus
from app.services.qdrant import RetrievedChunk


def _mock_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        text_content="This is test content about quantum physics" * 3,
        score=0.85,
        anchor_metadata={
            "anchor_page": 5,
            "anchor_chapter": "Quantum Basics",
            "anchor_section": "Introduction",
            "anchor_timecode": None,
        },
    )


@pytest.mark.asyncio
async def test_draft_test_happy_path_hybrid(admin_app) -> None:
    draft_snapshot_id = uuid.uuid4()
    mock_snapshot = SimpleNamespace(
        id=draft_snapshot_id,
        name="Test Draft",
        status=SnapshotStatus.DRAFT,
        chunk_count=10,
    )

    snapshot_service = SimpleNamespace(
        get_snapshot=AsyncMock(return_value=mock_snapshot),
    )
    embedding_service = SimpleNamespace(
        embed_texts=AsyncMock(return_value=[[0.1] * 3072]),
    )
    mock_results = [_mock_chunk()]
    qdrant_service = SimpleNamespace(
        hybrid_search=AsyncMock(return_value=mock_results),
        dense_search=AsyncMock(return_value=mock_results),
        keyword_search=AsyncMock(return_value=mock_results),
    )

    # Need to mock session for the indexed count query and source title lookup
    mock_session = AsyncMock()
    # Mock the indexed count query result
    mock_scalar_result = AsyncMock()
    mock_scalar_result.scalar_one = lambda: 10
    mock_session.execute = AsyncMock(return_value=mock_scalar_result)
    # Mock source title lookup
    mock_source = SimpleNamespace(title="Test Source")
    mock_session.get = AsyncMock(return_value=mock_source)

    from app.db.session import get_session
    admin_app.dependency_overrides[get_snapshot_service] = lambda: snapshot_service
    admin_app.dependency_overrides[get_embedding_service] = lambda: embedding_service
    admin_app.dependency_overrides[get_qdrant_service] = lambda: qdrant_service
    admin_app.dependency_overrides[get_session] = lambda: mock_session

    try:
        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                f"/api/admin/snapshots/{draft_snapshot_id}/test",
                json={"query": "quantum physics", "mode": "hybrid", "top_n": 5},
            )
    finally:
        admin_app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_id"] == str(draft_snapshot_id)
    assert body["snapshot_name"] == "Test Draft"
    assert body["query"] == "quantum physics"
    assert body["mode"] == "hybrid"
    assert len(body["results"]) == 1
    assert body["results"][0]["score"] == 0.85
    assert body["results"][0]["anchor"]["page"] == 5
    assert body["results"][0]["anchor"]["chapter"] == "Quantum Basics"
    assert body["results"][0]["source_title"] == "Test Source"
    assert len(body["results"][0]["text_content"]) <= 500

    # Verify correct services were called
    embedding_service.embed_texts.assert_called_once()
    qdrant_service.hybrid_search.assert_called_once()


@pytest.mark.asyncio
async def test_draft_test_sparse_mode_skips_embedding(admin_app) -> None:
    draft_snapshot_id = uuid.uuid4()
    mock_snapshot = SimpleNamespace(
        id=draft_snapshot_id, name="Draft", status=SnapshotStatus.DRAFT, chunk_count=5
    )
    snapshot_service = SimpleNamespace(get_snapshot=AsyncMock(return_value=mock_snapshot))
    embedding_service = SimpleNamespace(embed_texts=AsyncMock())
    qdrant_service = SimpleNamespace(keyword_search=AsyncMock(return_value=[]))

    mock_session = AsyncMock()
    mock_scalar_result = AsyncMock()
    mock_scalar_result.scalar_one = lambda: 5
    mock_session.execute = AsyncMock(return_value=mock_scalar_result)

    from app.db.session import get_session
    admin_app.dependency_overrides[get_snapshot_service] = lambda: snapshot_service
    admin_app.dependency_overrides[get_embedding_service] = lambda: embedding_service
    admin_app.dependency_overrides[get_qdrant_service] = lambda: qdrant_service
    admin_app.dependency_overrides[get_session] = lambda: mock_session

    try:
        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                f"/api/admin/snapshots/{draft_snapshot_id}/test",
                json={"query": "test", "mode": "sparse"},
            )
    finally:
        admin_app.dependency_overrides.clear()

    assert response.status_code == 200
    # Sparse mode should NOT call embedding service
    embedding_service.embed_texts.assert_not_called()
    qdrant_service.keyword_search.assert_called_once()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/integration/test_snapshot_api.py -k "draft_test" -v && python -m pytest tests/unit/test_admin_draft_test.py -v`
Expected: FAIL — 404 (endpoint doesn't exist)

- [ ] **Step 4: Implement draft test endpoint**

Add to `backend/app/api/admin.py`:

```python
@router.post(
    "/snapshots/{snapshot_id}/test",
    response_model=DraftTestResponse,
    status_code=200,
)
async def test_draft_snapshot(
    snapshot_id: uuid.UUID,
    body: DraftTestRequest,
    agent_id: uuid.UUID = Query(default=DEFAULT_AGENT_ID),
    knowledge_base_id: uuid.UUID = Query(default=DEFAULT_KNOWLEDGE_BASE_ID),
    snapshot_service: SnapshotService = Depends(get_snapshot_service),
    embedding_service: EmbeddingService = Depends(get_embedding_service),
    qdrant_service: QdrantService = Depends(get_qdrant_service),
    session: AsyncSession = Depends(get_session),
) -> DraftTestResponse:
    # Validate snapshot is DRAFT
    snapshot = await snapshot_service.get_snapshot(
        snapshot_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Snapshot {snapshot_id} not found")
    if snapshot.status != SnapshotStatus.DRAFT:
        raise HTTPException(
            status_code=422,
            detail="Only draft snapshots can be tested",
        )
    # Count actual INDEXED chunks (chunk_count includes all statuses)
    from app.db.models import Chunk
    from app.db.models.enums import ChunkStatus as CS
    indexed_count_stmt = select(func.count()).where(
        Chunk.snapshot_id == snapshot_id,
        Chunk.status == CS.INDEXED,
    )
    indexed_count = (await session.execute(indexed_count_stmt)).scalar_one()
    if indexed_count < 1:
        raise HTTPException(
            status_code=422,
            detail="Draft has no indexed chunks",
        )

    # Perform retrieval based on mode
    results: list[RetrievedChunk] = []
    if body.mode in (RetrievalMode.HYBRID, RetrievalMode.DENSE):
        embeddings = await embedding_service.embed_texts(
            [body.query], task_type="RETRIEVAL_QUERY"
        )
        query_vector = embeddings[0] if embeddings else []

        if body.mode == RetrievalMode.HYBRID:
            results = await qdrant_service.hybrid_search(
                text=body.query,
                vector=query_vector,
                snapshot_id=snapshot_id,
                agent_id=agent_id,
                knowledge_base_id=knowledge_base_id,
                limit=body.top_n,
            )
        else:
            results = await qdrant_service.dense_search(
                vector=query_vector,
                snapshot_id=snapshot_id,
                agent_id=agent_id,
                knowledge_base_id=knowledge_base_id,
                limit=body.top_n,
            )
    elif body.mode == RetrievalMode.SPARSE:
        results = await qdrant_service.keyword_search(
            text=body.query,
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            limit=body.top_n,
        )

    # Enrich with source titles
    source_ids = {r.source_id for r in results}
    source_titles: dict[uuid.UUID, str | None] = {}
    if source_ids:
        from app.db.models import Source
        for sid in source_ids:
            source = await session.get(Source, sid)
            source_titles[sid] = source.title if source else None

    # Build response
    test_results = [
        DraftTestResult(
            chunk_id=r.chunk_id,
            source_id=r.source_id,
            source_title=source_titles.get(r.source_id),
            text_content=r.text_content[:500] if r.text_content else "",
            score=r.score,
            anchor=DraftTestAnchor(
                page=r.anchor_metadata.get("anchor_page"),
                chapter=r.anchor_metadata.get("anchor_chapter"),
                section=r.anchor_metadata.get("anchor_section"),
                timecode=r.anchor_metadata.get("anchor_timecode"),
            ),
        )
        for r in results
    ]

    return DraftTestResponse(
        snapshot_id=snapshot_id,
        snapshot_name=snapshot.name,
        query=body.query,
        mode=body.mode,
        results=test_results,
        total_chunks_in_draft=snapshot.chunk_count,
    )
```

Update imports in `admin.py`:
- Add `DraftTestRequest`, `DraftTestResponse`, `DraftTestResult`, `DraftTestAnchor`, `RetrievalMode` from snapshot_schemas
- Add `RetrievedChunk` from `app.services.qdrant`
- Add `EmbeddingService` from `app.services.embedding`
- Add `get_embedding_service` from `app.api.dependencies`
- Add `func, select` from `sqlalchemy` (for indexed count query)

**IMPORTANT: Create `get_embedding_service` in `backend/app/api/dependencies.py`** — it does not exist yet. Add:

```python
from app.services.embedding import EmbeddingService

def get_embedding_service(request: Request) -> EmbeddingService:
    return request.app.state.embedding_service
```

Verify that `app.state.embedding_service` is set during app startup (check `backend/app/main.py` lifespan). If not, add it there following the pattern of `app.state.qdrant_service`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/integration/test_snapshot_api.py -k "draft_test" -v && python -m pytest tests/unit/test_admin_draft_test.py -v`
Expected: ALL PASS — validation tests (422/404) + happy path (200 with mocked services) + sparse mode test.

- [ ] **Step 6: Run all snapshot API tests**

Run: `cd backend && python -m pytest tests/integration/test_snapshot_api.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit (only if user explicitly requests)**

Proposed message: `feat(api): add draft test endpoint POST /api/admin/snapshots/{id}/test (S3-05)`
Files: `backend/app/api/snapshot_schemas.py`, `backend/app/api/admin.py`, `backend/app/api/dependencies.py`, `backend/tests/integration/test_snapshot_api.py`, `backend/tests/unit/test_admin_draft_test.py`

---

## Task 4: Source Soft Delete — Service

**Files:**
- Create: `backend/app/services/source_delete.py`
- Create: `backend/tests/integration/test_source_soft_delete.py`

- [ ] **Step 1: Write failing test — soft delete source in draft only**

Create `backend/tests/integration/test_source_soft_delete.py`:

```python
"""Tests for source soft delete with draft cascade."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import Chunk, KnowledgeSnapshot, Source
from app.db.models.enums import (
    ChunkStatus,
    SnapshotStatus,
    SourceStatus,
    SourceType,
)
from app.services.source_delete import (
    SourceDeleteResult,
    SourceDeleteService,
    SourceNotFoundError,
)


async def _create_source(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: SourceStatus = SourceStatus.READY,
    title: str = "Test Source",
) -> uuid.UUID:
    source_id = uuid.uuid7()
    async with session_factory() as session:
        source = Source(
            id=source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            source_type=SourceType.MARKDOWN,
            title=title,
            status=status,
            file_path=f"test/{source_id}.md",
        )
        session.add(source)
        await session.commit()
    return source_id


async def _create_doc_version(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_id: uuid.UUID,
) -> uuid.UUID:
    """Create a real Document + DocumentVersion to satisfy FK constraints on Chunk."""
    from app.db.models import Document, DocumentVersion
    from app.db.models.enums import DocumentStatus, DocumentVersionStatus
    doc_id = uuid.uuid7()
    version_id = uuid.uuid7()
    async with session_factory() as session:
        doc = Document(
            id=doc_id,
            agent_id=DEFAULT_AGENT_ID,
            # Note: Document uses TenantMixin (owner_id, agent_id) but NOT
            # KnowledgeScopeMixin — no knowledge_base_id field.
            source_id=source_id,
            title="Test Doc",
            status=DocumentStatus.READY,
        )
        version = DocumentVersion(
            id=version_id,
            document_id=doc_id,
            version_number=1,
            file_path=f"test/{source_id}/v1",
            status=DocumentVersionStatus.READY,
        )
        session.add_all([doc, version])
        await session.commit()
    return version_id


async def _create_chunk_in_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    document_version_id: uuid.UUID | None = None,
) -> uuid.UUID:
    # If no document_version_id provided, create real Document + DocumentVersion
    if document_version_id is None:
        document_version_id = await _create_doc_version(
            session_factory, source_id=source_id
        )
    chunk_id = uuid.uuid7()
    async with session_factory() as session:
        chunk = Chunk(
            id=chunk_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            source_id=source_id,
            snapshot_id=snapshot_id,
            document_version_id=document_version_id,
            chunk_index=0,
            text_content="test content",
            status=ChunkStatus.INDEXED,
        )
        session.add(chunk)
        await session.commit()
    return chunk_id


@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_soft_delete_source_in_draft_removes_chunks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_source(session_factory)

    # Create draft snapshot with a chunk from this source
    draft_id = uuid.uuid7()
    async with session_factory() as session:
        draft = KnowledgeSnapshot(
            id=draft_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            name="Draft",
            status=SnapshotStatus.DRAFT,
            chunk_count=1,
        )
        session.add(draft)
        await session.commit()

    chunk_id = await _create_chunk_in_snapshot(
        session_factory, source_id=source_id, snapshot_id=draft_id
    )

    async with session_factory() as session:
        service = SourceDeleteService(session, qdrant_service=None)  # No Qdrant in unit test
        result = await service.soft_delete(source_id)

    assert result.source.status == SourceStatus.DELETED
    assert result.source.deleted_at is not None
    assert len(result.warnings) == 0

    # Verify chunk removed from PG
    async with session_factory() as session:
        chunk = await session.get(Chunk, chunk_id)
        assert chunk is None

    # Verify draft chunk_count decremented
    async with session_factory() as session:
        draft = await session.get(KnowledgeSnapshot, draft_id)
        assert draft.chunk_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/integration/test_source_soft_delete.py::test_soft_delete_source_in_draft_removes_chunks -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.source_delete'`

- [ ] **Step 3: Implement SourceDeleteService**

Create `backend/app/services/source_delete.py`:

```python
"""Source soft delete with cascade to draft snapshot chunks."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import Chunk, KnowledgeSnapshot, Source
from app.db.models.enums import ChunkStatus, SnapshotStatus, SourceStatus


logger = structlog.get_logger(__name__)


class SourceNotFoundError(RuntimeError):
    pass


@dataclass(slots=True)
class SourceDeleteResult:
    source: Source
    warnings: list[str] = field(default_factory=list)


class SourceDeleteService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        qdrant_service: object | None = None,  # QdrantService, optional for tests
    ) -> None:
        self._session = session
        self._qdrant_service = qdrant_service

    async def soft_delete(
        self,
        source_id: uuid.UUID,
        *,
        agent_id: uuid.UUID = DEFAULT_AGENT_ID,
        knowledge_base_id: uuid.UUID = DEFAULT_KNOWLEDGE_BASE_ID,
    ) -> SourceDeleteResult:
        # Scope-aware lookup: verify source belongs to the requested scope
        stmt = select(Source).where(
            Source.id == source_id,
            Source.agent_id == agent_id,
            Source.knowledge_base_id == knowledge_base_id,
        )
        source = (await self._session.execute(stmt)).scalar_one_or_none()
        if source is None:
            raise SourceNotFoundError(f"Source {source_id} not found")

        # Idempotent: already deleted
        if source.status == SourceStatus.DELETED:
            return SourceDeleteResult(source=source, warnings=[])

        # Mark source as deleted
        source.status = SourceStatus.DELETED
        source.deleted_at = datetime.now(UTC)

        warnings: list[str] = []

        # Find chunks grouped by snapshot status
        chunk_snapshot_stmt = (
            select(
                Chunk.id,
                Chunk.snapshot_id,
                KnowledgeSnapshot.status.label("snapshot_status"),
            )
            .join(KnowledgeSnapshot, Chunk.snapshot_id == KnowledgeSnapshot.id)
            .where(Chunk.source_id == source_id)
        )
        rows = (await self._session.execute(chunk_snapshot_stmt)).all()

        draft_chunk_ids: list[uuid.UUID] = []
        draft_snapshot_ids: set[uuid.UUID] = set()
        published_active_count = 0

        for row in rows:
            if row.snapshot_status == SnapshotStatus.DRAFT:
                draft_chunk_ids.append(row.id)
                draft_snapshot_ids.add(row.snapshot_id)
            elif row.snapshot_status in (
                SnapshotStatus.PUBLISHED,
                SnapshotStatus.ACTIVE,
            ):
                published_active_count += 1

        # Delete draft chunks from PG
        if draft_chunk_ids:
            for chunk_id in draft_chunk_ids:
                chunk = await self._session.get(Chunk, chunk_id)
                if chunk is not None:
                    await self._session.delete(chunk)

            # Decrement chunk_count for affected drafts
            for snap_id in draft_snapshot_ids:
                draft_count = sum(
                    1 for r in rows
                    if r.snapshot_id == snap_id and r.snapshot_status == SnapshotStatus.DRAFT
                )
                snapshot = await self._session.get(KnowledgeSnapshot, snap_id)
                if snapshot is not None:
                    snapshot.chunk_count = max(0, snapshot.chunk_count - draft_count)

        # Build warnings for published/active
        if published_active_count > 0:
            # Count distinct published/active snapshots
            snap_count_stmt = (
                select(func.count(func.distinct(Chunk.snapshot_id)))
                .join(KnowledgeSnapshot, Chunk.snapshot_id == KnowledgeSnapshot.id)
                .where(
                    Chunk.source_id == source_id,
                    KnowledgeSnapshot.status.in_([
                        SnapshotStatus.PUBLISHED,
                        SnapshotStatus.ACTIVE,
                    ]),
                )
            )
            snap_count = (await self._session.execute(snap_count_stmt)).scalar_one()
            warnings.append(
                f"Source is referenced in {snap_count} published/active snapshot(s). "
                "Chunks will remain visible until a new snapshot replaces them."
            )

        # Delete from Qdrant BEFORE PG commit.
        # Ordering rationale and failure modes:
        #
        # SUCCESS: Qdrant delete OK → PG commit OK → clean state.
        #
        # FAILURE MODE 1: Qdrant delete OK → PG commit FAILS.
        #   Impact: source stays non-DELETED in PG, but draft vectors are gone.
        #   Draft chunks in PG have no vectors → invisible to search (not harmful).
        #   Recovery: retry the soft_delete call — it will attempt Qdrant delete
        #   again (idempotent for already-deleted points) and then PG commit.
        #
        # FAILURE MODE 2: Qdrant delete FAILS (raises).
        #   Impact: nothing committed to PG either — fully consistent.
        #   Recovery: retry the soft_delete call.
        #
        # Why NOT PG-first: if PG commits but Qdrant fails, orphaned vectors
        # remain searchable via draft test endpoint, and the idempotent return
        # path (source already DELETED) won't know which chunk_ids to retry.
        if draft_chunk_ids and self._qdrant_service is not None:
            await self._qdrant_service.delete_chunks(draft_chunk_ids)

        await self._session.commit()

        if draft_chunk_ids:
            logger.info(
                "source_delete.draft_chunks_removed",
                source_id=str(source_id),
                chunk_count=len(draft_chunk_ids),
            )

        logger.info(
            "source_delete.completed",
            source_id=str(source_id),
            draft_chunks_removed=len(draft_chunk_ids),
            published_chunks_preserved=published_active_count,
            warning_count=len(warnings),
        )

        return SourceDeleteResult(source=source, warnings=warnings)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/integration/test_source_soft_delete.py::test_soft_delete_source_in_draft_removes_chunks -v`
Expected: PASS

- [ ] **Step 5: Write test — soft delete source in published (warnings)**

```python
@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_soft_delete_source_in_published_returns_warnings(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_source(session_factory)

    pub_id = uuid.uuid7()
    async with session_factory() as session:
        pub = KnowledgeSnapshot(
            id=pub_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            name="Published",
            status=SnapshotStatus.PUBLISHED,
            chunk_count=1,
            published_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        session.add(pub)
        await session.commit()

    chunk_id = await _create_chunk_in_snapshot(
        session_factory, source_id=source_id, snapshot_id=pub_id
    )

    async with session_factory() as session:
        service = SourceDeleteService(session, qdrant_service=None)
        result = await service.soft_delete(source_id)

    assert result.source.status == SourceStatus.DELETED
    assert len(result.warnings) == 1
    assert "1 published/active snapshot(s)" in result.warnings[0]

    # Verify chunk NOT removed
    async with session_factory() as session:
        chunk = await session.get(Chunk, chunk_id)
        assert chunk is not None
```

- [ ] **Step 6: Write test — idempotent re-delete**

```python
@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_soft_delete_already_deleted_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id = await _create_source(session_factory, status=SourceStatus.DELETED)

    # Manually set deleted_at
    async with session_factory() as session:
        source = await session.get(Source, source_id)
        source.deleted_at = datetime(2026, 1, 1, tzinfo=UTC)
        await session.commit()

    async with session_factory() as session:
        service = SourceDeleteService(session, qdrant_service=None)
        result = await service.soft_delete(source_id)

    assert result.source.status == SourceStatus.DELETED
    assert len(result.warnings) == 0
```

- [ ] **Step 7: Write test — not found**

```python
@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_soft_delete_not_found_raises_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        service = SourceDeleteService(session, qdrant_service=None)
        with pytest.raises(SourceNotFoundError):
            await service.soft_delete(uuid.uuid4())
```

- [ ] **Step 8: Run all soft delete tests**

Run: `cd backend && python -m pytest tests/integration/test_source_soft_delete.py -v`
Expected: ALL PASS

- [ ] **Step 9: Commit (only if user explicitly requests)**

Proposed message: `feat(source): add soft delete service with draft cascade (S3-05)`
Files: `backend/app/services/source_delete.py`, `backend/tests/integration/test_source_soft_delete.py`

---

## Task 5: Source Soft Delete — API Endpoint

**Files:**
- Create: `backend/app/api/source_schemas.py`
- Modify: `backend/app/api/admin.py` (add DELETE endpoint)
- Modify: `backend/tests/integration/test_source_soft_delete.py` (add API tests)

- [ ] **Step 1: Create SourceDeleteResponse schema**

Create `backend/app/api/source_schemas.py`:

```python
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models.enums import SourceStatus, SourceType


class SourceDeleteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_type: SourceType
    status: SourceStatus
    deleted_at: datetime | None
    warnings: list[str]
```

- [ ] **Step 2: Write failing API test**

Add to `backend/tests/integration/test_source_soft_delete.py`:

```python
@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_delete_source_endpoint_returns_200(
    session_factory: async_sessionmaker[AsyncSession],
    api_client: AsyncClient,
) -> None:
    source_id = await _create_source(session_factory)

    response = await api_client.delete(f"/api/admin/sources/{source_id}")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "deleted"
    assert body["deleted_at"] is not None
    assert body["warnings"] == []


@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_delete_source_endpoint_returns_404(
    api_client: AsyncClient,
) -> None:
    response = await api_client.delete(f"/api/admin/sources/{uuid.uuid4()}")
    assert response.status_code == 404
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/integration/test_source_soft_delete.py -k "endpoint" -v`
Expected: FAIL — 404/405 (endpoint doesn't exist)

- [ ] **Step 4: Implement DELETE endpoint**

Add to `backend/app/api/admin.py`:

```python
@router.delete(
    "/sources/{source_id}",
    response_model=SourceDeleteResponse,
    status_code=200,
)
async def delete_source(
    source_id: uuid.UUID,
    agent_id: uuid.UUID = Query(default=DEFAULT_AGENT_ID),
    knowledge_base_id: uuid.UUID = Query(default=DEFAULT_KNOWLEDGE_BASE_ID),
    session: AsyncSession = Depends(get_session),
    qdrant_service: QdrantService = Depends(get_qdrant_service),
) -> SourceDeleteResponse:
    service = SourceDeleteService(session, qdrant_service=qdrant_service)
    try:
        result = await service.soft_delete(
            source_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
        )
    except SourceNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return SourceDeleteResponse(
        id=result.source.id,
        title=result.source.title,
        source_type=result.source.source_type,
        status=result.source.status,
        deleted_at=result.source.deleted_at,
        warnings=result.warnings,
    )
```

Update imports: add `SourceDeleteResponse` from source_schemas, `SourceDeleteService` and `SourceNotFoundError` from source_delete service.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/integration/test_source_soft_delete.py -k "endpoint" -v`
Expected: PASS

- [ ] **Step 6: Run all tests**

Run: `cd backend && python -m pytest tests/integration/test_source_soft_delete.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit (only if user explicitly requests)**

Proposed message: `feat(api): add source soft delete endpoint DELETE /api/admin/sources/{id} (S3-05)`
Files: `backend/app/api/source_schemas.py`, `backend/app/api/admin.py`, `backend/tests/integration/test_source_soft_delete.py`

---

## Task 6: Ingestion Guard

**Files:**
- Modify: `backend/app/workers/tasks/ingestion.py` (in `_process_task()`, between lines 131-132 — before `_load_pipeline_services`)
- Modify: `backend/tests/integration/test_source_soft_delete.py` (add ingestion guard test)

- [ ] **Step 1: Write failing test**

Add to `backend/tests/integration/test_source_soft_delete.py`:

```python
from app.db.models import BackgroundTask
from app.db.models.enums import BackgroundTaskStatus, BackgroundTaskType
from app.workers.tasks.ingestion import process_ingestion


@pytest.mark.anyio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_ingestion_rejects_deleted_source(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Guard must fire BEFORE source.status is overwritten to PROCESSING."""
    source_id = await _create_source(session_factory, status=SourceStatus.DELETED)

    # Manually set deleted_at (dual-field contract)
    async with session_factory() as session:
        source = await session.get(Source, source_id)
        source.deleted_at = datetime(2026, 1, 1, tzinfo=UTC)
        await session.commit()

    # Create a PENDING task for this source
    task_id = uuid.uuid7()
    async with session_factory() as session:
        task = BackgroundTask(
            id=task_id,
            agent_id=DEFAULT_AGENT_ID,
            task_type=BackgroundTaskType.INGESTION,
            status=BackgroundTaskStatus.PENDING,
            source_id=source_id,
        )
        session.add(task)
        await session.commit()

    # Call process_ingestion with a real session_factory in ctx.
    # process_ingestion() at line 98 immediately reads ctx["session_factory"]
    # and opens a session. The guard in _process_task() fires BEFORE
    # _load_pipeline_services(ctx), so pipeline services are never needed.
    mock_ctx: dict[str, Any] = {
        "session_factory": session_factory,
        "job_id": "test-job",
        # Pipeline service keys not needed — guard fires before _load_pipeline_services
    }
    await process_ingestion(mock_ctx, str(task_id))

    # Verify task was marked FAILED with the guard message
    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        assert task.status == BackgroundTaskStatus.FAILED
        assert "deleted before processing" in task.error_message
```

Note: Add `from typing import Any` to the test file imports. The `session_factory` fixture is already available as a test parameter. `process_ingestion` opens its own session via `session_factory()`, so the guard runs inside that session.

- [ ] **Step 2: Add source status guard to ingestion pipeline**

In `backend/app/workers/tasks/ingestion.py`, in `_process_task()` (~line 113) — insert **between** line 131 (`source = await session.get(...)`) and line 132 (`services = _load_pipeline_services(ctx)`). The guard MUST be before both `_load_pipeline_services` (which is unnecessary for a deleted source) and the `try:` block that sets `source.status = PROCESSING`:

```python
    source = await session.get(Source, task.source_id) if task.source_id else None

    # >>> INSERT HERE: Guard for deleted sources <<<
    if source is not None and source.status == SourceStatus.DELETED:
        task.status = BackgroundTaskStatus.FAILED
        task.error_message = "Source was deleted before processing completed"
        task.completed_at = datetime.now(UTC)
        await session.commit()
        logger.warning(
            "worker.ingestion.source_deleted",
            task_id=str(task_id),
            source_id=str(source.id),
        )
        return

    services = _load_pipeline_services(ctx)  # existing line 132 — now comes AFTER guard
```

Make sure `SourceStatus` is imported (check existing imports — already there since `SourceStatus.FAILED` is used at line 156).

- [ ] **Step 3: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 4: Commit (only if user explicitly requests)**

Proposed message: `feat(worker): add source status guard in ingestion pipeline (S3-05)`
Files: `backend/app/workers/tasks/ingestion.py`, `backend/tests/integration/test_source_soft_delete.py`

---

## Task 7: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 2: Run linter**

Run: `cd backend && ruff check .`
Expected: No errors

- [ ] **Step 3: Run type checker (if configured)**

Run: `cd backend && mypy app/ --ignore-missing-imports` (or whatever is configured)
Expected: No new errors

- [ ] **Step 4: Verify no regressions in existing endpoints**

Run: `cd backend && python -m pytest tests/integration/test_snapshot_lifecycle.py tests/integration/test_snapshot_api.py -v`
Expected: ALL PASS (including all pre-existing tests)

- [ ] **Step 5: Re-read `docs/development.md` and self-review**

Verify:
- No mocks outside `tests/`
- No fallbacks to stubs
- All stubs reference specific story IDs
- Both `status` and `deleted_at` set together for soft delete (dual-field contract)
- Error handling follows existing patterns
- Services are properly isolated (SRP)

- [ ] **Step 6: Final commit (only if user explicitly requests)**

Proposed message: `chore(s3-05): final cleanup and verification`
Stage only the specific files that were modified during cleanup.

---

## Post-implementation Checklist

Per CLAUDE.md requirements:

- [ ] Re-read `docs/development.md` — self-review completed
- [ ] All package versions at or above `docs/spec.md` minimums
- [ ] CI tests pass
- [ ] Stable behavior covered by tests
- [ ] Pre-code read and post-code self-review explicitly stated in apply report
