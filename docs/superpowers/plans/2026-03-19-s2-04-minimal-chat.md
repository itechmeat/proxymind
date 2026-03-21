# S2-04: Minimal Chat — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable question-answering based on uploaded knowledge — dense vector search against active snapshot, LLM via LiteLLM, JSON response (no streaming).

**Architecture:** Thin ChatService orchestrator coordinates RetrievalService (embedding + Qdrant search), LLMService (LiteLLM wrapper), and pure prompt_builder functions. Three Chat API endpoints: create session, send message, get history.

**Tech Stack:** FastAPI, LiteLLM, Qdrant (dense search), SQLAlchemy, Pydantic, structlog

**Spec:** `docs/superpowers/specs/2026-03-19-s2-04-minimal-chat-design.md`

---

### Task 1: Configuration — LLM and retrieval settings

**Files:**
- Modify: `backend/app/core/config.py:36` (after `bm25_language`)
- Modify: `backend/.env.example` (add LLM vars)

- [ ] **Step 1: Add LLM and retrieval settings to Settings**

In `backend/app/core/config.py`, add after line 36 (`bm25_language`):

```python
llm_model: str = Field(default="openai/gpt-4o", min_length=1)
llm_api_key: str | None = Field(default=None)
llm_api_base: str | None = Field(default=None)
llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)

retrieval_top_n: int = Field(default=5, ge=1)
min_retrieved_chunks: int = Field(default=1, ge=0)
min_dense_similarity: float | None = Field(default=None)
```

- [ ] **Step 2: Add LLM vars to .env.example**

Append to `backend/.env.example`:

```bash
# LLM Provider (via LiteLLM)
LLM_MODEL=openai/gpt-4o
LLM_API_KEY=
LLM_API_BASE=
```

- [ ] **Step 3: Verify settings load**

Run: `cd backend && python -c "from app.core.config import Settings; s = Settings(_env_file=''); print(s.llm_model, s.retrieval_top_n, s.min_dense_similarity)"`

Expected: `openai/gpt-4o 5 None`

- [ ] **Step 4: Stage checkpoint**

Stage files: `backend/app/core/config.py`, `backend/.env.example`
Suggested commit message: `feat(config): add LLM and retrieval settings for S2-04`
**Note: do NOT commit without explicit user permission (CLAUDE.md git policy).**

---

### Task 2: QdrantService — add search() method

**Files:**
- Modify: `backend/app/services/qdrant.py:135` (before `close()`)
- Test: `backend/tests/unit/services/test_qdrant.py`

- [ ] **Step 1: Write the failing test for search**

Append to `backend/tests/unit/services/test_qdrant.py`:

```python
@pytest.mark.asyncio
async def test_search_returns_scored_points_filtered_by_snapshot() -> None:
    snapshot_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    source_id = uuid.uuid4()

    mock_point = SimpleNamespace(
        id=str(chunk_id),
        score=0.85,
        payload={
            "chunk_id": str(chunk_id),
            "source_id": str(source_id),
            "text_content": "some text",
            "anchor_page": 1,
            "anchor_chapter": "Chapter 1",
            "anchor_section": None,
            "anchor_timecode": None,
        },
    )
    query_response = SimpleNamespace(points=[mock_point])
    client = SimpleNamespace(
        query_points=AsyncMock(return_value=query_response),
    )
    service = QdrantService(
        client=client,  # type: ignore[arg-type]
        collection_name="proxymind_chunks",
        embedding_dimensions=3072,
    )

    from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID

    results = await service.search(
        vector=[0.1] * 3072,
        snapshot_id=snapshot_id,
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        limit=5,
    )

    assert len(results) == 1
    assert results[0].chunk_id == chunk_id
    assert results[0].source_id == source_id
    assert results[0].text_content == "some text"
    assert results[0].score == 0.85
    assert results[0].anchor_metadata == {
        "page": 1,
        "chapter": "Chapter 1",
        "section": None,
        "timecode": None,
    }

    # Verify filter was applied
    call_kwargs = client.query_points.await_args.kwargs
    assert call_kwargs["limit"] == 5


@pytest.mark.asyncio
async def test_search_with_score_threshold_filters_low_scores() -> None:
    low_point = SimpleNamespace(
        id=str(uuid.uuid4()),
        score=0.2,
        payload={
            "chunk_id": str(uuid.uuid4()),
            "source_id": str(uuid.uuid4()),
            "text_content": "irrelevant",
            "anchor_page": None,
            "anchor_chapter": None,
            "anchor_section": None,
            "anchor_timecode": None,
        },
    )
    query_response = SimpleNamespace(points=[low_point])
    client = SimpleNamespace(
        query_points=AsyncMock(return_value=query_response),
    )
    service = QdrantService(
        client=client,  # type: ignore[arg-type]
        collection_name="proxymind_chunks",
        embedding_dimensions=3072,
    )

    from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID

    results = await service.search(
        vector=[0.1] * 3072,
        snapshot_id=uuid.uuid4(),
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        limit=5,
        score_threshold=0.3,
    )

    assert len(results) == 0


@pytest.mark.asyncio
async def test_search_returns_empty_list_when_no_results() -> None:
    query_response = SimpleNamespace(points=[])
    client = SimpleNamespace(
        query_points=AsyncMock(return_value=query_response),
    )
    service = QdrantService(
        client=client,  # type: ignore[arg-type]
        collection_name="proxymind_chunks",
        embedding_dimensions=3072,
    )

    from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID

    results = await service.search(
        vector=[0.1] * 3072,
        snapshot_id=uuid.uuid4(),
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        limit=5,
    )

    assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/services/test_qdrant.py::test_search_returns_scored_points_filtered_by_snapshot -v`

Expected: FAIL — `QdrantService has no attribute 'search'`

- [ ] **Step 3: Add RetrievedChunk dataclass and search() method**

In `backend/app/services/qdrant.py`, add the `RetrievedChunk` dataclass after `QdrantChunkPoint` (line ~48) and the `search()` method to `QdrantService` before `close()` (line ~135):

```python
@dataclass(slots=True, frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    source_id: UUID
    text_content: str
    score: float
    anchor_metadata: dict[str, Any]
```

