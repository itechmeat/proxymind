# S9-03 BGE-M3 Sparse Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace BM25 sparse retrieval with an installation-level BGE-M3 sparse fallback for languages where evals prove BM25 is insufficient, while keeping Gemini dense retrieval unchanged.

**Architecture:** Introduce a narrow sparse-provider abstraction with one active sparse backend per installation (`bm25` or `bge_m3`). Keep the existing hybrid retrieval contract, indexing flow, and RRF fusion intact; only the sparse leg changes. Treat sparse backend changes as an index contract change that requires explicit reindexing, explicit Qdrant schema handling, and auditable metadata.

**Tech Stack:** Python 3.14+, FastAPI, Qdrant 1.17+, SQLAlchemy 2.x, Alembic, httpx, tenacity, pytest, Gemini Embedding 2, existing eval framework

---

## File Structure

### Create

- `backend/app/services/sparse_providers.py` — sparse-provider protocol, BM25 adapter, external BGE-M3 adapter, sparse vector payload model, provider metadata model
- `backend/tests/unit/services/test_sparse_providers.py` — provider selection, request shaping, failure handling, metadata tests
- `backend/tests/unit/services/test_reindex_requirements.py` — explicit reindex requirement logic and metadata tests
- `backend/tests/integration/test_sparse_backend_contract.py` — retrieval/admin diagnostic regression coverage for active sparse backend wiring
- `backend/evals/datasets/retrieval_bge_m3_russian.yaml` — language-specific retrieval eval suite using the current eval dataset format

### Modify

- `backend/app/core/config.py` — add installation-level sparse backend settings and validation
- `backend/app/services/qdrant.py` — route sparse document/query construction through the active sparse provider and make collection schema lifecycle provider-aware
- `backend/app/services/retrieval.py` — keep search contract stable while delegating sparse behavior to Qdrant service
- `backend/app/workers/tasks/pipeline.py` — keep sparse text selection explicit and propagate provider metadata into indexable payload metadata if needed
- `backend/app/main.py` — construct active sparse provider and inject it into services
- `backend/app/workers/main.py` — construct active sparse provider and inject it into worker services
- `backend/app/api/admin.py` — expose sparse backend diagnostics where useful
- `backend/app/api/schemas.py` — extend keyword-search response model for sparse backend diagnostics
- `backend/tests/unit/services/test_qdrant.py` — replace BM25-only assumptions with provider-aware sparse contract and schema lifecycle tests
- `backend/tests/unit/test_retrieval_service.py` — preserve dense + sparse + hybrid contract while removing BM25-specific assumptions
- `backend/tests/unit/test_config.py` — config parsing and validation for `SPARSE_BACKEND` and provider settings
- `backend/tests/unit/workers/test_path_b_handler.py` — ensure indexing still uses `enriched_text` when available and keeps provider-independent behavior
- `backend/tests/unit/test_app_main.py` — startup wiring coverage for sparse provider injection
- `backend/tests/unit/workers/test_main.py` — worker startup wiring coverage for sparse provider injection
- `backend/tests/integration/test_qdrant_roundtrip.py` — add active sparse backend contract coverage and schema lifecycle regression tests
- `docs/rag.md` — update the operational fallback wording with explicit switch/reindex rules
- `docs/spec.md` — only if implementation introduces a new required runtime setting or explicit operational contract text
- `docs/superpowers/specs/2026-03-29-s9-03-bge-m3-fallback-design.md` — only if implementation planning uncovers a required clarification

---

## Prerequisite container setup

All backend verification in this plan MUST run inside Docker containers.

- [ ] **Step 0.1: Ensure backend containers are available before any backend command**

Run: `docker compose up -d backend postgres redis qdrant`
Expected: containers are running and `docker compose ps` shows backend dependencies healthy or started.

- [ ] **Step 0.2: Use container-only command prefix for all backend checks**

```bash
docker compose exec backend uv run pytest ...
docker compose exec backend uv run python -m evals.run_evals ...
```

Expected: no host-side backend `uv run` commands are used anywhere in execution.

### Task 1: Add sparse backend configuration and provider abstraction

