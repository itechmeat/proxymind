# S4-02: SSE Streaming — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch `POST /api/chat/messages` from blocking JSON to SSE streaming with message state machine, idempotency, and persistence.

**Architecture:** Async generator pipeline — `LLMService.stream()` yields tokens → `ChatService.stream_answer()` yields domain events → API formats as SSE via `StreamingResponse`. Pre-stream checks (idempotency, concurrency) happen before `StreamingResponse` is returned, allowing standard HTTP error codes. Existing `complete()` and `answer()` methods are preserved.

**Tech Stack:** FastAPI `StreamingResponse`, LiteLLM `acompletion(stream=True)`, `httpx-sse` (dev dependency for tests)

**Spec:** `docs/superpowers/specs/2026-03-23-s4-02-sse-streaming-design.md`

**Dev standards:** `docs/development.md` — read before writing code, self-review after.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/app/db/models/dialogue.py` | Add `parent_message_id` nullable FK column |
| Create | `backend/migrations/versions/...` | Alembic migration for `parent_message_id` |
| Modify | `backend/app/services/llm.py` | Add `stream()` method, `LLMToken`/`LLMStreamEnd` dataclasses |
| Modify | `backend/app/services/chat.py` | Add `stream_answer()`, domain event types, idempotency/concurrency checks |
| Modify | `backend/app/api/chat.py` | Replace JSON endpoint with SSE `StreamingResponse`, add SSE formatting |
| Modify | `backend/app/api/chat_schemas.py` | Add `idempotency_key` to `SendMessageRequest` |
| Modify | `backend/app/core/config.py` | Add `sse_heartbeat_interval_seconds`, `sse_inter_token_timeout_seconds` |
| Modify | `backend/app/api/dependencies.py` | Pass new settings to `ChatService` |
| Modify | `backend/pyproject.toml` | Add `httpx-sse` to dev dependencies |
| Modify | `backend/tests/conftest.py` | Add `stream` mock to `mock_llm_service`, update `chat_app` settings |
| Create | `backend/tests/unit/test_llm_streaming.py` | Unit tests for `LLMService.stream()` |
| Create | `backend/tests/unit/test_chat_streaming.py` | Unit tests for `ChatService.stream_answer()` |
| Create | `backend/tests/integration/test_chat_sse.py` | Integration tests for full SSE flow |

---

## Task 1: Add `httpx-sse` dev dependency

**Files:**
- Modify: `backend/pyproject.toml:28-33`

- [ ] **Step 1: Add httpx-sse to dev dependencies**

In `backend/pyproject.toml`, add `httpx-sse` to the `[dependency-groups] dev` list:

```toml
[dependency-groups]
dev = [
  "httpx-sse>=0.4.0",
  "pytest>=8.4.2",
  "pytest-asyncio>=1.2.0",
  "ruff>=0.14.0",
  "testcontainers[postgres]>=4.14.2",
]
```

- [ ] **Step 2: Install dependencies**

Run: `cd backend && uv sync`
Expected: successful install including httpx-sse

- [ ] **Step 3: Commit**

```
feat(chat): add httpx-sse dev dependency for SSE testing (S4-02)
```

---

## Task 2: Add SSE config settings

**Files:**
- Modify: `backend/app/core/config.py:49-50`
- Test: `backend/tests/unit/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/unit/test_config.py`:

```python
def test_sse_settings_have_defaults() -> None:
    settings = get_settings()
    assert settings.sse_heartbeat_interval_seconds == 15
    assert settings.sse_inter_token_timeout_seconds == 30