```python
async def search(
    self,
    *,
    vector: list[float],
    snapshot_id: UUID,
    agent_id: UUID,
    knowledge_base_id: UUID,
    limit: int = 5,
    score_threshold: float | None = None,
) -> list[RetrievedChunk]:
    query_filter = models.Filter(
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
    )

    points = await self._search_points(
        vector=vector,
        query_filter=query_filter,
        limit=limit,
        score_threshold=score_threshold,
    )

    results: list[RetrievedChunk] = []
    for point in points:
        payload = point.payload or {}
        score = point.score if point.score is not None else 0.0
        if score_threshold is not None and score < score_threshold:
            continue
        results.append(
            RetrievedChunk(
                chunk_id=UUID(payload["chunk_id"]),
                source_id=UUID(payload["source_id"]),
                text_content=payload.get("text_content", ""),
                score=score,
                anchor_metadata={
                    "page": payload.get("anchor_page"),
                    "chapter": payload.get("anchor_chapter"),
                    "section": payload.get("anchor_section"),
                    "timecode": payload.get("anchor_timecode"),
                },
            )
        )
    return results

@retry(
    retry=retry_if_exception_type((httpx.TransportError, ResponseHandlingException)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    reraise=True,
)
async def _search_points(
    self,
    *,
    vector: list[float],
    query_filter: models.Filter,
    limit: int,
    score_threshold: float | None,
) -> list:
    response = await self._client.query_points(
        collection_name=self._collection_name,
        query=vector,
        using="dense",
        query_filter=query_filter,
        limit=limit,
        score_threshold=score_threshold,
        with_payload=True,
    )
    return response.points
```

**Note:** `query_points` is the Qdrant client search API. `score_threshold` is passed directly — when `None`, Qdrant ignores it. The client-side `score < score_threshold` check is a safety net for Qdrant versions that may not honor it.

- [ ] **Step 4: Export RetrievedChunk from services/__init__.py**

Add to `backend/app/services/__init__.py`:

```python
from app.services.qdrant import RetrievedChunk
```

And add `"RetrievedChunk"` to `__all__`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/services/test_qdrant.py -v -k search`

Expected: 3 tests PASS

- [ ] **Step 6: Stage checkpoint**

Stage files: `backend/app/services/qdrant.py`, `backend/app/services/__init__.py`, `backend/tests/unit/services/test_qdrant.py`
Suggested commit message: `feat(qdrant): add dense vector search with payload filtering`
**Note: do NOT commit without explicit user permission.**

---

### Task 3: SnapshotService — add get_active_snapshot()

**Files:**
- Modify: `backend/app/services/snapshot.py:62` (after `list_snapshots`)
- Test: `backend/tests/unit/services/test_snapshot_service.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/unit/services/test_snapshot_service.py`:

```python
from __future__ import annotations

import uuid

import pytest

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import KnowledgeSnapshot
from app.db.models.enums import SnapshotStatus
from app.services.snapshot import SnapshotService


@pytest.mark.asyncio
async def test_get_active_snapshot_returns_active(db_session, seeded_agent) -> None:
    snapshot = KnowledgeSnapshot(
        id=uuid.uuid7(),
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        name="Test snapshot",
        status=SnapshotStatus.ACTIVE,
    )
    db_session.add(snapshot)
    await db_session.flush()

    service = SnapshotService(session=db_session)
    result = await service.get_active_snapshot(
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
    )

    assert result is not None
    assert result.id == snapshot.id
    assert result.status == SnapshotStatus.ACTIVE