**Files:**

- Create: `backend/app/services/sparse_providers.py`
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/unit/services/test_sparse_providers.py`
- Test: `backend/tests/unit/test_config.py`

- [ ] **Step 1: Write failing config tests for sparse backend selection**

```python
# backend/tests/unit/test_config.py
from pydantic import ValidationError


def test_sparse_backend_defaults_to_bm25() -> None:
    settings = Settings(**_base_settings())
    assert settings.sparse_backend == "bm25"


def test_sparse_backend_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        Settings(**_base_settings(), sparse_backend="bogus")


def test_bge_m3_requires_provider_url() -> None:
    with pytest.raises(ValueError, match="BGE_M3_PROVIDER_URL"):
        Settings(**_base_settings(), sparse_backend="bge_m3")
```

- [ ] **Step 2: Run config tests to verify they fail**

Run: `docker compose exec backend uv run pytest tests/unit/test_config.py -v -k "sparse_backend or bge_m3"`
Expected: FAIL with missing `sparse_backend` settings or validation.

- [ ] **Step 3: Write failing provider tests for BM25 and external BGE-M3 adapters**

```python
# backend/tests/unit/services/test_sparse_providers.py
import httpx
import pytest
from qdrant_client import models


@pytest.mark.asyncio
async def test_bm25_provider_builds_qdrant_document() -> None:
    provider = Bm25SparseProvider(language="english")
    result = await provider.build_document_representation("hello world")
    assert isinstance(result, models.Document)
    assert result.model == "Qdrant/bm25"


@pytest.mark.asyncio
async def test_bge_m3_provider_posts_texts_to_external_endpoint() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"indices": [1], "values": [0.5]},
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://sparse") as client:
        provider = ExternalBgeM3SparseProvider(base_url="http://sparse", client=client)
        result = await provider.build_query_representation("hello")
    assert result.indices == [1]
    assert result.values == [0.5]
```

- [ ] **Step 4: Run provider tests to verify they fail**

Run: `docker compose exec backend uv run pytest tests/unit/services/test_sparse_providers.py -v`
Expected: FAIL with missing provider classes or missing sparse payload model.

- [ ] **Step 5: Implement minimal sparse provider module**

```python
# backend/app/services/sparse_providers.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx
from qdrant_client import models


@dataclass(frozen=True, slots=True)
class SparseProviderMetadata:
    backend: str
    model_name: str
    contract_version: str


@dataclass(frozen=True, slots=True)
class SparseVectorPayload:
    indices: list[int]
    values: list[float]


class SparseProvider(Protocol):
    metadata: SparseProviderMetadata

    async def build_document_representation(self, text: str) -> models.Document | SparseVectorPayload: ...
    async def build_query_representation(self, text: str) -> models.Document | SparseVectorPayload: ...


class Bm25SparseProvider:
    def __init__(self, *, language: str) -> None:
        self.metadata = SparseProviderMetadata(
            backend="bm25",
            model_name="Qdrant/bm25",
            contract_version="v1",
        )
        self._language = language

    async def build_document_representation(self, text: str) -> models.Document:
        return models.Document(
            text=text,
            model="Qdrant/bm25",
            options=models.Bm25Config(language=self._language),
        )

    async def build_query_representation(self, text: str) -> models.Document:
        return await self.build_document_representation(text)


class ExternalBgeM3SparseProvider:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.metadata = SparseProviderMetadata(
            backend="bge_m3",
            model_name="bge-m3",
            contract_version="v1",
        )
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
        )

    async def build_document_representation(self, text: str) -> SparseVectorPayload:
        response = await self._client.post("/sparse/documents", json={"text": text})
        response.raise_for_status()
        data = response.json()
        return SparseVectorPayload(indices=data["indices"], values=data["values"])

    async def build_query_representation(self, text: str) -> SparseVectorPayload:
        response = await self._client.post("/sparse/queries", json={"text": text})
        response.raise_for_status()
        data = response.json()
        return SparseVectorPayload(indices=data["indices"], values=data["values"])


