# S3-02: BM25 Sparse Vectors — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Qdrant BM25 sparse vector indexing alongside dense vectors, with a keyword search endpoint for verification.

**Architecture:** Extend the existing Qdrant collection with a named sparse vector `"bm25"`. At upsert time, pass chunk text as `models.Document(model="Qdrant/bm25")` alongside the dense vector. Add `keyword_search` method to QdrantService and expose it via `POST /api/admin/search/keyword`. Configured BM25 language is logged at startup; changing it requires manual collection deletion + re-ingest.

**Tech Stack:** qdrant-client >=1.16.0, Qdrant Document API, Bm25Config, FastAPI, pytest

**Spec:** `docs/superpowers/specs/2026-03-22-s3-02-bm25-sparse-vectors-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/pyproject.toml` | Bump qdrant-client dependency |
| `backend/app/services/qdrant.py` | BM25 collection config, upsert with Document, keyword_search, auto-recreate on missing BM25 |
| `backend/app/workers/main.py` | Pass bm25_language to QdrantService |
| `backend/app/main.py` | Pass bm25_language to QdrantService |
| `backend/app/api/admin.py` | Keyword search endpoint |
| `backend/app/api/dependencies.py` | Qdrant service dependency getter |
| `backend/app/api/schemas.py` | Request/response models for keyword search |
| `backend/tests/unit/services/test_qdrant.py` | Unit tests for BM25 collection, upsert, keyword_search |
| `backend/tests/unit/test_admin_keyword_search.py` | Unit tests for endpoint |
| `backend/tests/integration/test_qdrant_roundtrip.py` | Integration tests with real Qdrant |

---

### Task 1: Bump qdrant-client dependency

**Files:**
- Modify: `backend/pyproject.toml:17`

- [ ] **Step 1: Bump qdrant-client**

In `backend/pyproject.toml`, change line 17:

```
  "qdrant-client>=1.14.1",
```

to:

```
  "qdrant-client>=1.16.0",
```

- [ ] **Step 2: Lock and verify import**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv lock && uv run python -c "from qdrant_client import models; print(models.Bm25Config); print(models.Document)"
```

Expected: no ImportError, prints class references.

- [ ] **Step 3: Propose commit**

Proposed message: `build: bump qdrant-client to >=1.16.0 for BM25 Document API`
Files: `backend/pyproject.toml`, `backend/uv.lock`

---

### Task 2: Extend QdrantService constructor and ensure_collection for BM25

**Files:**
- Modify: `backend/app/services/qdrant.py:63-109`
- Test: `backend/tests/unit/services/test_qdrant.py`

- [ ] **Step 1: Write failing tests for BM25 collection creation**

Add to `backend/tests/unit/services/test_qdrant.py`:

```python
def _collection_info_with_sparse(size: int) -> SimpleNamespace:
    return SimpleNamespace(
        config=SimpleNamespace(
            params=SimpleNamespace(
                vectors={"dense": SimpleNamespace(size=size)},
                sparse_vectors={"bm25": SimpleNamespace()},
            )
        )
    )


@pytest.mark.asyncio
async def test_ensure_collection_creates_dense_and_sparse_vectors() -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=False),
        create_collection=AsyncMock(),
        create_payload_index=AsyncMock(),
    )
    service = QdrantService(
        client=client,
        collection_name="proxymind_chunks",
        embedding_dimensions=3072,
        bm25_language="english",
    )

    await service.ensure_collection()

    kwargs = client.create_collection.await_args.kwargs
    assert "dense" in kwargs["vectors_config"]
    assert "bm25" in kwargs["sparse_vectors_config"]
    sparse_config = kwargs["sparse_vectors_config"]["bm25"]
    assert sparse_config.modifier is models.Modifier.IDF


@pytest.mark.asyncio
async def test_ensure_collection_recreates_when_sparse_vector_missing() -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=_collection_info(3072)),
        delete_collection=AsyncMock(),
        create_collection=AsyncMock(),
        create_payload_index=AsyncMock(),
    )
    service = QdrantService(
        client=client,
        collection_name="proxymind_chunks",
        embedding_dimensions=3072,
        bm25_language="english",
    )

    await service.ensure_collection()

    client.delete_collection.assert_awaited_once_with("proxymind_chunks")
    client.create_collection.assert_awaited_once()