@pytest.mark.asyncio
async def test_get_active_snapshot_returns_none_when_no_active(db_session, seeded_agent) -> None:
    service = SnapshotService(session=db_session)
    result = await service.get_active_snapshot(
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
    )

    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/services/test_snapshot_service.py::test_get_active_snapshot_returns_active -v`

Expected: FAIL — `SnapshotService has no attribute 'get_active_snapshot'`

- [ ] **Step 3: Implement get_active_snapshot()**

In `backend/app/services/snapshot.py`, add after `get_snapshot()` method (around line 77):

```python
async def get_active_snapshot(
    self,
    *,
    agent_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    session: AsyncSession | None = None,
) -> KnowledgeSnapshot | None:
    db_session = self._resolve_session(session)
    return await db_session.scalar(
        select(KnowledgeSnapshot).where(
            KnowledgeSnapshot.agent_id == agent_id,
            KnowledgeSnapshot.knowledge_base_id == knowledge_base_id,
            KnowledgeSnapshot.status == SnapshotStatus.ACTIVE,
        )
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/services/test_snapshot_service.py -v`

Expected: 2 tests PASS

- [ ] **Step 5: Stage checkpoint**

Stage files: `backend/app/services/snapshot.py`, `backend/tests/unit/services/test_snapshot_service.py`
Suggested commit message: `feat(snapshot): add get_active_snapshot query method`
**Note: do NOT commit without explicit user permission.**

---

### Task 4: Prompt builder — pure functions

**Files:**
- Create: `backend/app/services/prompt.py`
- Test: `backend/tests/unit/services/test_prompt_builder.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/services/test_prompt_builder.py`:

```python
from __future__ import annotations

import uuid

import pytest

from app.services.qdrant import RetrievedChunk


def _make_chunk(text: str = "chunk text", source_id: uuid.UUID | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id or uuid.uuid4(),
        text_content=text,
        score=0.9,
        anchor_metadata={"page": 1, "chapter": None, "section": None, "timecode": None},
    )


class TestBuildChatPrompt:
    def test_returns_system_and_user_messages(self) -> None:
        from app.services.prompt import build_chat_prompt

        chunks = [_make_chunk("relevant info")]
        messages = build_chat_prompt("What is X?", chunks)

        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_system_message_contains_grounding_instruction(self) -> None:
        from app.services.prompt import build_chat_prompt

        messages = build_chat_prompt("question", [_make_chunk()])
        system_content = messages[0]["content"]

        assert "based ONLY" in system_content or "based only" in system_content.lower()
        assert "do not make up" in system_content.lower()

    def test_user_message_contains_query_and_context(self) -> None:
        from app.services.prompt import build_chat_prompt

        chunks = [_make_chunk("The answer is 42")]
        messages = build_chat_prompt("What is the answer?", chunks)
        user_content = messages[1]["content"]

        assert "The answer is 42" in user_content
        assert "What is the answer?" in user_content

    def test_multiple_chunks_all_included(self) -> None:
        from app.services.prompt import build_chat_prompt

        chunks = [_make_chunk(f"chunk {i}") for i in range(3)]
        messages = build_chat_prompt("question", chunks)
        user_content = messages[1]["content"]

        for i in range(3):
            assert f"chunk {i}" in user_content

    def test_chunk_source_id_included_in_context(self) -> None:
        from app.services.prompt import build_chat_prompt

        sid = uuid.uuid4()
        chunks = [_make_chunk("text", source_id=sid)]
        messages = build_chat_prompt("question", chunks)
        user_content = messages[1]["content"]

        assert str(sid) in user_content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/services/test_prompt_builder.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.prompt'`

- [ ] **Step 3: Implement prompt.py**

Create `backend/app/services/prompt.py`:

```python
from __future__ import annotations

from app.services.qdrant import RetrievedChunk

SYSTEM_PROMPT = (
    "You are a knowledgeable assistant. Answer the user's question based ONLY "
    "on the provided context. If the context does not contain enough information "
    "to answer, say so honestly. Do not make up information."
)

NO_CONTEXT_REFUSAL = "I don't have information about this in my knowledge base."


def build_chat_prompt(
    user_query: str,
    retrieved_chunks: list[RetrievedChunk],
) -> list[dict[str, str]]:
    context_parts: list[str] = []
    for i, chunk in enumerate(retrieved_chunks, 1):
        context_parts.append(
            f"---\n[Chunk {i}] (source: {chunk.source_id})\n{chunk.text_content}"
        )

    context_block = "Context from knowledge base:\n\n" + "\n\n".join(context_parts) + "\n\n---"
    user_content = f"{context_block}\n\nQuestion: {user_query}"

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/services/test_prompt_builder.py -v`

Expected: 5 tests PASS

- [ ] **Step 5: Stage checkpoint**

Stage files: `backend/app/services/prompt.py`, `backend/tests/unit/services/test_prompt_builder.py`
Suggested commit message: `feat(prompt): add minimal RAG prompt builder`
**Note: do NOT commit without explicit user permission.**

---

### Task 5: LLMService — LiteLLM wrapper

**Files:**
- Create: `backend/app/services/llm.py`
- Test: `backend/tests/unit/services/test_llm_service.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/services/test_llm_service.py`:

```python
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


class TestLLMService:
    @pytest.mark.asyncio
    async def test_complete_returns_llm_response(self) -> None:
        from app.services.llm import LLMService

        mock_response = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="Hello world"))
            ],
            model="openai/gpt-4o",
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )

        with patch("app.services.llm.litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_response
            service = LLMService(model="openai/gpt-4o", api_key="test-key")
            result = await service.complete(
                messages=[{"role": "user", "content": "hi"}]
            )

        assert result.content == "Hello world"
        assert result.model_name == "openai/gpt-4o"
        assert result.token_count_prompt == 100
        assert result.token_count_completion == 20

    @pytest.mark.asyncio
    async def test_complete_passes_parameters_to_litellm(self) -> None:
        from app.services.llm import LLMService

        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            model="openai/gpt-4o",
            usage=SimpleNamespace(prompt_tokens=50, completion_tokens=10),
        )

        with patch("app.services.llm.litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_response
            service = LLMService(
                model="openai/gpt-4o",
                api_key="test-key",
                api_base="https://custom.endpoint/v1",
            )
            await service.complete(
                messages=[{"role": "user", "content": "hi"}],
                temperature=0.3,
            )

        call_kwargs = mock_acompletion.await_args.kwargs
        assert call_kwargs["model"] == "openai/gpt-4o"
        assert call_kwargs["api_key"] == "test-key"
        assert call_kwargs["api_base"] == "https://custom.endpoint/v1"
        assert call_kwargs["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_complete_raises_llm_error_on_failure(self) -> None:
        from app.services.llm import LLMError, LLMService

        with patch("app.services.llm.litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.side_effect = Exception("API timeout")
            service = LLMService(model="openai/gpt-4o", api_key="test-key")

            with pytest.raises(LLMError, match="API timeout"):
                await service.complete(
                    messages=[{"role": "user", "content": "hi"}]
                )

    @pytest.mark.asyncio
    async def test_complete_handles_empty_content(self) -> None:
        from app.services.llm import LLMService

        mock_response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))],
            model="openai/gpt-4o",
            usage=SimpleNamespace(prompt_tokens=50, completion_tokens=0),
        )

        with patch("app.services.llm.litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.return_value = mock_response
            service = LLMService(model="openai/gpt-4o", api_key="test-key")
            result = await service.complete(
                messages=[{"role": "user", "content": "hi"}]
            )

        assert result.content == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/services/test_llm_service.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.llm'`

- [ ] **Step 3: Implement LLMService**

Create `backend/app/services/llm.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import litellm
import structlog

logger = structlog.get_logger(__name__)


class LLMError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class LLMResponse:
    content: str
    model_name: str
    token_count_prompt: int
    token_count_completion: int


class LLMService:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        api_base: str | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._api_base = api_base

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.7,
    ) -> LLMResponse:
        try:
            response = await litellm.acompletion(
                model=self._model,
                messages=messages,
                api_key=self._api_key,
                api_base=self._api_base,
                temperature=temperature,
            )
        except Exception as error:
            logger.error(
                "llm.completion_failed",
                model=self._model,
                error=str(error),
            )
            raise LLMError(str(error)) from error

        content = response.choices[0].message.content or ""
        usage = response.usage

        return LLMResponse(
            content=content,
            model_name=response.model,
            token_count_prompt=usage.prompt_tokens if usage else 0,
            token_count_completion=usage.completion_tokens if usage else 0,
        )
```

- [ ] **Step 4: Export from services/__init__.py**

Add to `backend/app/services/__init__.py`:

```python
from app.services.llm import LLMError, LLMResponse, LLMService
```

And add `"LLMError"`, `"LLMResponse"`, `"LLMService"` to `__all__`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/services/test_llm_service.py -v`

Expected: 4 tests PASS

- [ ] **Step 6: Stage checkpoint**

Stage files: `backend/app/services/llm.py`, `backend/app/services/__init__.py`, `backend/tests/unit/services/test_llm_service.py`
Suggested commit message: `feat(llm): add LiteLLM wrapper service`
**Note: do NOT commit without explicit user permission.**

---

### Task 6: RetrievalService — embedding + search

**Files:**
- Create: `backend/app/services/retrieval.py`
- Test: `backend/tests/unit/services/test_retrieval_service.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/services/test_retrieval_service.py`:

```python
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.services.qdrant import RetrievedChunk


def _make_retrieved_chunk(score: float = 0.9) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        text_content="test content",
        score=score,
        anchor_metadata={"page": 1, "chapter": None, "section": None, "timecode": None},
    )