def sparse_backend_change_requires_reindex(
    current: SparseProviderMetadata,
    target: SparseProviderMetadata,
) -> bool:
    return (
        current.backend != target.backend
        or current.model_name != target.model_name
        or current.contract_version != target.contract_version
    )
```

- [ ] **Step 6: Add config fields and validation**

```python
# backend/app/core/config.py
from typing import Literal

class Settings(BaseSettings):
    sparse_backend: Literal["bm25", "bge_m3"] = Field(default="bm25")
    bge_m3_provider_url: str | None = Field(default=None)
    bge_m3_timeout_seconds: float = Field(default=10.0, ge=0.1, le=60.0)

    @model_validator(mode="before")
    @classmethod
    def normalize_empty_optional_strings(cls, data: Any) -> Any:
        ...
        for field_name in (
            ...,
            "bge_m3_provider_url",
        ):
            ...

    @model_validator(mode="after")
    def validate_retrieval_settings(self) -> Settings:
        ...
        if self.sparse_backend == "bge_m3" and self.bge_m3_provider_url is None:
            raise ValueError("BGE_M3_PROVIDER_URL is required when SPARSE_BACKEND=bge_m3")
        return self
```

- [ ] **Step 7: Re-run unit tests**

Run: `docker compose exec backend uv run pytest tests/unit/test_config.py tests/unit/services/test_sparse_providers.py -v`
Expected: PASS.

### Task 2: Make Qdrant schema lifecycle explicitly sparse-provider-aware

**Files:**

- Modify: `backend/app/services/qdrant.py`
- Test: `backend/tests/unit/services/test_qdrant.py`
- Test: `backend/tests/integration/test_qdrant_roundtrip.py`

- [ ] **Step 1: Write failing unit tests for provider-aware collection lifecycle**

```python
# backend/tests/unit/services/test_qdrant.py
@pytest.mark.asyncio
async def test_ensure_collection_logs_active_sparse_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    sparse_provider = SimpleNamespace(
        metadata=SimpleNamespace(backend="bge_m3", model_name="bge-m3", contract_version="v1")
    )
    service, logger = _service(monkeypatch, client=client, sparse_provider=sparse_provider)
    await service.ensure_collection()
    logger.info.assert_any_call(
        "qdrant.ensure_collection",
        collection_name="proxymind_chunks",
        bm25_language="english",
        sparse_backend="bge_m3",
        sparse_model="bge-m3",
        sparse_contract_version="v1",
    )


@pytest.mark.asyncio
async def test_ensure_collection_rejects_sparse_backend_metadata_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    # existing collection metadata says bm25, active provider says bge_m3
    ...
    with pytest.raises(CollectionSchemaMismatchError, match="sparse backend"):
        await service.ensure_collection()
```

- [ ] **Step 2: Write failing unit tests for provider-aware sparse construction**

```python
# backend/tests/unit/services/test_qdrant.py
@pytest.mark.asyncio
async def test_upsert_chunks_uses_sparse_provider_document_representation(monkeypatch: pytest.MonkeyPatch) -> None:
    sparse_provider = SimpleNamespace(
        metadata=SimpleNamespace(backend="bge_m3", model_name="bge-m3", contract_version="v1"),
        build_document_representation=AsyncMock(
            return_value=SparseVectorPayload(indices=[1], values=[0.5])
        ),
    )
    service, _logger = _service(monkeypatch, client=client, sparse_provider=sparse_provider)
    await service.upsert_chunks([point])
    sparse_provider.build_document_representation.assert_awaited_once_with("chunk body")


@pytest.mark.asyncio
async def test_hybrid_search_uses_sparse_provider_query_representation(monkeypatch: pytest.MonkeyPatch) -> None:
    sparse_provider = SimpleNamespace(
        metadata=SimpleNamespace(backend="bge_m3", model_name="bge-m3", contract_version="v1"),
        build_query_representation=AsyncMock(
            return_value=SparseVectorPayload(indices=[2], values=[0.7])
        ),
    )
    service, _logger = _service(monkeypatch, client=client, sparse_provider=sparse_provider)
    await service.hybrid_search(
        text="deployment",
        vector=[0.1, 0.2, 0.3],
        snapshot_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        knowledge_base_id=uuid.uuid4(),
        limit=5,
    )
    sparse_provider.build_query_representation.assert_awaited_once_with("deployment")