@pytest.mark.asyncio
async def test_safe_delete_handles_404_when_already_deleted() -> None:
    """Race: another process already deleted the collection."""
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=_collection_info(3072)),
        delete_collection=AsyncMock(
            side_effect=UnexpectedResponse(
                status_code=404,
                reason_phrase="Not Found",
                content=b"{}",
                headers=httpx.Headers(),
            )
        ),
        create_collection=AsyncMock(),
        create_payload_index=AsyncMock(),
    )
    service = QdrantService(
        client=client,
        collection_name="proxymind_chunks",
        embedding_dimensions=3072,
        bm25_language="english",
    )

    await service.ensure_collection()

    client.delete_collection.assert_awaited_once()
    client.create_collection.assert_awaited_once()


@pytest.mark.asyncio
async def test_safe_create_handles_409_when_already_created() -> None:
    """Race: another process already recreated the collection."""
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=_collection_info(3072)),
        delete_collection=AsyncMock(),
        create_collection=AsyncMock(
            side_effect=UnexpectedResponse(
                status_code=409,
                reason_phrase="Conflict",
                content=b'{"status":{"error":"Collection already exists"}}',
                headers=httpx.Headers(),
            )
        ),
        create_payload_index=AsyncMock(),
    )
    service = QdrantService(
        client=client,
        collection_name="proxymind_chunks",
        embedding_dimensions=3072,
        bm25_language="english",
    )

    await service.ensure_collection()

    client.delete_collection.assert_awaited_once()
    client.create_collection.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_collection_idempotent_when_schema_matches() -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=_collection_info_with_sparse(3072)),
        create_collection=AsyncMock(),
        delete_collection=AsyncMock(),
        create_payload_index=AsyncMock(),
    )
    service = QdrantService(
        client=client,
        collection_name="proxymind_chunks",
        embedding_dimensions=3072,
        bm25_language="english",
    )

    await service.ensure_collection()

    client.create_collection.assert_not_awaited()
    client.delete_collection.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_qdrant.py -v -k "sparse or sentinel or recreates or idempotent_when_schema"
```

Expected: FAIL (QdrantService missing `bm25_language` parameter).

- [ ] **Step 3: Implement constructor and ensure_collection changes**

In `backend/app/services/qdrant.py`:

1. Add structlog import at module level:

```python
import structlog

logger = structlog.get_logger(__name__)
```

2. Extend `__init__`:

```python
def __init__(
    self,
    *,
    client: AsyncQdrantClient,
    collection_name: str,
    embedding_dimensions: int,
    bm25_language: str = "english",
) -> None:
    self._client = client
    self._collection_name = collection_name
    self._embedding_dimensions = embedding_dimensions
    self._bm25_language = bm25_language