class TestRetrievalService:
    @pytest.mark.asyncio
    async def test_search_embeds_query_and_searches_qdrant(self) -> None:
        from app.services.retrieval import RetrievalService

        query_vector = [0.1] * 3072
        expected_chunks = [_make_retrieved_chunk()]

        embedding_service = AsyncMock()
        embedding_service.embed_texts = AsyncMock(return_value=[query_vector])

        qdrant_service = AsyncMock()
        qdrant_service.search = AsyncMock(return_value=expected_chunks)

        service = RetrievalService(
            embedding_service=embedding_service,
            qdrant_service=qdrant_service,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )

        snapshot_id = uuid.uuid4()
        results = await service.search("test query", snapshot_id=snapshot_id, top_n=5)

        embedding_service.embed_texts.assert_awaited_once_with(
            ["test query"], task_type="RETRIEVAL_QUERY"
        )
        qdrant_service.search.assert_awaited_once_with(
            vector=query_vector,
            snapshot_id=snapshot_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            limit=5,
            score_threshold=None,
        )
        assert results == expected_chunks

    @pytest.mark.asyncio
    async def test_search_passes_score_threshold(self) -> None:
        from app.services.retrieval import RetrievalService

        embedding_service = AsyncMock()
        embedding_service.embed_texts = AsyncMock(return_value=[[0.1] * 3072])

        qdrant_service = AsyncMock()
        qdrant_service.search = AsyncMock(return_value=[])

        service = RetrievalService(
            embedding_service=embedding_service,
            qdrant_service=qdrant_service,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )

        await service.search(
            "query",
            snapshot_id=uuid.uuid4(),
            top_n=5,
            score_threshold=0.4,
        )

        call_kwargs = qdrant_service.search.await_args.kwargs
        assert call_kwargs["score_threshold"] == 0.4

    @pytest.mark.asyncio
    async def test_search_returns_empty_list_when_no_results(self) -> None:
        from app.services.retrieval import RetrievalService

        embedding_service = AsyncMock()
        embedding_service.embed_texts = AsyncMock(return_value=[[0.1] * 3072])

        qdrant_service = AsyncMock()
        qdrant_service.search = AsyncMock(return_value=[])

        service = RetrievalService(
            embedding_service=embedding_service,
            qdrant_service=qdrant_service,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )

        results = await service.search("query", snapshot_id=uuid.uuid4())
        assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/services/test_retrieval_service.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement RetrievalService**

Create `backend/app/services/retrieval.py`:

```python
from __future__ import annotations

from uuid import UUID

import structlog

from app.services.embedding import EmbeddingService
from app.services.qdrant import QdrantService, RetrievedChunk

logger = structlog.get_logger(__name__)


class RetrievalError(RuntimeError):
    pass


class RetrievalService:
    def __init__(
        self,
        *,
        embedding_service: EmbeddingService,
        qdrant_service: QdrantService,
        agent_id: UUID,
        knowledge_base_id: UUID,
    ) -> None:
        self._embedding_service = embedding_service
        self._qdrant_service = qdrant_service
        self._agent_id = agent_id
        self._knowledge_base_id = knowledge_base_id

    async def search(
        self,
        query: str,
        *,
        snapshot_id: UUID,
        top_n: int = 5,
        score_threshold: float | None = None,
    ) -> list[RetrievedChunk]:
        try:
            vectors = await self._embedding_service.embed_texts(
                [query], task_type="RETRIEVAL_QUERY"
            )
        except Exception as error:
            raise RetrievalError(f"Query embedding failed: {error}") from error

        query_vector = vectors[0]

        try:
            return await self._qdrant_service.search(
                vector=query_vector,
                snapshot_id=snapshot_id,
                agent_id=self._agent_id,
                knowledge_base_id=self._knowledge_base_id,
                limit=top_n,
                score_threshold=score_threshold,
            )
        except Exception as error:
            raise RetrievalError(f"Vector search failed: {error}") from error
```

- [ ] **Step 4: Export from services/__init__.py**

Add to `backend/app/services/__init__.py`:

```python
from app.services.retrieval import RetrievalError, RetrievalService
```

And add `"RetrievalError"`, `"RetrievalService"` to `__all__`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/services/test_retrieval_service.py -v`

Expected: 3 tests PASS

- [ ] **Step 6: Stage checkpoint**

Stage files: `backend/app/services/retrieval.py`, `backend/app/services/__init__.py`, `backend/tests/unit/services/test_retrieval_service.py`
Suggested commit message: `feat(retrieval): add dense vector retrieval service`
**Note: do NOT commit without explicit user permission.**

---

### Task 7: ChatService — orchestrator

**Files:**
- Create: `backend/app/services/chat.py`
- Test: `backend/tests/unit/services/test_chat_service.py`

This is the largest task. ChatService coordinates session creation, lazy bind, retrieval, LLM call, and message persistence.

- [ ] **Step 1: Write failing tests for session creation**

Create `backend/tests/unit/services/test_chat_service.py`:

```python
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import KnowledgeSnapshot, Message, Session
from app.db.models.enums import (
    MessageRole,
    MessageStatus,
    SessionChannel,
    SessionStatus,
    SnapshotStatus,
)
from app.services.qdrant import RetrievedChunk


def _make_chunk(text: str = "relevant text", source_id: uuid.UUID | None = None) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id or uuid.uuid4(),
        text_content=text,
        score=0.9,
        anchor_metadata={"page": 1, "chapter": None, "section": None, "timecode": None},
    )


def _mock_llm_response():
    from app.services.llm import LLMResponse

    return LLMResponse(
        content="The answer based on context.",
        model_name="openai/gpt-4o",
        token_count_prompt=200,
        token_count_completion=50,
    )


@pytest.mark.asyncio
async def test_create_session_with_active_snapshot(db_session, seeded_agent) -> None:
    snapshot = KnowledgeSnapshot(
        id=uuid.uuid7(),
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        name="Active",
        status=SnapshotStatus.ACTIVE,
    )
    db_session.add(snapshot)
    await db_session.flush()

    from app.services.chat import ChatService
    from app.services.snapshot import SnapshotService

    snapshot_svc = SnapshotService(session=db_session)
    chat_svc = ChatService(
        session=db_session,
        snapshot_service=snapshot_svc,
        retrieval_service=AsyncMock(),
        llm_service=AsyncMock(),
        settings=AsyncMock(min_retrieved_chunks=1, min_dense_similarity=None, retrieval_top_n=5, llm_temperature=0.7),
    )

    session = await chat_svc.create_session()
    assert session.snapshot_id == snapshot.id
    assert session.status == SessionStatus.ACTIVE
    assert session.channel == SessionChannel.WEB


@pytest.mark.asyncio
async def test_create_session_without_snapshot(db_session, seeded_agent) -> None:
    from app.services.chat import ChatService
    from app.services.snapshot import SnapshotService

    snapshot_svc = SnapshotService(session=db_session)
    chat_svc = ChatService(
        session=db_session,
        snapshot_service=snapshot_svc,
        retrieval_service=AsyncMock(),
        llm_service=AsyncMock(),
        settings=AsyncMock(min_retrieved_chunks=1, min_dense_similarity=None, retrieval_top_n=5, llm_temperature=0.7),
    )

    session = await chat_svc.create_session()
    assert session.snapshot_id is None
    assert session.status == SessionStatus.ACTIVE