```

- [ ] **Step 3: Run targeted Qdrant tests to verify they fail**

Run: `docker compose exec backend uv run pytest tests/unit/services/test_qdrant.py -v -k "sparse_backend or sparse_provider or metadata_mismatch"`
Expected: FAIL because `QdrantService` is still BM25-specific in schema lifecycle and sparse construction.

- [ ] **Step 4: Refactor `QdrantService` constructor to accept the sparse provider**

```python
# backend/app/services/qdrant.py
class QdrantService:
    def __init__(
        self,
        *,
        client: AsyncQdrantClient,
        collection_name: str,
        embedding_dimensions: int,
        sparse_provider: SparseProvider,
        bm25_language: str,
    ) -> None:
        self._client = client
        self._collection_name = collection_name
        self._embedding_dimensions = embedding_dimensions
        self._sparse_provider = sparse_provider
        self._bm25_language = bm25_language
```

- [ ] **Step 5: Make sparse schema metadata explicit in payload/index contract**

```python
# backend/app/services/qdrant.py
SPARSE_BACKEND_PAYLOAD_KEY = "sparse_backend"
SPARSE_MODEL_PAYLOAD_KEY = "sparse_model"
SPARSE_CONTRACT_VERSION_PAYLOAD_KEY = "sparse_contract_version"
```

```python
# backend/app/services/qdrant.py
self._logger.info(
    "qdrant.ensure_collection",
    collection_name=self._collection_name,
    bm25_language=self._bm25_language,
    sparse_backend=self._sparse_provider.metadata.backend,
    sparse_model=self._sparse_provider.metadata.model_name,
    sparse_contract_version=self._sparse_provider.metadata.contract_version,
)
```

- [ ] **Step 6: Add explicit collection metadata validation for active sparse backend**

```python
# backend/app/services/qdrant.py
async def ensure_collection(self) -> None:
    ...
    if collection_info is not None:
        existing_dimensions = self._get_dense_vector_size(collection_info)
        if existing_dimensions != self._embedding_dimensions:
            raise CollectionSchemaMismatchError(...)
        self._assert_sparse_backend_contract(collection_info)
        if self._sparse_provider.metadata.backend == "bm25":
            if not self._has_required_bm25_sparse_vector(collection_info):
                await self._recreate_collection_with_bm25()
```

```python
# backend/app/services/qdrant.py
def _assert_sparse_backend_contract(self, collection_info: Any) -> None:
    payload_schema = getattr(collection_info, "payload_schema", None) or {}
    # If collection metadata cannot prove compatibility, fail loudly and require operator action.
    # For v1, provider switch is treated as incompatible state.
```

- [ ] **Step 7: Replace BM25-only helper calls with provider-aware sparse methods**

```python
# backend/app/services/qdrant.py
async def upsert_chunks(self, chunks: list[QdrantChunkPoint]) -> None:
    points = []
    for chunk in chunks:
        sparse_value = await self._sparse_provider.build_document_representation(chunk.bm25_text)
        vector_payload = {
            DENSE_VECTOR_NAME: chunk.vector,
            BM25_VECTOR_NAME: self._to_qdrant_sparse_vector(sparse_value),
        }
        payload = self._build_payload(chunk)
        payload[SPARSE_BACKEND_PAYLOAD_KEY] = self._sparse_provider.metadata.backend
        payload[SPARSE_MODEL_PAYLOAD_KEY] = self._sparse_provider.metadata.model_name
        payload[SPARSE_CONTRACT_VERSION_PAYLOAD_KEY] = self._sparse_provider.metadata.contract_version
        points.append(models.PointStruct(id=str(chunk.chunk_id), vector=vector_payload, payload=payload))
    await self._upsert_points(points)
```

```python
# backend/app/services/qdrant.py
async def hybrid_search(...):
    sparse_query = await self._sparse_provider.build_query_representation(text)
    ...