```

3. Rewrite `ensure_collection`:

```python
async def ensure_collection(self) -> None:
    collection_info: Any | None = None
    if await self._client.collection_exists(self._collection_name):
        collection_info = await self._client.get_collection(self._collection_name)
    else:
        try:
            await self._create_collection()
        except UnexpectedResponse as error:
            if not self._is_collection_exists_conflict(error):
                raise
            collection_info = await self._client.get_collection(self._collection_name)

    if collection_info is not None:
        # Dense dimension mismatch is a hard error (unchanged from before)
        existing_dimensions = self._get_dense_vector_size(collection_info)
        if existing_dimensions != self._embedding_dimensions:
            raise CollectionSchemaMismatchError(
                "Qdrant collection dimension mismatch: "
                f"existing={existing_dimensions}, required={self._embedding_dimensions}. "
                "Delete the collection and re-run ingestion to reindex."
            )

        # Missing BM25 sparse vector → recreate
        if not self._has_bm25_sparse_vector(collection_info):
            logger.warning(
                "qdrant.collection.missing_bm25",
                collection=self._collection_name,
                action="recreate",
                message="Recreating collection — all existing vectors will be lost. "
                "Re-ingest sources after restart.",
            )
            await self._safe_delete_and_recreate()

    logger.info(
        "qdrant.collection.ready",
        collection=self._collection_name,
        bm25_language=self._bm25_language,
    )

    for field_name in PAYLOAD_INDEX_FIELDS:
        await self._client.create_payload_index(
            collection_name=self._collection_name,
            field_name=field_name,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
```

4. Add helper methods:

```python
@staticmethod
def _has_bm25_sparse_vector(collection_info: Any) -> bool:
    sparse_vectors = getattr(
        collection_info.config.params, "sparse_vectors", None
    )
    return sparse_vectors is not None and "bm25" in sparse_vectors

def _create_collection(self) -> Any:
    return self._client.create_collection(
        collection_name=self._collection_name,
        vectors_config={
            "dense": models.VectorParams(
                size=self._embedding_dimensions,
                distance=models.Distance.COSINE,
            )
        },
        sparse_vectors_config={
            "bm25": models.SparseVectorParams(
                modifier=models.Modifier.IDF,
            )
        },
    )

async def _safe_delete_and_recreate(self) -> None:
    try:
        await self._client.delete_collection(self._collection_name)
    except UnexpectedResponse as error:
        if error.status_code != 404:
            raise
    try:
        await self._create_collection()
    except UnexpectedResponse as error:
        if not self._is_collection_exists_conflict(error):
            raise
```

**No sentinel point, no language fingerprinting.** BM25 language is logged at startup. Changing `BM25_LANGUAGE` in `.env` requires manual collection deletion + re-ingest (documented in spec recovery path). This avoids the race condition between API and worker startup.

- [ ] **Step 4: Update existing tests to pass bm25_language**

All existing `QdrantService(...)` calls in `test_qdrant.py` need `bm25_language="english"` added.

Key updates to existing tests:

**`test_ensure_collection_is_idempotent_for_matching_schema`** — now needs `_collection_info_with_sparse(3072)` instead of `_collection_info(3072)`:

```python
@pytest.mark.asyncio
async def test_ensure_collection_is_idempotent_for_matching_schema() -> None:
    client = SimpleNamespace(
        collection_exists=AsyncMock(return_value=True),
        get_collection=AsyncMock(return_value=_collection_info_with_sparse(3072)),
        create_collection=AsyncMock(),
        delete_collection=AsyncMock(),
        create_payload_index=AsyncMock(),
    )
    service = QdrantService(
        client=client,
        collection_name="proxymind_chunks",
        embedding_dimensions=3072,
        bm25_language="english",
    )

    await service.ensure_collection()

    client.create_collection.assert_not_awaited()
    client.delete_collection.assert_not_awaited()
    assert client.create_payload_index.await_count == len(PAYLOAD_INDEX_FIELDS)
```

**`test_ensure_collection_raises_on_dimension_mismatch`** — unchanged behavior (still raises). Just add `bm25_language="english"` to constructor.

**All other existing tests** — add `bm25_language="english"` to every `QdrantService(...)` constructor call.

- [ ] **Step 5: Run all unit tests**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_qdrant.py -v
```

Expected: all PASS.

- [ ] **Step 6: Propose commit**

Proposed message: `feat(qdrant): add BM25 sparse vector to collection schema`
Files: `backend/app/services/qdrant.py`, `backend/tests/unit/services/test_qdrant.py`

---

### Task 3: Add BM25 Document to upsert

**Files:**
- Modify: `backend/app/services/qdrant.py:111-140`
- Test: `backend/tests/unit/services/test_qdrant.py`

- [ ] **Step 1: Write failing test for BM25 Document in upsert**

Add to `backend/tests/unit/services/test_qdrant.py`:

```python
@pytest.mark.asyncio
async def test_upsert_chunks_includes_bm25_document() -> None:
    client = SimpleNamespace(upsert=AsyncMock())
    service = QdrantService(
        client=client,
        collection_name="proxymind_chunks",
        embedding_dimensions=3,
        bm25_language="english",
    )
    point = QdrantChunkPoint(
        chunk_id=uuid.uuid4(),
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        text_content="hello world keyword search",
        chunk_index=0,
        token_count=5,
        anchor_page=None,
        anchor_chapter=None,
        anchor_section=None,
        anchor_timecode=None,
        source_type=SourceType.MARKDOWN,
        language="english",
        status=ChunkStatus.INDEXED,
    )

    await service.upsert_chunks([point])

    points = client.upsert.await_args.kwargs["points"]
    vector_dict = points[0].vector
    assert "dense" in vector_dict
    assert vector_dict["dense"] == [0.1, 0.2, 0.3]
    bm25_doc = vector_dict["bm25"]
    assert isinstance(bm25_doc, models.Document)
    assert bm25_doc.text == "hello world keyword search"
    assert bm25_doc.model == "Qdrant/bm25"
    assert bm25_doc.options.language == "english"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_qdrant.py::test_upsert_chunks_includes_bm25_document -v
```

Expected: FAIL (vector dict has no "bm25" key).

- [ ] **Step 3: Implement BM25 Document in upsert**

In `backend/app/services/qdrant.py`, modify `upsert_chunks` method. Change the `vector=` line inside `PointStruct`:

```python
vector={
    "dense": chunk.vector,
    "bm25": models.Document(
        text=chunk.text_content,
        model="Qdrant/bm25",
        options=models.Bm25Config(language=self._bm25_language),
    ),
},
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_qdrant.py -v
```

Expected: all PASS. Check that `test_upsert_chunks_sends_named_vector_payload` also still passes (it checks `points[0].vector` — may need updating since vector dict now has `"bm25"` key too).

- [ ] **Step 5: Propose commit**

Proposed message: `feat(qdrant): include BM25 Document in chunk upsert`
Files: `backend/app/services/qdrant.py`, `backend/tests/unit/services/test_qdrant.py`

---

### Task 4: Add keyword_search method to QdrantService

**Files:**
- Modify: `backend/app/services/qdrant.py`
- Test: `backend/tests/unit/services/test_qdrant.py`

- [ ] **Step 1: Write failing tests for keyword_search**

Add to `backend/tests/unit/services/test_qdrant.py`:

```python
@pytest.mark.asyncio
async def test_keyword_search_queries_bm25_vector_with_document() -> None:
    snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    source_id = uuid.uuid4()
    client = SimpleNamespace(
        query_points=AsyncMock(
            return_value=SimpleNamespace(
                points=[
                    SimpleNamespace(
                        score=0.85,
                        payload={
                            "chunk_id": str(chunk_id),
                            "source_id": str(source_id),
                            "text_content": "keyword matched body",
                            "anchor_page": 3,
                            "anchor_chapter": "Ch. 2",
                            "anchor_section": None,
                            "anchor_timecode": None,
                        },
                    )
                ]
            )
        )
    )
    service = QdrantService(
        client=client,
        collection_name="proxymind_chunks",
        embedding_dimensions=3,
        bm25_language="english",
    )

    results = await service.keyword_search(
        text="keyword query",
        snapshot_id=snapshot_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        limit=5,
    )

    assert len(results) == 1
    assert results[0].chunk_id == chunk_id
    assert results[0].text_content == "keyword matched body"
    assert results[0].score == 0.85

    kwargs = client.query_points.await_args.kwargs
    query_doc = kwargs["query"]
    assert isinstance(query_doc, models.Document)
    assert query_doc.text == "keyword query"
    assert query_doc.model == "Qdrant/bm25"
    assert query_doc.options.language == "english"
    assert kwargs["using"] == "bm25"
    assert kwargs["limit"] == 5
    filters = kwargs["query_filter"].must
    assert [(c.key, c.match.value) for c in filters] == [
        ("snapshot_id", str(snapshot_id)),
        ("agent_id", str(agent_id)),
        ("knowledge_base_id", str(knowledge_base_id)),
    ]


@pytest.mark.asyncio
async def test_keyword_search_retries_on_transient_error() -> None:
    client = SimpleNamespace(
        query_points=AsyncMock(
            side_effect=[
                ResponseHandlingException(httpx.ConnectError("boom")),
                SimpleNamespace(points=[]),
            ]
        )
    )
    service = QdrantService(
        client=client,
        collection_name="proxymind_chunks",
        embedding_dimensions=3,
        bm25_language="english",
    )

    results = await service.keyword_search(
        text="retry test",
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
    )

    assert results == []
    assert client.query_points.await_count == 2


@pytest.mark.asyncio
async def test_keyword_search_returns_empty_list_when_no_matches() -> None:
    client = SimpleNamespace(
        query_points=AsyncMock(return_value=SimpleNamespace(points=[]))
    )
    service = QdrantService(
        client=client,
        collection_name="proxymind_chunks",
        embedding_dimensions=3,
        bm25_language="english",
    )

    results = await service.keyword_search(
        text="no match query",
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
    )

    assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_qdrant.py -v -k "keyword_search"
```

Expected: FAIL (QdrantService has no method `keyword_search`).

- [ ] **Step 3: Implement keyword_search**

Add to `QdrantService` in `backend/app/services/qdrant.py`:

```python
async def keyword_search(
    self,
    *,
    text: str,
    snapshot_id: UUID,
    agent_id: UUID,
    knowledge_base_id: UUID,
    limit: int = 10,
) -> list[RetrievedChunk]:
    response = await self._search_points(
        collection_name=self._collection_name,
        query=models.Document(
            text=text,
            model="Qdrant/bm25",
            options=models.Bm25Config(language=self._bm25_language),
        ),
        using="bm25",
        query_filter=models.Filter(
            must=[
                models.FieldCondition(
                    key="snapshot_id",
                    match=models.MatchValue(value=str(snapshot_id)),
                ),
                models.FieldCondition(
                    key="agent_id",
                    match=models.MatchValue(value=str(agent_id)),
                ),
                models.FieldCondition(
                    key="knowledge_base_id",
                    match=models.MatchValue(value=str(knowledge_base_id)),
                ),
            ]
        ),
        limit=limit,
        with_payload=True,
    )
    return [self._to_retrieved_chunk(point) for point in response.points]
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/services/test_qdrant.py -v
```

Expected: all PASS.

- [ ] **Step 5: Propose commit**

Proposed message: `feat(qdrant): add keyword_search method for BM25 sparse vector queries`
Files: `backend/app/services/qdrant.py`, `backend/tests/unit/services/test_qdrant.py`

---

### Task 5: Pass bm25_language to QdrantService in worker and API startup

**Files:**
- Modify: `backend/app/workers/main.py:35-39`
- Modify: `backend/app/main.py:30-37`

- [ ] **Step 1: Update worker startup**

In `backend/app/workers/main.py`, change the `QdrantService(...)` call (line 35-39):

```python
    qdrant_service = QdrantService(
        client=AsyncQdrantClient(url=settings.qdrant_url),
        collection_name=settings.qdrant_collection,
        embedding_dimensions=settings.embedding_dimensions,
        bm25_language=settings.bm25_language,
    )
```

- [ ] **Step 2: Update API startup**

In `backend/app/main.py`, change `_create_qdrant_service` (line 30-37):

```python
def _create_qdrant_service(settings):
    from app.services.qdrant import QdrantService

    return QdrantService(
        client=AsyncQdrantClient(url=settings.qdrant_url),
        collection_name=settings.qdrant_collection,
        embedding_dimensions=settings.embedding_dimensions,
        bm25_language=settings.bm25_language,
    )
```

- [ ] **Step 3: Run existing tests to verify no regressions**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/ -v```

Expected: all PASS.

- [ ] **Step 4: Propose commit**

Proposed message: `feat(startup): pass bm25_language to QdrantService in API and worker`
Files: `backend/app/workers/main.py`, `backend/app/main.py`

---

### Task 6: Add keyword search Admin API endpoint

**Files:**
- Modify: `backend/app/api/admin.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/api/schemas.py` (or create new schema file)
- Test: `backend/tests/unit/test_admin_keyword_search.py`

- [ ] **Step 1: Write failing tests for keyword search endpoint**

Create `backend/tests/unit/test_admin_keyword_search.py`:

```python
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from app.services.qdrant import RetrievedChunk


@pytest.fixture
def mock_qdrant_service() -> SimpleNamespace:
    chunk_id = uuid.uuid7()
    source_id = uuid.uuid7()
    return SimpleNamespace(
        keyword_search=AsyncMock(
            return_value=[
                RetrievedChunk(
                    chunk_id=chunk_id,
                    source_id=source_id,
                    text_content="matched chunk",
                    score=0.85,
                    anchor_metadata={
                        "anchor_page": 42,
                        "anchor_chapter": "Chapter 3",
                        "anchor_section": None,
                        "anchor_timecode": None,
                    },
                )
            ]
        )
    )


@pytest.fixture
def mock_snapshot_service_with_active() -> SimpleNamespace:
    return SimpleNamespace(
        get_active_snapshot=AsyncMock(
            return_value=SimpleNamespace(id=uuid.uuid7())
        ),
    )


@pytest.fixture
def mock_snapshot_service_no_active() -> SimpleNamespace:
    return SimpleNamespace(
        get_active_snapshot=AsyncMock(return_value=None),
    )


def _make_app(
    session_factory,
    mock_qdrant_service,
    mock_snapshot_service,
    mock_storage_service,
    mock_arq_pool,
) -> FastAPI:
    from app.api.admin import router as admin_router
    from app.api.dependencies import get_qdrant_service, get_snapshot_service

    app = FastAPI()
    app.include_router(admin_router)
    app.state.settings = SimpleNamespace(
        upload_max_file_size_mb=100,
        seaweedfs_sources_path="/sources",
        bm25_language="english",
    )
    app.state.session_factory = session_factory
    app.state.storage_service = mock_storage_service
    app.state.arq_pool = mock_arq_pool
    app.state.qdrant_service = mock_qdrant_service
    app.dependency_overrides[get_snapshot_service] = lambda: mock_snapshot_service
    app.dependency_overrides[get_qdrant_service] = lambda: mock_qdrant_service
    return app


@pytest.mark.asyncio
async def test_keyword_search_returns_results(
    session_factory,
    mock_qdrant_service,
    mock_snapshot_service_with_active,
    mock_storage_service,
    mock_arq_pool,
) -> None:
    app = _make_app(
        session_factory,
        mock_qdrant_service,
        mock_snapshot_service_with_active,
        mock_storage_service,
        mock_arq_pool,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/admin/search/keyword",
            json={"query": "test keyword"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["language"] == "english"
    assert data["query"] == "test keyword"
    assert len(data["results"]) == 1
    result = data["results"][0]
    assert result["text_content"] == "matched chunk"
    assert result["score"] == 0.85
    assert result["anchor"]["page"] == 42
    assert result["anchor"]["chapter"] == "Chapter 3"


@pytest.mark.asyncio
async def test_keyword_search_empty_query_returns_422(
    session_factory,
    mock_qdrant_service,
    mock_storage_service,
    mock_arq_pool,
) -> None:
    app = _make_app(
        session_factory,
        mock_qdrant_service,
        SimpleNamespace(get_active_snapshot=AsyncMock(return_value=SimpleNamespace(id=uuid.uuid7()))),
        mock_storage_service,
        mock_arq_pool,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/admin/search/keyword",
            json={"query": ""},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_keyword_search_no_active_snapshot_returns_422(
    session_factory,
    mock_qdrant_service,
    mock_snapshot_service_no_active,
    mock_storage_service,
    mock_arq_pool,
) -> None:
    app = _make_app(
        session_factory,
        mock_qdrant_service,
        mock_snapshot_service_no_active,
        mock_storage_service,
        mock_arq_pool,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/admin/search/keyword",
            json={"query": "test"},
        )

    assert response.status_code == 422
    assert "active snapshot" in response.json()["detail"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/test_admin_keyword_search.py -v
```

Expected: FAIL (endpoint does not exist).

- [ ] **Step 3: Add dependency getter for QdrantService**

In `backend/app/api/dependencies.py`, add:

```python
from app.services.qdrant import QdrantService

def get_qdrant_service(request: Request) -> QdrantService:
    return request.app.state.qdrant_service
```

- [ ] **Step 4: Add request/response schemas**

Add keyword search schemas to `backend/app/api/schemas.py` (or a new file if schemas.py is getting large — check first):

```python
class KeywordSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    snapshot_id: uuid.UUID | None = None
    agent_id: uuid.UUID = DEFAULT_AGENT_ID
    knowledge_base_id: uuid.UUID = DEFAULT_KNOWLEDGE_BASE_ID
    limit: int = Field(default=10, ge=1, le=100)


class AnchorResponse(BaseModel):
    page: int | None = None
    chapter: str | None = None
    section: str | None = None
    timecode: str | None = None


class KeywordSearchResult(BaseModel):
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    text_content: str
    score: float
    anchor: AnchorResponse


class KeywordSearchResponse(BaseModel):
    results: list[KeywordSearchResult]
    query: str
    language: str
    total: int
```

Import `DEFAULT_AGENT_ID` and `DEFAULT_KNOWLEDGE_BASE_ID` from `app.core.constants`.

- [ ] **Step 5: Add endpoint to admin router**

In `backend/app/api/admin.py`, add the endpoint. Import the new dependencies and schemas, then:

```python
from app.api.dependencies import get_qdrant_service, get_snapshot_service
from app.api.schemas import (
    KeywordSearchRequest,
    KeywordSearchResponse,
    KeywordSearchResult,
    AnchorResponse,
)
from app.services.qdrant import QdrantService


@router.post("/search/keyword", response_model=KeywordSearchResponse)
async def keyword_search(
    body: KeywordSearchRequest,
    request: Request,
    qdrant_service: Annotated[QdrantService, Depends(get_qdrant_service)],
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
) -> KeywordSearchResponse:
    snapshot_id = body.snapshot_id
    if snapshot_id is None:
        active_snapshot = await snapshot_service.get_active_snapshot(
            agent_id=body.agent_id,
            knowledge_base_id=body.knowledge_base_id,
        )
        if active_snapshot is None:
            raise HTTPException(
                status_code=422,
                detail="No active snapshot found. Publish and activate a snapshot first.",
            )
        snapshot_id = active_snapshot.id

    results = await qdrant_service.keyword_search(
        text=body.query,
        snapshot_id=snapshot_id,
        agent_id=body.agent_id,
        knowledge_base_id=body.knowledge_base_id,
        limit=body.limit,
    )

    bm25_language = request.app.state.settings.bm25_language

    return KeywordSearchResponse(
        results=[
            KeywordSearchResult(
                chunk_id=r.chunk_id,
                source_id=r.source_id,
                text_content=r.text_content,
                score=r.score,
                anchor=AnchorResponse(
                    page=r.anchor_metadata.get("anchor_page"),
                    chapter=r.anchor_metadata.get("anchor_chapter"),
                    section=r.anchor_metadata.get("anchor_section"),
                    timecode=r.anchor_metadata.get("anchor_timecode"),
                ),
            )
            for r in results
        ],
        query=body.query,
        language=bm25_language,
        total=len(results),
    )
```

Note: `SnapshotService.get_active_snapshot(agent_id=..., knowledge_base_id=...)` returns `KnowledgeSnapshot | None`. The endpoint extracts `.id` from the result. The method exists at `backend/app/services/snapshot.py:79`.

- [ ] **Step 6: Add qdrant_service to admin_app fixture**

The `admin_app` fixture in `backend/tests/conftest.py` needs `app.state.qdrant_service` and `app.state.settings.bm25_language`. Either update the fixture or use the local `_make_app` from the test file.

- [ ] **Step 7: Run tests**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/test_admin_keyword_search.py -v
```

Expected: all PASS.

- [ ] **Step 8: Run full unit test suite**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/unit/ -v```

Expected: all PASS.

- [ ] **Step 9: Propose commit**

Proposed message: `feat(admin): add POST /api/admin/search/keyword endpoint for BM25 search`
Files: `backend/app/api/admin.py`, `backend/app/api/dependencies.py`, `backend/app/api/schemas.py`, `backend/tests/unit/test_admin_keyword_search.py`

---

### Task 7: Integration tests with real Qdrant

**Files:**
- Modify: `backend/tests/integration/test_qdrant_roundtrip.py`

- [ ] **Step 1: Write integration tests**

Add to `backend/tests/integration/test_qdrant_roundtrip.py`:

```python
@pytest.mark.asyncio
async def test_keyword_search_finds_chunks_by_text(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_bm25_{uuid.uuid4().hex}"
    service = QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=3,
        bm25_language="english",
    )
    snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    knowledge_base_id = uuid.uuid4()
    target_chunk_id = uuid.uuid4()
    target_source_id = uuid.uuid4()

    try:
        await service.ensure_collection()
        await service.upsert_chunks(
            [
                _point(
                    chunk_id=target_chunk_id,
                    snapshot_id=snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[1.0, 0.0, 0.0],
                    text_content="The quick brown fox runs over the lazy dog",
                    source_id=target_source_id,
                ),
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    vector=[0.0, 1.0, 0.0],
                    text_content="Quantum physics explains particle behavior",
                ),
            ]
        )

        results = await service.keyword_search(
            text="fox running",
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
            limit=5,
        )

        assert len(results) >= 1
        assert results[0].chunk_id == target_chunk_id
        assert results[0].source_id == target_source_id
    finally:
        await client.delete_collection(collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_keyword_search_scoped_by_snapshot_id(qdrant_url: str) -> None:
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_bm25_scope_{uuid.uuid4().hex}"
    service = QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=3,
        bm25_language="english",
    )
    snapshot_a = uuid.uuid4()
    snapshot_b = uuid.uuid4()
    agent_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    try:
        await service.ensure_collection()
        await service.upsert_chunks(
            [
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=snapshot_a,
                    agent_id=agent_id,
                    knowledge_base_id=kb_id,
                    vector=[1.0, 0.0, 0.0],
                    text_content="visible keyword content",
                ),
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=snapshot_b,
                    agent_id=agent_id,
                    knowledge_base_id=kb_id,
                    vector=[0.0, 1.0, 0.0],
                    text_content="hidden keyword content",
                ),
            ]
        )

        results = await service.keyword_search(
            text="keyword content",
            snapshot_id=snapshot_a,
            agent_id=agent_id,
            knowledge_base_id=kb_id,
            limit=10,
        )

        assert len(results) == 1
        assert results[0].text_content == "visible keyword content"
    finally:
        await client.delete_collection(collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_bm25_stemming_matches_inflected_forms(qdrant_url: str) -> None:
    """Verifies Snowball stemmer: 'running' matches 'runs'."""
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_bm25_stem_{uuid.uuid4().hex}"
    service = QdrantService(
        client=client,
        collection_name=collection_name,
        embedding_dimensions=3,
        bm25_language="english",
    )
    snapshot_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    kb_id = uuid.uuid4()

    try:
        await service.ensure_collection()
        await service.upsert_chunks(
            [
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=kb_id,
                    vector=[1.0, 0.0, 0.0],
                    text_content="The athlete runs every morning",
                ),
            ]
        )

        results = await service.keyword_search(
            text="running",
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=kb_id,
            limit=5,
        )

        assert len(results) == 1
    finally:
        await client.delete_collection(collection_name)
        await client.close()


@pytest.mark.asyncio
async def test_ensure_collection_recreates_on_missing_sparse_vector(qdrant_url: str) -> None:
    """Collection without BM25 sparse vector gets recreated."""
    client = AsyncQdrantClient(url=qdrant_url)
    collection_name = f"test_bm25_recreate_{uuid.uuid4().hex}"

    try:
        # Create a dense-only collection manually
        await client.create_collection(
            collection_name=collection_name,
            vectors_config={
                "dense": models.VectorParams(size=3, distance=models.Distance.COSINE)
            },
        )

        # Now ensure_collection should recreate it with both vectors
        service = QdrantService(
            client=client,
            collection_name=collection_name,
            embedding_dimensions=3,
            bm25_language="english",
        )
        await service.ensure_collection()

        # Verify BM25 works by upserting and searching
        snapshot_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        kb_id = uuid.uuid4()
        await service.upsert_chunks(
            [
                _point(
                    chunk_id=uuid.uuid4(),
                    snapshot_id=snapshot_id,
                    agent_id=agent_id,
                    knowledge_base_id=kb_id,
                    vector=[1.0, 0.0, 0.0],
                    text_content="recreation test content",
                ),
            ]
        )

        results = await service.keyword_search(
            text="recreation",
            snapshot_id=snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=kb_id,
        )
        assert len(results) == 1
    finally:
        await client.delete_collection(collection_name)
        await client.close()
```

**Update all existing integration tests:**

1. Add `bm25_language="english"` to every `QdrantService(...)` constructor call in this file.
2. **`test_qdrant_dimension_mismatch_raises`** — unchanged behavior (still raises). Just add `bm25_language="english"` to both QdrantService constructors.

- [ ] **Step 2: Run integration tests**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/integration/test_qdrant_roundtrip.py -v```

Expected: all PASS.

- [ ] **Step 3: Propose commit**

Proposed message: `test(integration): add BM25 keyword search, stemming, and recreation roundtrip tests`
Files: `backend/tests/integration/test_qdrant_roundtrip.py`

---

### Task 8: Final verification

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run pytest tests/ -v```

Expected: all PASS.

- [ ] **Step 2: Run linter**

```bash
cd /Users/techmeat/www/projects/agentic-depot/proxymind/backend && uv run ruff check app/ tests/
```

Expected: no errors.

- [ ] **Step 3: Verify story criteria manually (if services are running)**

```bash
# 1. Upload a source
curl -X POST http://localhost:8000/api/admin/sources \
  -F "file=@test.md" \
  -F 'metadata={"title":"Test","description":"BM25 test"}'

# 2. Wait for ingestion, then publish + activate snapshot

# 3. Test keyword search
curl -X POST http://localhost:8000/api/admin/search/keyword \
  -H "Content-Type: application/json" \
  -d '{"query": "your keyword here"}'

# Expected: results array with matching chunks, language field = BM25_LANGUAGE from .env
```

- [ ] **Step 4: Commit any remaining fixes**

Only if Steps 1-2 revealed issues.