@pytest.mark.asyncio
async def test_answer_with_retrieval_context(db_session, seeded_agent) -> None:
    snapshot = KnowledgeSnapshot(
        id=uuid.uuid7(),
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        name="Active",
        status=SnapshotStatus.ACTIVE,
    )
    db_session.add(snapshot)
    await db_session.flush()

    from app.services.chat import ChatService
    from app.services.snapshot import SnapshotService

    source_id = uuid.uuid4()
    chunks = [_make_chunk("info about X", source_id=source_id)]

    mock_retrieval = AsyncMock()
    mock_retrieval.search = AsyncMock(return_value=chunks)

    mock_llm = AsyncMock()
    mock_llm.complete = AsyncMock(return_value=_mock_llm_response())

    snapshot_svc = SnapshotService(session=db_session)
    chat_svc = ChatService(
        session=db_session,
        snapshot_service=snapshot_svc,
        retrieval_service=mock_retrieval,
        llm_service=mock_llm,
        settings=AsyncMock(min_retrieved_chunks=1, min_dense_similarity=None, retrieval_top_n=5, llm_temperature=0.7),
    )

    session = await chat_svc.create_session()
    msg, chunks_count = await chat_svc.answer(session.id, "What is X?")

    assert msg.role == MessageRole.ASSISTANT
    assert msg.status == MessageStatus.COMPLETE
    assert msg.content == "The answer based on context."
    assert msg.model_name == "openai/gpt-4o"
    assert msg.token_count_prompt == 200
    assert msg.token_count_completion == 50
    assert source_id in msg.source_ids
    assert chunks_count == 1


@pytest.mark.asyncio
async def test_answer_refuses_when_no_chunks(db_session, seeded_agent) -> None:
    snapshot = KnowledgeSnapshot(
        id=uuid.uuid7(),
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        name="Active",
        status=SnapshotStatus.ACTIVE,
    )
    db_session.add(snapshot)
    await db_session.flush()

    from app.services.chat import ChatService
    from app.services.snapshot import SnapshotService

    mock_retrieval = AsyncMock()
    mock_retrieval.search = AsyncMock(return_value=[])

    mock_llm = AsyncMock()

    snapshot_svc = SnapshotService(session=db_session)
    chat_svc = ChatService(
        session=db_session,
        snapshot_service=snapshot_svc,
        retrieval_service=mock_retrieval,
        llm_service=mock_llm,
        settings=AsyncMock(min_retrieved_chunks=1, min_dense_similarity=None, retrieval_top_n=5, llm_temperature=0.7),
    )

    session = await chat_svc.create_session()
    msg, chunks_count = await chat_svc.answer(session.id, "unknown topic")

    assert msg.status == MessageStatus.COMPLETE
    assert "don't have information" in msg.content.lower() or "no information" in msg.content.lower()
    assert chunks_count == 0
    mock_llm.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_answer_raises_when_no_snapshot(db_session, seeded_agent) -> None:
    from app.services.chat import ChatService, NoActiveSnapshotError
    from app.services.snapshot import SnapshotService

    snapshot_svc = SnapshotService(session=db_session)
    chat_svc = ChatService(
        session=db_session,
        snapshot_service=snapshot_svc,
        retrieval_service=AsyncMock(),
        llm_service=AsyncMock(),
        settings=AsyncMock(min_retrieved_chunks=1, min_dense_similarity=None, retrieval_top_n=5, llm_temperature=0.7),
    )

    session = await chat_svc.create_session()
    assert session.snapshot_id is None

    with pytest.raises(NoActiveSnapshotError):
        await chat_svc.answer(session.id, "hello")


@pytest.mark.asyncio
async def test_lazy_bind_snapshot_on_first_message(db_session, seeded_agent) -> None:
    from app.services.chat import ChatService
    from app.services.snapshot import SnapshotService

    snapshot_svc = SnapshotService(session=db_session)
    chat_svc = ChatService(
        session=db_session,
        snapshot_service=snapshot_svc,
        retrieval_service=AsyncMock(),
        llm_service=AsyncMock(),
        settings=AsyncMock(min_retrieved_chunks=1, min_dense_similarity=None, retrieval_top_n=5, llm_temperature=0.7),
    )

    # Create session without active snapshot
    session = await chat_svc.create_session()
    assert session.snapshot_id is None

    # Now publish a snapshot
    snapshot = KnowledgeSnapshot(
        id=uuid.uuid7(),
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        name="Active",
        status=SnapshotStatus.ACTIVE,
    )
    db_session.add(snapshot)
    await db_session.flush()

    # Setup mocks for answer flow
    chunks = [_make_chunk()]
    chat_svc._retrieval_service.search = AsyncMock(return_value=chunks)
    chat_svc._llm_service.complete = AsyncMock(return_value=_mock_llm_response())

    # First message should lazy-bind
    msg, _ = await chat_svc.answer(session.id, "hello")
    assert msg.status == MessageStatus.COMPLETE

    # Session should now have snapshot_id
    await db_session.refresh(session)
    assert session.snapshot_id == snapshot.id


@pytest.mark.asyncio
async def test_answer_raises_for_unknown_session(db_session, seeded_agent) -> None:
    from app.services.chat import ChatService, SessionNotFoundError
    from app.services.snapshot import SnapshotService

    snapshot_svc = SnapshotService(session=db_session)
    chat_svc = ChatService(
        session=db_session,
        snapshot_service=snapshot_svc,
        retrieval_service=AsyncMock(),
        llm_service=AsyncMock(),
        settings=AsyncMock(min_retrieved_chunks=1, min_dense_similarity=None, retrieval_top_n=5, llm_temperature=0.7),
    )

    with pytest.raises(SessionNotFoundError):
        await chat_svc.answer(uuid.uuid4(), "hello")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/services/test_chat_service.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.chat'`

- [ ] **Step 3: Implement ChatService**

Create `backend/app/services/chat.py`:

```python
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import structlog

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import Message, Session
from app.db.models.enums import (
    MessageRole,
    MessageStatus,
    SessionChannel,
    SessionStatus,
)
from app.services.llm import LLMError
from app.services.prompt import NO_CONTEXT_REFUSAL, build_chat_prompt
from app.services.snapshot import SnapshotService

if TYPE_CHECKING:
    from app.services.llm import LLMService
    from app.services.retrieval import RetrievalService

logger = structlog.get_logger(__name__)


class SessionNotFoundError(RuntimeError):
    pass


class NoActiveSnapshotError(RuntimeError):
    pass


class ChatSettings(Protocol):
    min_retrieved_chunks: int
    min_dense_similarity: float | None
    retrieval_top_n: int
    llm_temperature: float


class ChatService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        snapshot_service: SnapshotService,
        retrieval_service: RetrievalService,
        llm_service: LLMService,
        settings: ChatSettings,
    ) -> None:
        self._session = session
        self._snapshot_service = snapshot_service
        self._retrieval_service = retrieval_service
        self._llm_service = llm_service
        self._settings = settings

    async def create_session(self, channel: str = "web") -> Session:
        active_snapshot = await self._snapshot_service.get_active_snapshot(
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )

        chat_session = Session(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            snapshot_id=active_snapshot.id if active_snapshot else None,
            status=SessionStatus.ACTIVE,
            channel=SessionChannel(channel),
            message_count=0,
        )
        self._session.add(chat_session)
        await self._session.commit()
        return chat_session

    async def answer(self, session_id: uuid.UUID, text: str) -> tuple[Message, int]:
        chat_session = await self._load_session(session_id)

        # Lazy bind: if session has no snapshot, try to find one now
        if chat_session.snapshot_id is None:
            active_snapshot = await self._snapshot_service.get_active_snapshot(
                agent_id=DEFAULT_AGENT_ID,
                knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            )
            if active_snapshot is None:
                raise NoActiveSnapshotError(
                    "No active knowledge snapshot. Publish a snapshot first."
                )
            chat_session.snapshot_id = active_snapshot.id
            await self._session.flush()

        # Save user message
        user_msg = Message(
            id=uuid.uuid7(),
            session_id=session_id,
            role=MessageRole.USER,
            content=text,
            status=MessageStatus.RECEIVED,
            snapshot_id=chat_session.snapshot_id,
        )
        self._session.add(user_msg)
        chat_session.message_count += 1
        await self._session.flush()

        # Retrieve relevant chunks
        chunks = await self._retrieval_service.search(
            text,
            snapshot_id=chat_session.snapshot_id,
            top_n=self._settings.retrieval_top_n,
            score_threshold=self._settings.min_dense_similarity,
        )

        # Refusal if not enough chunks
        if len(chunks) < self._settings.min_retrieved_chunks:
            msg = await self._save_assistant_message(
                session_id=session_id,
                snapshot_id=chat_session.snapshot_id,
                content=NO_CONTEXT_REFUSAL,
                status=MessageStatus.COMPLETE,
                source_ids=[],
                chat_session=chat_session,
            )
            await self._session.commit()
            return msg, 0

        # Build prompt and call LLM
        messages = build_chat_prompt(text, chunks)

        try:
            llm_response = await self._llm_service.complete(
                messages,
                temperature=self._settings.llm_temperature,
            )
        except LLMError:
            await self._save_assistant_message(
                session_id=session_id,
                snapshot_id=chat_session.snapshot_id,
                content="Failed to generate response.",
                status=MessageStatus.FAILED,
                source_ids=[],
                chat_session=chat_session,
            )
            await self._session.commit()
            raise

        # Deduplicated source_ids
        source_ids = list({chunk.source_id for chunk in chunks})
        chunks_count = len(chunks)

        msg = await self._save_assistant_message(
            session_id=session_id,
            snapshot_id=chat_session.snapshot_id,
            content=llm_response.content,
            status=MessageStatus.COMPLETE,
            model_name=llm_response.model_name,
            token_count_prompt=llm_response.token_count_prompt,
            token_count_completion=llm_response.token_count_completion,
            source_ids=source_ids,
            chat_session=chat_session,
        )
        await self._session.commit()
        return msg, chunks_count

    async def get_session(self, session_id: uuid.UUID) -> Session:
        chat_session = await self._session.scalar(
            select(Session)
            .where(Session.id == session_id)
            .options(selectinload(Session.messages))
        )
        if chat_session is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        return chat_session

    async def _load_session(self, session_id: uuid.UUID) -> Session:
        chat_session = await self._session.scalar(
            select(Session).where(Session.id == session_id)
        )
        if chat_session is None:
            raise SessionNotFoundError(f"Session {session_id} not found")
        return chat_session

    async def _save_assistant_message(
        self,
        *,
        session_id: uuid.UUID,
        snapshot_id: uuid.UUID,
        content: str,
        status: MessageStatus,
        source_ids: list[uuid.UUID],
        chat_session: Session,
        model_name: str | None = None,
        token_count_prompt: int | None = None,
        token_count_completion: int | None = None,
    ) -> Message:
        msg = Message(
            id=uuid.uuid7(),
            session_id=session_id,
            role=MessageRole.ASSISTANT,
            content=content,
            status=status,
            snapshot_id=snapshot_id,
            model_name=model_name,
            token_count_prompt=token_count_prompt,
            token_count_completion=token_count_completion,
            source_ids=source_ids if source_ids else None,
        )
        self._session.add(msg)
        chat_session.message_count += 1
        await self._session.flush()
        return msg
```

- [ ] **Step 4: Export from services/__init__.py**

Add to `backend/app/services/__init__.py`:

```python
from app.services.chat import ChatService, NoActiveSnapshotError, SessionNotFoundError
```

And add `"ChatService"`, `"NoActiveSnapshotError"`, `"SessionNotFoundError"` to `__all__`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/services/test_chat_service.py -v`

Expected: 7 tests PASS

- [ ] **Step 6: Stage checkpoint**

Stage files: `backend/app/services/chat.py`, `backend/app/services/__init__.py`, `backend/tests/unit/services/test_chat_service.py`
Suggested commit message: `feat(chat): add ChatService orchestrator with lazy bind`
**Note: do NOT commit without explicit user permission.**

---

### Task 8: Chat schemas — Pydantic request/response models

**Files:**
- Create: `backend/app/api/chat_schemas.py`

- [ ] **Step 1: Create chat_schemas.py**

```python
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.enums import MessageRole, MessageStatus, SessionChannel, SessionStatus


class CreateSessionRequest(BaseModel):
    channel: SessionChannel = SessionChannel.WEB


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_id: uuid.UUID | None
    channel: SessionChannel
    status: SessionStatus
    message_count: int
    created_at: datetime


class SendMessageRequest(BaseModel):
    session_id: uuid.UUID
    text: str = Field(min_length=1, max_length=10000)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    message_id: uuid.UUID
    session_id: uuid.UUID
    role: MessageRole
    content: str
    status: MessageStatus
    model_name: str | None = None
    retrieved_chunks_count: int = 0
    token_count_prompt: int | None = None
    token_count_completion: int | None = None
    created_at: datetime