```

- [ ] **Step 8: Add integration coverage for contract stability and lifecycle mismatch**

```python
# backend/tests/integration/test_qdrant_roundtrip.py
@pytest.mark.asyncio
async def test_hybrid_search_contract_stays_stable_with_active_sparse_backend(qdrant_url: str) -> None:
    service = QdrantService(
        client=AsyncQdrantClient(url=qdrant_url),
        collection_name=f"test_sparse_{uuid.uuid4().hex}",
        embedding_dimensions=3,
        sparse_provider=Bm25SparseProvider(language="english"),
        bm25_language="english",
    )
    await service.ensure_collection()
    ...
    results = await service.hybrid_search(...)
    assert results[0].text_content == "matched chunk"


@pytest.mark.asyncio
async def test_sparse_backend_switch_requires_new_index_contract(qdrant_url: str) -> None:
    # create under bm25, reopen under bge_m3 provider, assert explicit mismatch/failure
    ...
```

- [ ] **Step 9: Re-run Qdrant unit and integration tests**

Run: `docker compose exec backend uv run pytest tests/unit/services/test_qdrant.py tests/integration/test_qdrant_roundtrip.py -v`
Expected: PASS.

### Task 3: Wire the active sparse backend into worker and API startup

**Files:**

- Modify: `backend/app/main.py`
- Modify: `backend/app/workers/main.py`
- Modify: `backend/tests/unit/test_app_main.py`
- Modify: `backend/tests/unit/workers/test_main.py`

- [ ] **Step 1: Write failing startup wiring tests**

```python
# backend/tests/unit/test_app_main.py

def test_create_qdrant_service_passes_sparse_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    created = {}

    class FakeProvider:
        metadata = SimpleNamespace(backend="bm25", model_name="Qdrant/bm25", contract_version="v1")

    monkeypatch.setattr("app.main.build_sparse_provider", lambda settings: FakeProvider())
    monkeypatch.setattr("app.main.QdrantService", lambda **kwargs: created.update(kwargs) or object())

    create_qdrant_service(settings)
    assert created["sparse_provider"].metadata.backend == "bm25"
```

- [ ] **Step 2: Run startup wiring tests to verify they fail**

Run: `docker compose exec backend uv run pytest tests/unit/test_app_main.py tests/unit/workers/test_main.py -v -k "sparse_provider"`
Expected: FAIL because startup still only passes `bm25_language`.

- [ ] **Step 3: Add a provider factory and use it in API startup**

```python
# backend/app/main.py
from app.services.sparse_providers import Bm25SparseProvider, ExternalBgeM3SparseProvider


def build_sparse_provider(settings: Settings):
    if settings.sparse_backend == "bm25":
        return Bm25SparseProvider(language=settings.bm25_language)
    return ExternalBgeM3SparseProvider(
        base_url=settings.bge_m3_provider_url,
        timeout_seconds=settings.bge_m3_timeout_seconds,
    )
```

- [ ] **Step 4: Pass the provider into `QdrantService` in both API and worker startup**

```python
# backend/app/main.py / backend/app/workers/main.py
sparse_provider = build_sparse_provider(settings)
qdrant_service = QdrantService(
    client=client,
    collection_name=settings.qdrant_collection,
    embedding_dimensions=settings.embedding_dimensions,
    sparse_provider=sparse_provider,
    bm25_language=settings.bm25_language,
)
```

- [ ] **Step 5: Re-run startup tests**

Run: `docker compose exec backend uv run pytest tests/unit/test_app_main.py tests/unit/workers/test_main.py -v`
Expected: PASS.

### Task 4: Preserve ingestion and retrieval contract while making sparse backend explicit

**Files:**

- Modify: `backend/app/workers/tasks/pipeline.py`
- Modify: `backend/app/services/retrieval.py`
- Modify: `backend/tests/unit/workers/test_path_b_handler.py`
- Modify: `backend/tests/unit/test_retrieval_service.py`
- Create: `backend/tests/unit/services/test_reindex_requirements.py`

- [ ] **Step 1: Write failing retrieval-service regression tests**

```python
# backend/tests/unit/test_retrieval_service.py
@pytest.mark.asyncio
async def test_search_keeps_dense_query_embedding_and_provider_backed_sparse_search() -> None:
    embedding_service = AsyncMock()
    embedding_service.embed_texts.return_value = [[0.1, 0.2, 0.3]]
    qdrant_service = AsyncMock()
    service = RetrievalService(
        embedding_service=embedding_service,
        qdrant_service=qdrant_service,
        top_n=5,
        min_dense_similarity=0.4,
    )
    await service.search("Where is the answer?", snapshot_id=uuid.uuid4())
    embedding_service.embed_texts.assert_awaited_once_with(
        ["Where is the answer?"],
        task_type="RETRIEVAL_QUERY",
    )
    qdrant_service.hybrid_search.assert_awaited_once()