def test_sse_settings_reject_non_positive_values(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError
    monkeypatch.setenv("SSE_HEARTBEAT_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/test_config.py::test_sse_settings_have_defaults -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'sse_heartbeat_interval_seconds'`

- [ ] **Step 3: Add settings to config.py**

In `backend/app/core/config.py`, add after `min_dense_similarity` (around line 52):

```python
    sse_heartbeat_interval_seconds: int = Field(default=15, ge=1)
    sse_inter_token_timeout_seconds: int = Field(default=30, ge=1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_config.py -v`
Expected: all config tests PASS

- [ ] **Step 5: Commit**

```
feat(config): add SSE heartbeat and inter-token timeout settings (S4-02)
```

---

## Task 3: Add `idempotency_key` to `SendMessageRequest`

**Files:**
- Modify: `backend/app/api/chat_schemas.py:32-44`

- [ ] **Step 1: Write the failing test**

Create inline test in the current test file or verify manually. The field should accept optional string.

```python
# Quick verification (can be run in a Python REPL or as a test):
from app.api.chat_schemas import SendMessageRequest
import uuid

req = SendMessageRequest(session_id=uuid.uuid4(), text="hi")
assert req.idempotency_key is None

req2 = SendMessageRequest(session_id=uuid.uuid4(), text="hi", idempotency_key="key-123")
assert req2.idempotency_key == "key-123"
```

- [ ] **Step 2: Add the field**

In `backend/app/api/chat_schemas.py`, add to `SendMessageRequest`:

```python
class SendMessageRequest(BaseModel):
    session_id: uuid.UUID
    text: str = Field(min_length=1)
    idempotency_key: str | None = None

    @field_validator("text", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                raise ValueError("text must not be empty")
            return normalized
        return value
```

- [ ] **Step 3: Verify existing tests still pass**

Run: `cd backend && uv run pytest tests/integration/test_chat_api.py -v`
Expected: all PASS (idempotency_key is optional, backward compatible)

- [ ] **Step 4: Commit**

```
feat(schema): add optional idempotency_key to SendMessageRequest (S4-02)
```

---

## Task 4: Add `parent_message_id` to Message model (migration)

**Files:**
- Modify: `backend/app/db/models/dialogue.py`
- Create: new Alembic migration

Assistant messages need an explicit link to the user message they respond to. This makes idempotency lookup reliable (no fragile timestamp-based pairing).

- [ ] **Step 1: Add column to Message model**

In `backend/app/db/models/dialogue.py`, add to `Message` class:

```python
    parent_message_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("messages.id"), nullable=True, default=None
    )
```

- [ ] **Step 2: Generate migration**

Run: `cd backend && uv run alembic revision --autogenerate -m "add parent_message_id to messages"`
Expected: new migration file created

- [ ] **Step 3: Apply migration**

Run: `cd backend && uv run alembic upgrade head`
Expected: migration applies successfully

- [ ] **Step 4: Verify existing tests pass**

Run: `cd backend && uv run pytest tests/unit/test_chat_service.py -v`
Expected: all PASS (column is nullable, backward compatible)

- [ ] **Step 5: Commit**

```
feat(db): add parent_message_id to messages for explicit user↔assistant pairing (S4-02)
```

---

## Task 5: LLM streaming — types and `stream()` method

**Files:**
- Modify: `backend/app/services/llm.py`
- Create: `backend/tests/unit/test_llm_streaming.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_llm_streaming.py`:

```python
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.llm import LLMError, LLMService, LLMStreamEnd, LLMToken


class FakeStreamChunk:
    """Simulates a single chunk from litellm.acompletion(stream=True)."""

    def __init__(self, content: str | None = None, *, usage: object | None = None, model: str | None = None) -> None:
        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=content))]
        self.usage = usage
        self.model = model


class FakeStreamResponse:
    """Simulates the async iterator returned by litellm.acompletion(stream=True)."""

    def __init__(self, chunks: list[FakeStreamChunk]) -> None:
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class FakeStreamingCompletion:
    def __init__(self, responses: list[FakeStreamResponse | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def __call__(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _make_service(completion: FakeStreamingCompletion) -> LLMService:
    return LLMService(
        model="openai/gpt-4o",
        api_key="sk-test",
        api_base=None,
        temperature=0.7,
        completion_func=completion,
    )


@pytest.mark.asyncio
async def test_stream_yields_tokens_and_end() -> None:
    stream = FakeStreamResponse([
        FakeStreamChunk(content="Hello"),
        FakeStreamChunk(content=" world"),
        FakeStreamChunk(
            content=None,
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
            model="openai/gpt-4o",
        ),
    ])
    completion = FakeStreamingCompletion([stream])
    service = _make_service(completion)

    events = [event async for event in service.stream([{"role": "user", "content": "Hi"}])]

    assert events == [
        LLMToken(content="Hello"),
        LLMToken(content=" world"),
        LLMStreamEnd(model_name="openai/gpt-4o", token_count_prompt=10, token_count_completion=5),
    ]


@pytest.mark.asyncio
async def test_stream_passes_stream_true_and_options() -> None:
    stream = FakeStreamResponse([FakeStreamChunk(content="ok")])
    completion = FakeStreamingCompletion([stream])
    service = _make_service(completion)

    _ = [event async for event in service.stream([{"role": "user", "content": "Hi"}])]

    call = completion.calls[0]
    assert call["stream"] is True
    assert call["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_stream_skips_empty_content_chunks() -> None:
    stream = FakeStreamResponse([
        FakeStreamChunk(content=None),
        FakeStreamChunk(content=""),
        FakeStreamChunk(content="token"),
    ])
    completion = FakeStreamingCompletion([stream])
    service = _make_service(completion)

    events = [event async for event in service.stream([{"role": "user", "content": "Hi"}])]

    token_events = [e for e in events if isinstance(e, LLMToken)]
    assert token_events == [LLMToken(content="token")]


@pytest.mark.asyncio
async def test_stream_raises_llm_error_on_provider_failure() -> None:
    completion = FakeStreamingCompletion([RuntimeError("provider down")])
    service = _make_service(completion)

    with pytest.raises(LLMError, match="LLM streaming failed"):
        _ = [event async for event in service.stream([{"role": "user", "content": "Hi"}])]


@pytest.mark.asyncio
async def test_stream_yields_end_with_none_usage_when_not_provided() -> None:
    stream = FakeStreamResponse([
        FakeStreamChunk(content="answer"),
    ])
    completion = FakeStreamingCompletion([stream])
    service = _make_service(completion)

    events = [event async for event in service.stream([{"role": "user", "content": "Hi"}])]

    end_events = [e for e in events if isinstance(e, LLMStreamEnd)]
    assert len(end_events) == 1
    assert end_events[0].token_count_prompt is None
    assert end_events[0].token_count_completion is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_llm_streaming.py -v`
Expected: FAIL — `ImportError: cannot import name 'LLMStreamEnd' from 'app.services.llm'`

- [ ] **Step 3: Implement stream types and method**

In `backend/app/services/llm.py`, add the dataclasses and method:

```python
# Add after LLMResponse dataclass:

@dataclass(slots=True, frozen=True)
class LLMToken:
    content: str


@dataclass(slots=True, frozen=True)
class LLMStreamEnd:
    model_name: str | None
    token_count_prompt: int | None
    token_count_completion: int | None


LLMStreamEvent = LLMToken | LLMStreamEnd
```

Add to `LLMService` class, after `complete()`:

```python
    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        try:
            response = await self._completion_func(
                model=self._model,
                messages=messages,
                temperature=self._temperature if temperature is None else temperature,
                api_key=self._api_key,
                base_url=self._api_base,
                stream=True,
                stream_options={"include_usage": True},
            )
        except Exception as error:
            self._logger.error("llm.stream_init_failed", model=self._model, error=str(error))
            raise LLMError("LLM streaming failed") from error

        model_name: str | None = None
        token_count_prompt: int | None = None
        token_count_completion: int | None = None

        try:
            async for chunk in response:
                delta_content = getattr(chunk.choices[0].delta, "content", None) if chunk.choices else None
                if delta_content:
                    yield LLMToken(content=delta_content)

                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage is not None:
                    token_count_prompt = getattr(chunk_usage, "prompt_tokens", None)
                    token_count_completion = getattr(chunk_usage, "completion_tokens", None)
                chunk_model = getattr(chunk, "model", None)
                if chunk_model is not None:
                    model_name = chunk_model
        except Exception as error:
            self._logger.error("llm.stream_read_failed", model=self._model, error=str(error))
            raise LLMError("LLM streaming failed") from error

        yield LLMStreamEnd(
            model_name=model_name,
            token_count_prompt=token_count_prompt,
            token_count_completion=token_count_completion,
        )
```

Add `AsyncIterator` to imports:

```python
from collections.abc import AsyncIterator, Awaitable, Callable
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/test_llm_streaming.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Run existing LLM tests to verify no regression**

Run: `cd backend && uv run pytest tests/unit/test_llm_service.py -v`
Expected: all 5 tests PASS

- [ ] **Step 6: Commit**

```
feat(llm): add streaming support via stream() method (S4-02)
```

---

## Task 6: ChatService streaming — domain events and `stream_answer()`

**Files:**
- Modify: `backend/app/services/chat.py`
- Create: `backend/tests/unit/test_chat_streaming.py`

This is the largest task. It covers:
- Domain event dataclasses (`ChatStreamMeta`, `ChatStreamToken`, `ChatStreamDone`, `ChatStreamError`)
- Idempotency check logic
- Session concurrency guard
- `stream_answer()` async generator
- Message state machine (STREAMING → COMPLETE/PARTIAL/FAILED)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_chat_streaming.py`:

```python
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import Message, Session
from app.db.models.enums import (
    MessageRole,
    MessageStatus,
    SessionChannel,
    SnapshotStatus,
)
from app.db.models.knowledge import KnowledgeSnapshot
from app.persona.loader import PersonaContext
from app.services.chat import (
    ChatService,
    ChatStreamDone,
    ChatStreamError,
    ChatStreamMeta,
    ChatStreamToken,
    ConcurrentStreamError,
    IdempotencyConflictError,
    NoActiveSnapshotError,
    SessionNotFoundError,
)
from app.services.llm import LLMError, LLMStreamEnd, LLMToken
from app.services.prompt import NO_CONTEXT_REFUSAL
from app.services.qdrant import RetrievedChunk
from app.services.snapshot import SnapshotService


async def _create_snapshot(
    db_session: AsyncSession,
    *,
    status: SnapshotStatus,
) -> KnowledgeSnapshot:
    snapshot = KnowledgeSnapshot(
        id=uuid.uuid7(),
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        name=f"Snapshot {status.value}",
        status=status,
    )
    db_session.add(snapshot)
    await db_session.commit()
    await db_session.refresh(snapshot)
    return snapshot


def _chunk(
    *,
    source_id: uuid.UUID | None = None,
    text_content: str = "retrieved chunk",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id or uuid.uuid4(),
        text_content=text_content,
        score=0.91,
        anchor_metadata={
            "anchor_page": None,
            "anchor_chapter": None,
            "anchor_section": None,
            "anchor_timecode": None,
        },
    )


async def _fake_stream(*tokens: str, model_name: str = "openai/gpt-4o"):
    """Helper: yields LLMToken events then LLMStreamEnd."""
    for token in tokens:
        yield LLMToken(content=token)
    yield LLMStreamEnd(
        model_name=model_name,
        token_count_prompt=10,
        token_count_completion=len(tokens),
    )


def _make_service(
    db_session: AsyncSession,
    *,
    persona_context: PersonaContext,
    retrieval_result: list[RetrievedChunk] | Exception | None = None,
    stream_tokens: tuple[str, ...] = ("Hello", " world"),
    stream_error: Exception | None = None,
    min_retrieved_chunks: int = 1,
) -> tuple[ChatService, SimpleNamespace, SimpleNamespace]:
    retrieval_service = SimpleNamespace(search=AsyncMock())
    if isinstance(retrieval_result, Exception):
        retrieval_service.search.side_effect = retrieval_result
    else:
        retrieval_service.search.return_value = retrieval_result or []

    llm_service = SimpleNamespace(
        complete=AsyncMock(),
        stream=AsyncMock(),
    )
    if stream_error:
        llm_service.stream.side_effect = stream_error
    else:
        llm_service.stream.return_value = _fake_stream(*stream_tokens)

    service = ChatService(
        session=db_session,
        snapshot_service=SnapshotService(session=db_session),
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        persona_context=persona_context,
        min_retrieved_chunks=min_retrieved_chunks,
    )
    return service, retrieval_service, llm_service


@pytest.fixture
def persona_context() -> PersonaContext:
    return PersonaContext(
        identity="Test identity",
        soul="Test soul",
        behavior="Test behavior",
        config_commit_hash="test-commit",
        config_content_hash="test-content-hash",
    )


async def _collect_events(service, **kwargs):
    """Collect all events from stream_answer."""
    return [event async for event in service.stream_answer(**kwargs)]


async def _message_rows(db_session: AsyncSession, session_id: uuid.UUID) -> list[Message]:
    return list(
        (
            await db_session.scalars(
                select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
            )
        ).all()
    )


@pytest.mark.asyncio
async def test_stream_answer_yields_meta_tokens_done(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    snapshot = await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk()],
        stream_tokens=("Hello", " world"),
    )
    session = await service.create_session()

    events = await _collect_events(service, session_id=session.id, text="Q?")

    assert isinstance(events[0], ChatStreamMeta)
    assert events[0].session_id == session.id
    assert events[0].snapshot_id == snapshot.id

    tokens = [e for e in events if isinstance(e, ChatStreamToken)]
    assert [t.content for t in tokens] == ["Hello", " world"]

    done = [e for e in events if isinstance(e, ChatStreamDone)]
    assert len(done) == 1
    assert done[0].model_name == "openai/gpt-4o"


@pytest.mark.asyncio
async def test_stream_answer_persists_complete_message(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    source_id = uuid.uuid4()
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk(source_id=source_id)],
        stream_tokens=("answer",),
    )
    session = await service.create_session()

    await _collect_events(service, session_id=session.id, text="Q?")

    messages = await _message_rows(db_session, session.id)
    assert len(messages) == 2
    assert messages[0].role is MessageRole.USER
    assert messages[0].status is MessageStatus.RECEIVED
    assert messages[1].role is MessageRole.ASSISTANT
    assert messages[1].status is MessageStatus.COMPLETE
    assert messages[1].content == "answer"
    assert messages[1].source_ids == [source_id]


@pytest.mark.asyncio
async def test_stream_answer_refusal_when_no_chunks(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, llm_service = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[],
    )
    session = await service.create_session()

    events = await _collect_events(service, session_id=session.id, text="Q?")

    tokens = [e for e in events if isinstance(e, ChatStreamToken)]
    combined = "".join(t.content for t in tokens)
    assert combined == NO_CONTEXT_REFUSAL
    llm_service.stream.assert_not_called()

    messages = await _message_rows(db_session, session.id)
    assert messages[1].status is MessageStatus.COMPLETE


@pytest.mark.asyncio
async def test_stream_answer_yields_error_on_llm_failure(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk()],
        stream_error=LLMError("boom"),
    )
    session = await service.create_session()

    events = await _collect_events(service, session_id=session.id, text="Q?")

    errors = [e for e in events if isinstance(e, ChatStreamError)]
    assert len(errors) == 1

    messages = await _message_rows(db_session, session.id)
    assert messages[1].status is MessageStatus.FAILED


@pytest.mark.asyncio
async def test_stream_answer_raises_for_missing_session(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    service, _, _ = _make_service(db_session, persona_context=persona_context)

    with pytest.raises(SessionNotFoundError):
        await _collect_events(service, session_id=uuid.uuid7(), text="Q?")


@pytest.mark.asyncio
async def test_stream_answer_raises_for_no_snapshot(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    service, _, _ = _make_service(db_session, persona_context=persona_context)
    session = await service.create_session()

    with pytest.raises(NoActiveSnapshotError):
        await _collect_events(service, session_id=session.id, text="Q?")


@pytest.mark.asyncio
async def test_stream_answer_idempotency_replays_complete(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk()],
        stream_tokens=("original",),
    )
    session = await service.create_session()

    # First call
    await _collect_events(
        service, session_id=session.id, text="Q?", idempotency_key="key-1"
    )

    # Second call with same key — should replay
    events = await _collect_events(
        service, session_id=session.id, text="Q?", idempotency_key="key-1"
    )

    meta = [e for e in events if isinstance(e, ChatStreamMeta)]
    tokens = [e for e in events if isinstance(e, ChatStreamToken)]
    done = [e for e in events if isinstance(e, ChatStreamDone)]
    assert len(meta) == 1
    assert len(tokens) == 1
    assert tokens[0].content == "original"
    assert len(done) == 1


@pytest.mark.asyncio
async def test_stream_answer_concurrent_stream_raises(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk()],
    )
    session = await service.create_session()

    # Simulate a STREAMING message already in the session
    streaming_msg = Message(
        id=uuid.uuid7(),
        session_id=session.id,
        role=MessageRole.ASSISTANT,
        content="",
        status=MessageStatus.STREAMING,
    )
    session.message_count += 1
    db_session.add(streaming_msg)
    await db_session.commit()

    with pytest.raises(ConcurrentStreamError):
        await _collect_events(service, session_id=session.id, text="Q?")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/test_chat_streaming.py -v`
Expected: FAIL — `ImportError: cannot import name 'ChatStreamMeta' from 'app.services.chat'`

- [ ] **Step 3: Implement domain events and `stream_answer()`**

In `backend/app/services/chat.py`, add the following:

**New imports at top:**
```python
from collections.abc import AsyncIterator
from app.services.llm import LLMError, LLMStreamEnd, LLMToken
```

**New exception classes (after existing ones):**
```python
class ConcurrentStreamError(RuntimeError):
    pass


class IdempotencyConflictError(RuntimeError):
    pass
```

**New domain event dataclasses (after ChatAnswerResult):**
```python
@dataclass(slots=True, frozen=True)
class ChatStreamMeta:
    message_id: uuid.UUID
    session_id: uuid.UUID
    snapshot_id: uuid.UUID | None


@dataclass(slots=True, frozen=True)
class ChatStreamToken:
    content: str


@dataclass(slots=True, frozen=True)
class ChatStreamDone:
    token_count_prompt: int | None
    token_count_completion: int | None
    model_name: str | None


@dataclass(slots=True, frozen=True)
class ChatStreamError:
    detail: str


ChatStreamEvent = ChatStreamMeta | ChatStreamToken | ChatStreamDone | ChatStreamError
```

**New methods in `ChatService` class:**

```python
    async def stream_answer(
        self,
        *,
        session_id: uuid.UUID,
        text: str,
        idempotency_key: str | None = None,
    ) -> AsyncIterator[ChatStreamEvent]:
        # --- Pre-stream checks (raise before any SSE output) ---
        chat_session = await self._load_session(session_id)
        snapshot_id = await self._ensure_snapshot_binding(chat_session)

        # Idempotency check
        if idempotency_key is not None:
            replay = await self._check_idempotency(chat_session, idempotency_key, snapshot_id)
            if replay is not None:
                async for event in replay:
                    yield event
                return

        # Concurrency guard
        await self._check_no_active_stream(chat_session)

        # Save user message
        user_msg = await self._persist_message(
            chat_session,
            role=MessageRole.USER,
            content=text,
            status=MessageStatus.RECEIVED,
            snapshot_id=snapshot_id,
            idempotency_key=idempotency_key,
        )

        # Retrieve chunks (errors raise — pre-stream, same as current answer())
        # On failure: persist FAILED assistant message then re-raise
        try:
            retrieved_chunks = await self._retrieval_service.search(text, snapshot_id=snapshot_id)
        except Exception as error:
            await self._persist_message(
                chat_session,
                role=MessageRole.ASSISTANT,
                content=FAILED_ASSISTANT_CONTENT,
                status=MessageStatus.FAILED,
                snapshot_id=snapshot_id,
                parent_message_id=user_msg.id,
            )
            raise

        # No-context refusal
        if len(retrieved_chunks) < self._min_retrieved_chunks:
            assistant_msg = await self._persist_message(
                chat_session,
                role=MessageRole.ASSISTANT,
                content=NO_CONTEXT_REFUSAL,
                status=MessageStatus.COMPLETE,
                snapshot_id=snapshot_id,
                source_ids=[],
            )
            yield ChatStreamMeta(
                message_id=assistant_msg.id,
                session_id=chat_session.id,
                snapshot_id=snapshot_id,
            )
            yield ChatStreamToken(content=NO_CONTEXT_REFUSAL)
            yield ChatStreamDone(
                token_count_prompt=None,
                token_count_completion=None,
                model_name=None,
            )
            return

        # Create STREAMING assistant message with explicit parent link
        source_ids = self._deduplicate_source_ids(retrieved_chunks)
        assistant_msg = await self._persist_message(
            chat_session,
            role=MessageRole.ASSISTANT,
            content="",
            status=MessageStatus.STREAMING,
            snapshot_id=snapshot_id,
            source_ids=source_ids,
            parent_message_id=user_msg.id,
        )

        yield ChatStreamMeta(
            message_id=assistant_msg.id,
            session_id=chat_session.id,
            snapshot_id=snapshot_id,
        )

        # Stream LLM
        content_buffer: list[str] = []
        try:
            prompt = build_chat_prompt(text, retrieved_chunks, self._persona_context)
            async for event in self._llm_service.stream(prompt):
                if isinstance(event, LLMToken):
                    content_buffer.append(event.content)
                    yield ChatStreamToken(content=event.content)
                elif isinstance(event, LLMStreamEnd):
                    full_content = "".join(content_buffer)
                    assistant_msg.content = full_content
                    assistant_msg.status = MessageStatus.COMPLETE
                    assistant_msg.model_name = event.model_name
                    assistant_msg.token_count_prompt = event.token_count_prompt
                    assistant_msg.token_count_completion = event.token_count_completion
                    assistant_msg.config_commit_hash = self._persona_context.config_commit_hash
                    assistant_msg.config_content_hash = self._persona_context.config_content_hash
                    await self._session.commit()
                    yield ChatStreamDone(
                        token_count_prompt=event.token_count_prompt,
                        token_count_completion=event.token_count_completion,
                        model_name=event.model_name,
                    )
        except (LLMError, Exception) as error:
            full_content = "".join(content_buffer)
            assistant_msg.content = full_content or FAILED_ASSISTANT_CONTENT
            assistant_msg.status = MessageStatus.FAILED
            await self._session.commit()
            self._logger.error(
                "chat.stream_failed",
                session_id=str(chat_session.id),
                error=str(error),
            )
            yield ChatStreamError(detail="LLM generation failed")

    async def save_partial_on_disconnect(
        self, assistant_message_id: uuid.UUID, accumulated_content: str
    ) -> None:
        """Called by the API layer when client disconnects mid-stream. Status → PARTIAL."""
        message = await self._session.get(Message, assistant_message_id)
        if message is not None and message.status is MessageStatus.STREAMING:
            message.content = accumulated_content or ""
            message.status = MessageStatus.PARTIAL
            await self._session.commit()

    async def save_failed_on_timeout(
        self, assistant_message_id: uuid.UUID, accumulated_content: str
    ) -> None:
        """Called by the API layer on inter-token timeout. Status → FAILED."""
        message = await self._session.get(Message, assistant_message_id)
        if message is not None and message.status is MessageStatus.STREAMING:
            message.content = accumulated_content or ""
            message.status = MessageStatus.FAILED
            await self._session.commit()

    async def _check_idempotency(
        self,
        chat_session: Session,
        idempotency_key: str,
        snapshot_id: uuid.UUID,
    ) -> AsyncIterator[ChatStreamEvent] | None:
        existing_user_msg = await self._session.scalar(
            select(Message).where(
                Message.session_id == chat_session.id,
                Message.idempotency_key == idempotency_key,
                Message.role == MessageRole.USER,
            )
        )
        if existing_user_msg is None:
            return None

        # Find paired assistant message via explicit parent_message_id link
        assistant_msg = await self._session.scalar(
            select(Message).where(
                Message.parent_message_id == existing_user_msg.id,
                Message.role == MessageRole.ASSISTANT,
            )
        )
        if assistant_msg is None:
            return None

        if assistant_msg.status is MessageStatus.STREAMING:
            raise IdempotencyConflictError("A stream is already in progress for this request")

        if assistant_msg.status is MessageStatus.COMPLETE:
            return self._replay_complete(assistant_msg, chat_session, snapshot_id)

        # PARTIAL or FAILED — allow re-generation
        return None

    async def _replay_complete(
        self,
        assistant_msg: Message,
        chat_session: Session,
        snapshot_id: uuid.UUID,
    ) -> AsyncIterator[ChatStreamEvent]:
        async def _replay():
            yield ChatStreamMeta(
                message_id=assistant_msg.id,
                session_id=chat_session.id,
                snapshot_id=snapshot_id,
            )
            yield ChatStreamToken(content=assistant_msg.content)
            yield ChatStreamDone(
                token_count_prompt=assistant_msg.token_count_prompt,
                token_count_completion=assistant_msg.token_count_completion,
                model_name=assistant_msg.model_name,
            )
        return _replay()

    async def _check_no_active_stream(self, chat_session: Session) -> None:
        streaming_msg = await self._session.scalar(
            select(Message).where(
                Message.session_id == chat_session.id,
                Message.status == MessageStatus.STREAMING,
            )
        )
        if streaming_msg is not None:
            raise ConcurrentStreamError("A stream is already active in this session")
```

Also update `_persist_message` to accept `idempotency_key`:

```python
    async def _persist_message(
        self,
        chat_session: Session,
        *,
        role: MessageRole,
        content: str,
        status: MessageStatus,
        snapshot_id: uuid.UUID | None,
        source_ids: list[uuid.UUID] | None = None,
        model_name: str | None = None,
        token_count_prompt: int | None = None,
        token_count_completion: int | None = None,
        idempotency_key: str | None = None,
        parent_message_id: uuid.UUID | None = None,
    ) -> Message:
        message = Message(
            id=uuid.uuid7(),
            session_id=chat_session.id,
            role=role,
            content=content,
            status=status,
            snapshot_id=snapshot_id,
            source_ids=source_ids,
            model_name=model_name,
            token_count_prompt=token_count_prompt,
            token_count_completion=token_count_completion,
            idempotency_key=idempotency_key,
            parent_message_id=parent_message_id,
        )
        chat_session.message_count += 1
        self._session.add(message)
        await self._session.commit()
        await self._session.refresh(message)
        return message
```

- [ ] **Step 4: Run streaming tests**

Run: `cd backend && uv run pytest tests/unit/test_chat_streaming.py -v`
Expected: all 8 tests PASS

- [ ] **Step 5: Run existing chat tests for regression**

Run: `cd backend && uv run pytest tests/unit/test_chat_service.py -v`
Expected: all tests PASS (existing `answer()` is unchanged)

- [ ] **Step 6: Commit**

```
feat(chat): add stream_answer() with domain events, idempotency, and concurrency guard (S4-02)
```

---

## Task 7: SSE endpoint — replace JSON with streaming

**Files:**
- Modify: `backend/app/api/chat.py`
- Modify: `backend/app/api/dependencies.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/integration/test_chat_sse.py`

- [ ] **Step 1: Write the failing integration tests**

Create `backend/tests/integration/test_chat_sse.py`:

```python
from __future__ import annotations

import json
import uuid

import httpx
import pytest
from httpx_sse import aconnect_sse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from unittest.mock import AsyncMock

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import Message
from app.db.models.enums import MessageRole, MessageStatus, SnapshotStatus
from app.db.models.knowledge import KnowledgeSnapshot


async def _create_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: SnapshotStatus,
) -> KnowledgeSnapshot:
    async with session_factory() as session:
        snapshot = KnowledgeSnapshot(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            name=f"Snapshot {status.value}",
            status=status,
        )
        session.add(snapshot)
        await session.commit()
        await session.refresh(snapshot)
        return snapshot


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_send_message_returns_sse_stream(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    mock_llm_service,
    sample_retrieved_chunk,
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]

    session_resp = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_resp.json()["id"]

    async with aconnect_sse(
        chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": session_id, "text": "Question?"},
    ) as event_source:
        events = [sse async for sse in event_source.aiter_sse()]

    event_types = [e.event for e in events]
    assert event_types[0] == "meta"
    assert "token" in event_types
    assert event_types[-1] == "done"

    meta_data = json.loads(events[0].data)
    assert "message_id" in meta_data
    assert meta_data["session_id"] == session_id


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_persists_messages_as_complete(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    mock_llm_service,
    sample_retrieved_chunk,
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]

    session_resp = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_resp.json()["id"]

    async with aconnect_sse(
        chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": session_id, "text": "Question?"},
    ) as event_source:
        _ = [sse async for sse in event_source.aiter_sse()]

    async with session_factory() as session:
        messages = list(
            (
                await session.scalars(
                    select(Message)
                    .where(Message.session_id == uuid.UUID(session_id))
                    .order_by(Message.created_at)
                )
            ).all()
        )
        assert len(messages) == 2
        assert messages[0].role is MessageRole.USER
        assert messages[0].status is MessageStatus.RECEIVED
        assert messages[1].role is MessageRole.ASSISTANT
        assert messages[1].status is MessageStatus.COMPLETE


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_returns_404_for_unknown_session(
    chat_client: httpx.AsyncClient,
) -> None:
    response = await chat_client.post(
        "/api/chat/messages",
        json={"session_id": str(uuid.uuid7()), "text": "Q?"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_returns_422_without_snapshot(
    chat_client: httpx.AsyncClient,
) -> None:
    session_resp = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_resp.json()["id"]

    response = await chat_client.post(
        "/api/chat/messages",
        json={"session_id": session_id, "text": "Q?"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_returns_409_for_concurrent_stream(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    mock_llm_service,
    sample_retrieved_chunk,
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]

    session_resp = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_resp.json()["id"]

    # Manually insert a STREAMING message to simulate in-progress stream
    async with session_factory() as session:
        msg = Message(
            id=uuid.uuid7(),
            session_id=uuid.UUID(session_id),
            role=MessageRole.ASSISTANT,
            content="",
            status=MessageStatus.STREAMING,
        )
        session.add(msg)
        await session.commit()

    response = await chat_client.post(
        "/api/chat/messages",
        json={"session_id": session_id, "text": "Q?"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_idempotency_replay(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    mock_llm_service,
    sample_retrieved_chunk,
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]

    session_resp = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_resp.json()["id"]

    # First request
    async with aconnect_sse(
        chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": session_id, "text": "Q?", "idempotency_key": "idem-1"},
    ) as event_source:
        first_events = [sse async for sse in event_source.aiter_sse()]

    # Replay with same key
    async with aconnect_sse(
        chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": session_id, "text": "Q?", "idempotency_key": "idem-1"},
    ) as event_source:
        replay_events = [sse async for sse in event_source.aiter_sse()]

    # Both should have meta + token(s) + done
    assert replay_events[0].event == "meta"
    assert replay_events[-1].event == "done"

    # Same message_id in both
    first_meta = json.loads(first_events[0].data)
    replay_meta = json.loads(replay_events[0].data)
    assert first_meta["message_id"] == replay_meta["message_id"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_saves_partial_on_early_disconnect(
    chat_app,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    mock_llm_service,
    sample_retrieved_chunk,
) -> None:
    """Simulate client disconnect by closing the connection after the first token."""
    import asyncio
    from app.services.llm import LLMStreamEnd, LLMToken

    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]

    # Use a slow stream that yields tokens with delays
    disconnect_event = asyncio.Event()

    async def _slow_stream(*args, **kwargs):
        yield LLMToken(content="partial")
        disconnect_event.set()
        # Simulate a long wait that will be cancelled by disconnect
        await asyncio.sleep(60)
        yield LLMToken(content=" content")
        yield LLMStreamEnd(model_name="openai/gpt-4o", token_count_prompt=5, token_count_completion=2)

    mock_llm_service.stream = AsyncMock(side_effect=_slow_stream)

    transport = httpx.ASGITransport(app=chat_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_resp = await client.post("/api/chat/sessions", json={})
        session_id = session_resp.json()["id"]

        # Start the stream request, consume some events, then cancel
        async with client.stream(
            "POST",
            "/api/chat/messages",
            json={"session_id": session_id, "text": "Q?"},
        ) as response:
            # Read until we get the first token
            await disconnect_event.wait()
            # Close the response (simulates disconnect)

    # Allow cleanup to happen
    await asyncio.sleep(0.1)

    # Verify the message was saved as PARTIAL
    async with session_factory() as session:
        messages = list(
            (
                await session.scalars(
                    select(Message)
                    .where(Message.session_id == uuid.UUID(session_id))
                    .where(Message.role == MessageRole.ASSISTANT)
                )
            ).all()
        )
        assert len(messages) == 1
        assert messages[0].status is MessageStatus.PARTIAL
        assert messages[0].content == "partial"
```

- [ ] **Step 2: Update conftest.py mock_llm_service with `stream` mock**

In `backend/tests/conftest.py`, update the `mock_llm_service` fixture:

```python
@pytest.fixture
def mock_llm_service() -> SimpleNamespace:
    from app.services.llm import LLMResponse, LLMStreamEnd, LLMToken

    async def _fake_stream(*args, **kwargs):
        yield LLMToken(content="Assistant")
        yield LLMToken(content=" answer")
        yield LLMStreamEnd(
            model_name="openai/gpt-4o",
            token_count_prompt=10,
            token_count_completion=5,
        )

    return SimpleNamespace(
        complete=AsyncMock(
            return_value=LLMResponse(
                content="Assistant answer",
                model_name="openai/gpt-4o",
                token_count_prompt=10,
                token_count_completion=5,
            )
        ),
        stream=AsyncMock(side_effect=_fake_stream),
    )
```

Also update the `chat_app` fixture settings to include SSE config:

```python
    app.state.settings = SimpleNamespace(
        min_retrieved_chunks=1,
        sse_heartbeat_interval_seconds=15,
        sse_inter_token_timeout_seconds=30,
    )
```

**Note on DB session lifecycle:** FastAPI async generator dependencies (`get_session`) remain alive until the response body is fully sent, including `StreamingResponse` generators. No special session handling is needed — the session factory's `async with` context stays open until the SSE generator is exhausted or the connection is closed.

- [ ] **Step 3: Add `get_sse_settings` dependency**

In `backend/app/api/dependencies.py`, add:

```python
def get_sse_settings(request: Request) -> dict:
    settings = request.app.state.settings
    return {
        "heartbeat_interval": settings.sse_heartbeat_interval_seconds,
        "inter_token_timeout": settings.sse_inter_token_timeout_seconds,
    }
```

- [ ] **Step 4: Rewrite the chat endpoint**

Replace `backend/app/api/chat.py` with the SSE implementation:

```python
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.api.chat_schemas import (
    CreateSessionRequest,
    SendMessageRequest,
    SessionResponse,
    SessionWithMessagesResponse,
)
from app.api.dependencies import get_chat_service, get_sse_settings
from app.services.chat import (
    ChatService,
    ChatStreamDone,
    ChatStreamError,
    ChatStreamMeta,
    ChatStreamToken,
    ConcurrentStreamError,
    IdempotencyConflictError,
    NoActiveSnapshotError,
    SessionNotFoundError,
)

router = APIRouter(prefix="/api/chat", tags=["chat"])

SSE_HEARTBEAT = ": heartbeat\n\n"


def _format_sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def _raise_chat_http_error(error: Exception) -> None:
    if isinstance(error, SessionNotFoundError):
        raise HTTPException(status_code=404, detail=str(error))
    if isinstance(error, NoActiveSnapshotError):
        raise HTTPException(status_code=422, detail=str(error))
    if isinstance(error, (ConcurrentStreamError, IdempotencyConflictError)):
        raise HTTPException(status_code=409, detail=str(error))
    raise error


@router.post(
    "/sessions",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    payload: CreateSessionRequest | None = Body(default=None),
) -> SessionResponse:
    session = await chat_service.create_session(
        channel=(payload or CreateSessionRequest()).channel
    )
    return SessionResponse.from_session(session)


@router.post("/messages")
async def send_message(
    request: Request,
    payload: SendMessageRequest,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
    sse_settings: Annotated[dict, Depends(get_sse_settings)],
) -> StreamingResponse:
    heartbeat_interval = sse_settings["heartbeat_interval"]
    inter_token_timeout = sse_settings["inter_token_timeout"]

    # Pre-stream validation: errors here return normal HTTP status codes
    try:
        event_stream = chat_service.stream_answer(
            session_id=payload.session_id,
            text=payload.text,
            idempotency_key=payload.idempotency_key,
        )
        # Advance to the first yield to trigger pre-stream checks
        # (session load, snapshot bind, idempotency, concurrency)
        first_event = await event_stream.__anext__()
    except (SessionNotFoundError, NoActiveSnapshotError, ConcurrentStreamError, IdempotencyConflictError) as error:
        _raise_chat_http_error(error)
    except StopAsyncIteration:
        raise HTTPException(status_code=500, detail="Empty stream")

    accumulated_content: list[str] = []
    assistant_message_id: uuid.UUID | None = None

    def _format_meta(meta: ChatStreamMeta) -> str:
        return _format_sse("meta", {
            "message_id": str(meta.message_id),
            "session_id": str(meta.session_id),
            "snapshot_id": str(meta.snapshot_id) if meta.snapshot_id else None,
        })

    def _handle_event(event: ChatStreamMeta | ChatStreamToken | ChatStreamDone | ChatStreamError) -> str | None:
        nonlocal assistant_message_id
        if isinstance(event, ChatStreamToken):
            accumulated_content.append(event.content)
            return _format_sse("token", {"content": event.content})
        if isinstance(event, ChatStreamDone):
            return _format_sse("done", {
                "token_count_prompt": event.token_count_prompt,
                "token_count_completion": event.token_count_completion,
                "model_name": event.model_name,
            })
        if isinstance(event, ChatStreamError):
            return _format_sse("error", {"detail": event.detail})
        if isinstance(event, ChatStreamMeta):
            assistant_message_id = event.message_id
            return _format_meta(event)
        return None

    async def _generate():
        nonlocal assistant_message_id

        # Yield the first event we already consumed
        if isinstance(first_event, ChatStreamMeta):
            assistant_message_id = first_event.message_id
            yield _format_meta(first_event)

        aiter = event_stream.__aiter__()
        deadline = time.monotonic() + inter_token_timeout

        try:
            while True:
                wait_time = min(heartbeat_interval, deadline - time.monotonic())
                if wait_time <= 0:
                    # Inter-token timeout exceeded → FAILED (not PARTIAL)
                    yield _format_sse("error", {"detail": "LLM response timed out"})
                    if assistant_message_id is not None:
                        await chat_service.save_failed_on_timeout(
                            assistant_message_id, "".join(accumulated_content)
                        )
                    return

                try:
                    event = await asyncio.wait_for(aiter.__anext__(), timeout=wait_time)
                except TimeoutError:
                    # Heartbeat: waited heartbeat_interval without an event
                    yield SSE_HEARTBEAT
                    continue
                except StopAsyncIteration:
                    break

                # Reset deadline on each received event
                deadline = time.monotonic() + inter_token_timeout

                sse_line = _handle_event(event)
                if sse_line is not None:
                    yield sse_line

        except asyncio.CancelledError:
            # Client disconnected — save partial content
            if assistant_message_id is not None:
                await chat_service.save_partial_on_disconnect(
                    assistant_message_id, "".join(accumulated_content)
                )
            raise

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions/{session_id}", response_model=SessionWithMessagesResponse)
async def get_session(
    session_id: uuid.UUID,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> SessionWithMessagesResponse:
    try:
        session = await chat_service.get_session(session_id)
    except Exception as error:
        _raise_chat_http_error(error)

    return SessionWithMessagesResponse.from_session(session)
```

- [ ] **Step 5: Run new SSE integration tests**

Run: `cd backend && uv run pytest tests/integration/test_chat_sse.py -v`
Expected: all 7 tests PASS

- [ ] **Step 6: Run existing integration tests to check for regressions**

Run: `cd backend && uv run pytest tests/integration/test_chat_api.py -v`
Expected: Some tests may need updating since `POST /messages` now returns SSE instead of JSON. Update the tests that directly check `response.json()` to use SSE parsing instead. The tests for session creation and get_session should still pass since those endpoints are unchanged.

**Expected updates to `test_chat_api.py`:**
- `test_send_message_returns_assistant_response` → must use `aconnect_sse` instead of `response.json()`
- `test_lazy_bind_e2e_create_before_publish_send_after` → same SSE update
- `test_persona_content_reaches_llm_prompt` → same SSE update
- `test_send_message_returns_422_without_snapshot` → should still work (pre-stream error)
- `test_send_message_returns_404_for_unknown_session` → should still work
- `test_send_message_returns_422_for_empty_or_missing_text` → should still work

Update the affected tests to use SSE. Keep the same assertions but via SSE event parsing.

- [ ] **Step 7: Run full test suite**

Run: `cd backend && uv run pytest -v`
Expected: all tests PASS

- [ ] **Step 8: Commit**

```
feat(chat): replace JSON response with SSE streaming endpoint (S4-02)

POST /api/chat/messages now returns text/event-stream with events:
meta (message_id, session_id, snapshot_id), token (content),
done (usage stats), error (detail).

Pre-stream errors (404, 409, 422) still return standard HTTP codes.
Idempotency key replays complete responses. Concurrent streams per
session are rejected with 409.
```

---

## Task 8: Update existing chat integration tests for SSE

**Files:**
- Modify: `backend/tests/integration/test_chat_api.py`
- Modify: `backend/tests/conftest.py` (if not already updated in Task 7)

This task has a wider blast radius than it appears. Key changes:

1. **`test_send_message_returns_assistant_response`** — was checking `response.json()["content"]`, `["status"]`, `["model_name"]`, `["retrieved_chunks_count"]`. Must switch to SSE parsing. The `retrieved_chunks_count` field is no longer in the response — it was a JSON-only convenience; SSE doesn't include it. Verify persistence via DB query instead.

2. **`test_persona_content_reaches_llm_prompt`** — currently checks `mock_llm_service.complete.call_args`. After SSE, the service calls `stream()` not `complete()`. Must check `mock_llm_service.stream.call_args` instead.

3. **`test_lazy_bind_e2e_create_before_publish_send_after`** — must switch to SSE parsing. DB assertions remain the same.

4. **Tests checking HTTP error codes (404, 422)** — these should still work since pre-stream errors return normal HTTP responses. Verify they pass as-is.

- [ ] **Step 1: Update tests that call POST /messages**

The tests that check `response.json()` after sending a message must be updated to parse SSE events instead. Tests for session endpoints remain unchanged.

**Pattern for response assertions:**
```python
# Old pattern:
response = await chat_client.post("/api/chat/messages", json={...})
body = response.json()
assert body["content"] == "..."

# New pattern:
async with aconnect_sse(chat_client, "POST", "/api/chat/messages", json={...}) as event_source:
    events = [sse async for sse in event_source.aiter_sse()]
tokens = [json.loads(e.data)["content"] for e in events if e.event == "token"]
full_content = "".join(tokens)
assert full_content == "..."
```

**Pattern for prompt verification:**
```python
# Old: mock_llm_service.complete.call_args.args[0]
# New: mock_llm_service.stream.call_args.args[0]
```

- [ ] **Step 2: Run updated tests**

Run: `cd backend && uv run pytest tests/integration/test_chat_api.py -v`
Expected: all tests PASS

- [ ] **Step 3: Run full test suite**

Run: `cd backend && uv run pytest -v`
Expected: all tests PASS

- [ ] **Step 4: Commit**

```
test(chat): update integration tests for SSE streaming (S4-02)
```

---

## Task 9: Lint, final verification, and cleanup

**Files:** all modified files

- [ ] **Step 1: Run linter**

Run: `cd backend && uv run ruff check . --fix && uv run ruff format .`
Expected: no errors

- [ ] **Step 2: Run full test suite one final time**

Run: `cd backend && uv run pytest -v`
Expected: all tests PASS

- [ ] **Step 3: Self-review against development standards**

Re-read `docs/development.md` and verify:
- No mocks outside `tests/`
- No fallbacks to stubs
- All new code follows SOLID, KISS, DRY, YAGNI
- Functions are short and do one thing
- Each file under ~300 lines

- [ ] **Step 4: Commit any lint/formatting fixes**

```
chore: lint and format after S4-02 SSE streaming
```