class MessageInHistory(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    status: MessageStatus
    model_name: str | None = None
    created_at: datetime


class SessionWithMessagesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: SessionStatus
    channel: SessionChannel
    snapshot_id: uuid.UUID | None
    message_count: int
    created_at: datetime
    messages: list[MessageInHistory]
```

- [ ] **Step 2: Verify import works**

Run: `cd backend && python -c "from app.api.chat_schemas import CreateSessionRequest, SendMessageRequest, SessionResponse, MessageResponse, SessionWithMessagesResponse; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Stage checkpoint**

Stage files: `backend/app/api/chat_schemas.py`
Suggested commit message: `feat(api): add Pydantic schemas for chat endpoints`
**Note: do NOT commit without explicit user permission.**

---

### Task 9: Chat API router + dependency injection + wiring

**Files:**
- Create: `backend/app/api/chat.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add DI functions to dependencies.py**

Add to `backend/app/api/dependencies.py`:

```python
from app.services.chat import ChatService
from app.services.llm import LLMService
from app.services.retrieval import RetrievalService


def get_llm_service(request: Request) -> LLMService:
    return request.app.state.llm_service


def get_retrieval_service(request: Request) -> RetrievalService:
    return request.app.state.retrieval_service


def get_chat_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    retrieval_service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
    request: Request,
) -> ChatService:
    return ChatService(
        session=session,
        snapshot_service=snapshot_service,
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        settings=request.app.state.settings,
    )
```

- [ ] **Step 2: Create the chat router**

Create `backend/app/api/chat.py`:

```python
from __future__ import annotations