```

- [ ] **Step 2: Write failing pipeline tests for sparse text selection**

```python
# backend/tests/unit/workers/test_path_b_handler.py
async def test_handle_path_b_preserves_enriched_text_for_active_sparse_backend(...) -> None:
    ...
    assert qdrant_points[0].bm25_text == enriched_text
    assert qdrant_service.upsert_chunks.await_args.args[0][0].enriched_text == enriched_text
```

- [ ] **Step 3: Write failing reindex helper tests**

```python
# backend/tests/unit/services/test_reindex_requirements.py

def test_sparse_backend_change_requires_reindex() -> None:
    current = SparseProviderMetadata(backend="bm25", model_name="Qdrant/bm25", contract_version="v1")
    target = SparseProviderMetadata(backend="bge_m3", model_name="bge-m3", contract_version="v1")
    assert sparse_backend_change_requires_reindex(current, target) is True


def test_same_sparse_backend_contract_does_not_require_reindex() -> None:
    current = SparseProviderMetadata(backend="bm25", model_name="Qdrant/bm25", contract_version="v1")
    target = SparseProviderMetadata(backend="bm25", model_name="Qdrant/bm25", contract_version="v1")
    assert sparse_backend_change_requires_reindex(current, target) is False
```

- [ ] **Step 4: Run targeted tests to verify failures**

Run: `docker compose exec backend uv run pytest tests/unit/test_retrieval_service.py tests/unit/workers/test_path_b_handler.py tests/unit/services/test_reindex_requirements.py -v`
Expected: FAIL until helper coverage and provider-aware assumptions are in place.

- [ ] **Step 5: Keep retrieval service stable and avoid provider branching there**

```python
# backend/app/services/retrieval.py
async def search(self, query: str, *, snapshot_id: uuid.UUID, top_n: int | None = None) -> list[RetrievedChunk]:
    embeddings = await self._embedding_service.embed_texts(
        [query],
        task_type="RETRIEVAL_QUERY",
    )
    if not embeddings:
        return []
    return await self._qdrant_service.hybrid_search(
        text=query,
        vector=embeddings[0],
        snapshot_id=snapshot_id,
        agent_id=self._agent_id,
        knowledge_base_id=self._knowledge_base_id,
        limit=self._top_n if top_n is None else top_n,
        score_threshold=self._min_dense_similarity,
    )
```

- [ ] **Step 6: Keep ingestion sparse text selection explicit and unchanged**

```python
# backend/app/workers/tasks/pipeline.py
texts_for_embedding = [chunk.text_content for chunk in chunk_data]
...
if enrichment_result is not None:
    enriched_text = build_enriched_text(...)
    texts_for_embedding[index] = enriched_text
    chunk_row.enriched_text = enriched_text
...
# qdrant_points still pass row.enriched_text / row.text_content via QdrantChunkPoint.bm25_text
```

- [ ] **Step 7: Re-run unit tests**

Run: `docker compose exec backend uv run pytest tests/unit/test_retrieval_service.py tests/unit/workers/test_path_b_handler.py tests/unit/services/test_reindex_requirements.py -v`
Expected: PASS.

### Task 5: Add admin diagnostics and correct API schema wiring

**Files:**

- Modify: `backend/app/api/admin.py`
- Modify: `backend/app/api/schemas.py`
- Create: `backend/tests/integration/test_sparse_backend_contract.py`

- [ ] **Step 1: Write failing admin diagnostic test for sparse backend visibility**

```python
# backend/tests/integration/test_sparse_backend_contract.py
@pytest.mark.asyncio
async def test_admin_keyword_diagnostics_expose_active_sparse_backend(admin_app) -> None:
    response = await client.post("/api/admin/search/keyword", json={"query": "term"})
    assert response.status_code == 200
    assert response.json()["sparse_backend"] in {"bm25", "bge_m3"}
    assert "sparse_model" in response.json()
```

- [ ] **Step 2: Run the targeted diagnostic test to verify it fails**

Run: `docker compose exec backend uv run pytest tests/integration/test_sparse_backend_contract.py -v`
Expected: FAIL because response schema and payload do not yet include sparse backend diagnostics.

- [ ] **Step 3: Extend the API schema first**

```python
# backend/app/api/schemas.py
class KeywordSearchResponse(BaseModel):
    query: str
    language: str
    sparse_backend: str
    sparse_model: str
    total: int
    results: list[KeywordSearchResult]
```

- [ ] **Step 4: Return sparse backend diagnostics from the endpoint**

```python
# backend/app/api/admin.py
return KeywordSearchResponse(
    query=payload.query,
    language=qdrant_service.bm25_language,
    sparse_backend=qdrant_service.sparse_backend,
    sparse_model=qdrant_service.sparse_model,
    total=len(results),
    results=[KeywordSearchResult.from_retrieved_chunk(chunk) for chunk in results],
)
```

- [ ] **Step 5: Re-run diagnostic tests**

Run: `docker compose exec backend uv run pytest tests/integration/test_sparse_backend_contract.py -v`
Expected: PASS.

### Task 6: Separate eval dataset work from sparse-backend comparison orchestration

**Files:**

- Create: `backend/evals/datasets/retrieval_bge_m3_russian.yaml`
- Modify: `docs/rag.md`
- Modify: `docs/spec.md` (only if runtime settings or contract wording changed)

- [ ] **Step 1: Write the dataset in the current eval-suite format**

```yaml
# backend/evals/datasets/retrieval_bge_m3_russian.yaml
suite: retrieval_bge_m3_russian
description: Retrieval comparison suite for BM25 vs BGE-M3 on Russian queries
snapshot_id: 00000000-0000-0000-0000-000000000000
cases:
  - id: ru-ret-001
        query: "How do I configure snapshot publishing?"
    expected:
      - source_id: 00000000-0000-0000-0000-000000000011
        contains: "publish"
    tags: [retrieval, russian, sparse-comparison]
```

- [ ] **Step 2: Verify the dataset loads with the current eval loader**

Run: `docker compose exec backend uv run python -m evals.run_evals --dataset evals/datasets/retrieval_bge_m3_russian.yaml --snapshot-id 00000000-0000-0000-0000-000000000000`
Expected: dataset loads successfully; execution may still fail later if the target API or snapshot is unavailable, but it must not fail on schema parsing.

- [ ] **Step 3: Document the actual comparison workflow as two runs, not one magical combined run**

```text
Comparison workflow for S9-03:
1. Run eval suite with SPARSE_BACKEND=bm25 against the target snapshot and save the report.
2. Reindex the same snapshot/content under SPARSE_BACKEND=bge_m3.
3. Run the same eval suite again with SPARSE_BACKEND=bge_m3.
4. Compare the two reports manually or via a follow-up comparison helper if one is added later.
```

- [ ] **Step 4: Update docs with the explicit switch/reindex and comparison rule**

```md
# docs/rag.md