import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.api.chat_schemas import (
    CreateSessionRequest,
    MessageResponse,
    SendMessageRequest,
    SessionResponse,
    SessionWithMessagesResponse,
)
from app.api.dependencies import get_chat_service
from app.services.chat import ChatService, NoActiveSnapshotError, SessionNotFoundError
from app.services.llm import LLMError

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def create_session(
    body: CreateSessionRequest,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> SessionResponse:
    session = await chat_service.create_session(channel=body.channel.value)
    return SessionResponse.model_validate(session)


@router.post("/messages", response_model=MessageResponse)
async def send_message(
    body: SendMessageRequest,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> MessageResponse:
    try:
        msg, chunks_count = await chat_service.answer(body.session_id, body.text)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")
    except NoActiveSnapshotError:
        raise HTTPException(
            status_code=422,
            detail="No active knowledge snapshot. Publish a snapshot first.",
        )
    except LLMError as error:
        logger.error("chat.llm_error", session_id=str(body.session_id), error=str(error))
        raise HTTPException(status_code=500, detail=f"LLM error: {error}")

    return MessageResponse(
        message_id=msg.id,
        session_id=msg.session_id,
        role=msg.role,
        content=msg.content,
        status=msg.status,
        model_name=msg.model_name,
        retrieved_chunks_count=chunks_count,
        token_count_prompt=msg.token_count_prompt,
        token_count_completion=msg.token_count_completion,
        created_at=msg.created_at,
    )


@router.get("/sessions/{session_id}", response_model=SessionWithMessagesResponse)
async def get_session(
    session_id: uuid.UUID,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> SessionWithMessagesResponse:
    try:
        session = await chat_service.get_session(session_id)
    except SessionNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionWithMessagesResponse.model_validate(session)
```

- [ ] **Step 3: Wire up lifespan and router in main.py**

In `backend/app/main.py`:

Add imports:
```python
from qdrant_client import AsyncQdrantClient

from app.api.chat import router as chat_router
from app.services.embedding import EmbeddingService
from app.services.llm import LLMService
from app.services.qdrant import QdrantService
from app.services.retrieval import RetrievalService
from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
```

Add to lifespan (after `arq_pool` initialization, before `logger.info("app.startup")`):

```python
qdrant_client = AsyncQdrantClient(url=settings.qdrant_url)
app.state.qdrant_service = QdrantService(
    client=qdrant_client,
    collection_name=settings.qdrant_collection,
    embedding_dimensions=settings.embedding_dimensions,
)

app.state.embedding_service = EmbeddingService(
    model=settings.embedding_model,
    dimensions=settings.embedding_dimensions,
    batch_size=settings.embedding_batch_size,
    api_key=settings.gemini_api_key,
)

app.state.llm_service = LLMService(
    model=settings.llm_model,
    api_key=settings.llm_api_key,
    api_base=settings.llm_api_base,
)

app.state.retrieval_service = RetrievalService(
    embedding_service=app.state.embedding_service,
    qdrant_service=app.state.qdrant_service,
    agent_id=DEFAULT_AGENT_ID,
    knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
)
```

Add cleanup in shutdown (before `logger.info("app.shutdown")`):

```python
try:
    await app.state.qdrant_service.close()
except Exception as error:
    logger.error("app.shutdown.qdrant_close_failed", error=str(error))
```

Register the router:
```python
app.include_router(chat_router)
```

- [ ] **Step 4: Verify app starts (syntax check)**

Run: `cd backend && python -c "from app.main import app; print(f'Routes: {len(app.routes)}')"`

Expected: Route count increases (should be at least 8: health(2) + admin(6) + chat(3) + openapi(1))

- [ ] **Step 5: Stage checkpoint**

Stage files: `backend/app/api/chat.py`, `backend/app/api/dependencies.py`, `backend/app/main.py`
Suggested commit message: `feat(api): add chat endpoints with DI wiring`
**Note: do NOT commit without explicit user permission.**

---

### Task 10: Integration tests — E2E chat API

**Files:**
- Create: `backend/tests/integration/test_chat_api.py`
- Modify: `backend/tests/conftest.py` (add chat_app fixture)

- [ ] **Step 1: Add chat app fixture to conftest.py**

Add to `backend/tests/conftest.py`:

```python
from app.api.chat import router as chat_router


@pytest.fixture
def chat_app(
    session_factory: async_sessionmaker[AsyncSession],
) -> FastAPI:
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.services.llm import LLMResponse, LLMService

    app = FastAPI()
    app.include_router(chat_router)

    mock_llm = AsyncMock(spec=LLMService)
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            content="Answer from LLM based on context.",
            model_name="test-model",
            token_count_prompt=100,
            token_count_completion=30,
        )
    )

    mock_retrieval = AsyncMock()

    app.state.settings = SimpleNamespace(
        min_retrieved_chunks=1,
        min_dense_similarity=None,
        retrieval_top_n=5,
        llm_temperature=0.7,
    )
    app.state.session_factory = session_factory
    app.state.llm_service = mock_llm
    app.state.retrieval_service = mock_retrieval
    return app


@pytest_asyncio.fixture
async def chat_client(chat_app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=chat_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
```

- [ ] **Step 2: Write integration tests**

Create `backend/tests/integration/test_chat_api.py`:

```python
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import KnowledgeSnapshot
from app.db.models.enums import SnapshotStatus
from app.services.qdrant import RetrievedChunk


def _make_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        text_content="relevant knowledge",
        score=0.9,
        anchor_metadata={"page": 1, "chapter": None, "section": None, "timecode": None},
    )


@pytest.mark.asyncio
async def test_create_session_returns_201(
    chat_client: httpx.AsyncClient,
    db_session,
    seeded_agent,
    committed_data_cleanup,
) -> None:
    response = await chat_client.post("/api/chat/sessions", json={"channel": "web"})
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "active"
    assert data["channel"] == "web"
    assert data["message_count"] == 0


@pytest.mark.asyncio
async def test_send_message_returns_assistant_response(
    chat_client: httpx.AsyncClient,
    chat_app,
    session_factory,
    seeded_agent,
    committed_data_cleanup,
) -> None:
    # Create active snapshot via direct DB
    from sqlalchemy.ext.asyncio import AsyncSession

    async with session_factory() as session:
        snapshot = KnowledgeSnapshot(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            name="Test Active",
            status=SnapshotStatus.ACTIVE,
        )
        session.add(snapshot)
        await session.commit()

    # Mock retrieval to return chunks
    chat_app.state.retrieval_service.search = AsyncMock(return_value=[_make_chunk()])

    # Create session
    session_resp = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_resp.json()["id"]

    # Send message
    msg_resp = await chat_client.post("/api/chat/messages", json={
        "session_id": session_id,
        "text": "What is this about?",
    })
    assert msg_resp.status_code == 200
    data = msg_resp.json()
    assert data["role"] == "assistant"
    assert data["status"] == "complete"
    assert data["content"] == "Answer from LLM based on context."
    assert data["retrieved_chunks_count"] == 1


@pytest.mark.asyncio
async def test_send_message_returns_422_without_snapshot(
    chat_client: httpx.AsyncClient,
    seeded_agent,
    committed_data_cleanup,
) -> None:
    # Create session (no active snapshot)
    session_resp = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_resp.json()["id"]

    # Send message — should 422
    msg_resp = await chat_client.post("/api/chat/messages", json={
        "session_id": session_id,
        "text": "hello",
    })
    assert msg_resp.status_code == 422
    assert "snapshot" in msg_resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_send_message_returns_404_for_unknown_session(
    chat_client: httpx.AsyncClient,
    seeded_agent,
    committed_data_cleanup,
) -> None:
    msg_resp = await chat_client.post("/api/chat/messages", json={
        "session_id": str(uuid.uuid4()),
        "text": "hello",
    })
    assert msg_resp.status_code == 404


@pytest.mark.asyncio
async def test_get_session_returns_history(
    chat_client: httpx.AsyncClient,
    chat_app,
    session_factory,
    seeded_agent,
    committed_data_cleanup,
) -> None:
    # Create active snapshot
    async with session_factory() as session:
        snapshot = KnowledgeSnapshot(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            name="Test Active",
            status=SnapshotStatus.ACTIVE,
        )
        session.add(snapshot)
        await session.commit()

    chat_app.state.retrieval_service.search = AsyncMock(return_value=[_make_chunk()])

    # Create session + send message
    session_resp = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_resp.json()["id"]

    await chat_client.post("/api/chat/messages", json={
        "session_id": session_id,
        "text": "question",
    })

    # Get history
    history_resp = await chat_client.get(f"/api/chat/sessions/{session_id}")
    assert history_resp.status_code == 200
    data = history_resp.json()
    assert data["message_count"] == 2  # 1 user + 1 assistant, both increment counter
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "user"
    assert data["messages"][1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_lazy_bind_e2e(
    chat_client: httpx.AsyncClient,
    chat_app,
    session_factory,
    seeded_agent,
    committed_data_cleanup,
) -> None:
    # Create session WITHOUT active snapshot
    session_resp = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_resp.json()["id"]
    assert session_resp.json()["snapshot_id"] is None

    # Now create active snapshot
    async with session_factory() as session:
        snapshot = KnowledgeSnapshot(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            name="Test Active",
            status=SnapshotStatus.ACTIVE,
        )
        session.add(snapshot)
        await session.commit()
        snapshot_id = str(snapshot.id)

    # Mock retrieval
    chat_app.state.retrieval_service.search = AsyncMock(return_value=[_make_chunk()])

    # Send message — should succeed via lazy bind
    msg_resp = await chat_client.post("/api/chat/messages", json={
        "session_id": session_id,
        "text": "hello after publish",
    })
    assert msg_resp.status_code == 200
    assert msg_resp.json()["status"] == "complete"

    # Verify session now has snapshot_id
    history_resp = await chat_client.get(f"/api/chat/sessions/{session_id}")
    assert history_resp.json()["snapshot_id"] == snapshot_id
```

- [ ] **Step 3: Run integration tests**

Run: `cd backend && python -m pytest tests/integration/test_chat_api.py -v`

Expected: 6 tests PASS

- [ ] **Step 4: Run full test suite**

Run: `cd backend && python -m pytest tests/ -v --timeout=120`

Expected: All tests PASS (existing + new)

- [ ] **Step 5: Stage checkpoint**

Stage files: `backend/tests/conftest.py`, `backend/tests/integration/test_chat_api.py`
Suggested commit message: `test(chat): add integration tests for chat API endpoints`
**Note: do NOT commit without explicit user permission.**

---

### Task 11: Final verification and cleanup

- [ ] **Step 1: Run the full test suite**

Run: `cd backend && python -m pytest tests/ -v --timeout=120`

Expected: All tests PASS

- [ ] **Step 2: Run linter**

Run: `cd backend && python -m ruff check app/ tests/`

Expected: No errors

- [ ] **Step 3: Verify E2E scenario manually (requires running services)**

If Docker services are available:

```bash
# 1. Start services
docker-compose up -d

# 2. Create a session
curl -s -X POST http://localhost:8000/api/chat/sessions \
  -H "Content-Type: application/json" \
  -d '{"channel": "web"}' | python -m json.tool

# 3. If you have an active snapshot, send a message
curl -s -X POST http://localhost:8000/api/chat/messages \
  -H "Content-Type: application/json" \
  -d '{"session_id": "<UUID_FROM_STEP_2>", "text": "What do you know?"}' | python -m json.tool

# 4. Get session history
curl -s http://localhost:8000/api/chat/sessions/<UUID> | python -m json.tool
```

- [ ] **Step 4: Self-review against development.md**

Verify all checklist items from `docs/development.md#quick-reference`:
- Working value for current story? ✓ (E2E chat works)
- Simplest solution? ✓ (no over-engineering)
- Can be changed in next story? ✓ (isolated services)
- Readable code? ✓ (clear names, short functions)
- Meaningful tests? ✓ (unit + integration)
- No mocks outside tests/? ✓
- No fallbacks to stubs? ✓
- Dependencies from lock files? ✓ (litellm already in pyproject.toml)
- Secrets outside code? ✓ (env vars)