**Fallback: BGE-M3** — enabled per installation when evals show BM25 is insufficient for the configured language. Switching `sparse_backend` requires explicit reindexing because sparse index artifacts are backend-specific. Quality comparison is performed as two separate eval runs against equivalent content: one run with `bm25`, one run with `bge_m3`.
```

- [ ] **Step 5: Re-run dataset-load verification after docs/plan alignment**

Run: `docker compose exec backend uv run python -m evals.run_evals --dataset evals/datasets/retrieval_bge_m3_russian.yaml --snapshot-id 00000000-0000-0000-0000-000000000000`
Expected: dataset still loads under the current runner entry point `python -m evals.run_evals`.

### Task 7: Final verification and implementation review

**Files:**

- Review: `docs/development.md`
- Verify: relevant backend code and tests
- Modify: this plan file only to mark completed checkboxes during execution

- [ ] **Step 1: Re-read `docs/development.md` before final verification**

```text
Review the project standards again and explicitly confirm the implementation still respects:
- cheap-VPS-first / no local heavyweight ML runtime
- KISS / YAGNI
- no fake fallbacks in production code
- deterministic deploy tests plus separate eval verification
- container-only backend workflow
```

- [ ] **Step 2: Run targeted backend unit tests in container**

Run: `docker compose exec backend uv run pytest tests/unit/test_config.py tests/unit/services/test_sparse_providers.py tests/unit/services/test_qdrant.py tests/unit/test_retrieval_service.py tests/unit/workers/test_path_b_handler.py tests/unit/test_app_main.py tests/unit/workers/test_main.py tests/unit/services/test_reindex_requirements.py -v`
Expected: PASS.

- [ ] **Step 3: Run integration tests in container**

Run: `docker compose exec backend uv run pytest tests/integration/test_qdrant_roundtrip.py tests/integration/test_sparse_backend_contract.py -v`
Expected: PASS.

- [ ] **Step 4: Run the BM25 baseline eval pass**

Run: `docker compose exec backend sh -lc 'SPARSE_BACKEND=bm25 uv run python -m evals.run_evals --dataset evals/datasets/retrieval_bge_m3_russian.yaml --snapshot-id <snapshot-uuid>'`
Expected: report generated for BM25 baseline.

- [ ] **Step 5: Reindex under BGE-M3 and run the second eval pass**

```text
Perform explicit reindex under SPARSE_BACKEND=bge_m3 first. Then run:
```

Run: `docker compose exec backend sh -lc 'SPARSE_BACKEND=bge_m3 uv run python -m evals.run_evals --dataset evals/datasets/retrieval_bge_m3_russian.yaml --snapshot-id <snapshot-uuid>'`
Expected: report generated for BGE-M3 run against the reindexed snapshot/content.

- [ ] **Step 6: Compare the two reports explicitly**

```text
Check Precision@K, Recall@K, and MRR between the BM25 report and the BGE-M3 report. Do not claim automatic comparison tooling exists unless it was added in the same change.
```

- [ ] **Step 7: Capture implementation review notes**

```text
Record in the final implementation report:
- pre-code read of docs/development.md completed
- post-code self-review against docs/development.md completed
- sparse backend switch requires explicit reindexing
- Gemini dense remained unchanged
- comparison used two separate eval runs
- all backend verification was executed in containers
```

---

## Spec Coverage Check

- Installation-level sparse backend switch — covered in Task 1
- Sparse-provider abstraction — covered in Task 1
- Provider-aware Qdrant indexing/querying — covered in Task 2
- Explicit Qdrant schema lifecycle and sparse contract handling — covered in Task 2
- Stable hybrid retrieval contract — covered in Tasks 2 and 4
- Explicit reindex requirement — covered in Tasks 1, 2, 4, and 6
- Admin diagnostics and schema correctness — covered in Task 5
- Executable eval dataset format — covered in Task 6
- Actual comparison workflow between BM25 and BGE-M3 — covered in Tasks 6 and 7

## Placeholder Scan

Pseudo-code remains only where the exact implementation depends on local helper names in the touched file and is marked by surrounding explanatory text. Concrete commands, files, and expected outcomes are provided for every execution step. No host-side backend commands or forced git commits remain in the plan.

## Type Consistency Check

The plan consistently uses:

- `sparse_backend`
- `SparseProvider`
- `SparseProviderMetadata`
- `SparseVectorPayload`
- `Bm25SparseProvider`
- `ExternalBgeM3SparseProvider`
- `sparse_backend_change_requires_reindex`

These names are reused consistently across tasks.
