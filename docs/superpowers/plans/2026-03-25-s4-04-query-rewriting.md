# S4-04: Query Rewriting — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add LLM-based query rewriting to the chat pipeline so multi-turn queries like "tell me more" are reformulated into self-contained search queries before retrieval.

**Architecture:** A new `QueryRewriteService` calls `LLMService.complete()` with conversation history + current query to produce a self-contained search query. This happens between user message persistence and retrieval in `ChatService.stream_answer()`. Fail-open on any error — retrieval proceeds with the original query. Rewritten query is persisted in a new `rewritten_query` column on the `messages` table.

**Tech Stack:** Python, FastAPI, SQLAlchemy, Alembic, LiteLLM, structlog, pytest

**Spec:** `docs/superpowers/specs/2026-03-25-s4-04-query-rewriting-design.md`

**Dev standards:** `docs/development.md` — read before writing code, self-review after.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `backend/app/core/config.py` | Add 8 rewrite settings |
| Create | `backend/app/services/query_rewrite.py` | `QueryRewriteService`: rewrite prompt, token budget trimming, timeout, fail-open |
| Modify | `backend/app/db/models/dialogue.py` | Add `rewritten_query` column to `Message` |
| Create | `backend/migrations/versions/008_add_rewritten_query_to_messages.py` | Alembic migration |
| Modify | `backend/app/main.py` | Initialize `QueryRewriteService` (+ optional dedicated `LLMService`) in lifespan |
| Modify | `backend/app/api/dependencies.py` | Wire `QueryRewriteService` into `get_chat_service()` |
| Modify | `backend/app/services/chat.py` | Insert rewrite step before retrieval in `stream_answer()` and `answer()` |
| Modify | `backend/tests/conftest.py` | Add rewrite settings to `chat_app` fixture, add `mock_rewrite_service` fixture |
| Modify | `backend/tests/unit/test_chat_service.py` | Pass `query_rewrite_service` to `ChatService` in `_make_service` helper |
| Modify | `backend/tests/unit/test_chat_streaming.py` | Pass `query_rewrite_service` to `ChatService` in `_make_service` helper |
| Create | `backend/tests/unit/test_query_rewrite.py` | Unit tests for `QueryRewriteService` |
| Modify | `backend/tests/integration/test_chat_sse.py` | Integration tests: rewrite persistence and retrieval-with-rewritten-query |

---

## Task 1: Add rewrite settings to config

**Files:**
- Modify: `backend/app/core/config.py:46-57`
- Test: `backend/tests/unit/test_config.py`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/unit/test_config.py`:

```python
def test_rewrite_settings_defaults() -> None:
    settings = Settings(**_base_settings())

    assert settings.rewrite_enabled is True
    assert settings.rewrite_llm_model is None
    assert settings.rewrite_llm_api_key is None
    assert settings.rewrite_llm_api_base is None
    assert settings.rewrite_temperature == 0.1
    assert settings.rewrite_timeout_ms == 3000
    assert settings.rewrite_token_budget == 2048
    assert settings.rewrite_history_messages == 10


def test_rewrite_settings_custom() -> None:
    settings = Settings(
        **_base_settings(),
        rewrite_enabled=False,
        rewrite_llm_model="gemini/gemini-2.0-flash",
        rewrite_temperature=0.0,
        rewrite_timeout_ms=5000,
        rewrite_token_budget=1024,
        rewrite_history_messages=5,
    )

    assert settings.rewrite_enabled is False
    assert settings.rewrite_llm_model == "gemini/gemini-2.0-flash"
    assert settings.rewrite_temperature == 0.0
    assert settings.rewrite_timeout_ms == 5000
    assert settings.rewrite_token_budget == 1024
    assert settings.rewrite_history_messages == 5


def test_rewrite_timeout_rejects_non_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(**_base_settings(), rewrite_timeout_ms=0)


def test_rewrite_token_budget_rejects_non_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(**_base_settings(), rewrite_token_budget=0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_config.py::test_rewrite_settings_defaults -v`
Expected: FAIL — `rewrite_enabled` not in Settings

- [ ] **Step 3: Write minimal implementation**

In `backend/app/core/config.py`, add after line 55 (`sse_inter_token_timeout_seconds`):

```python
    rewrite_enabled: bool = Field(default=True)
    rewrite_llm_model: str | None = Field(default=None)
    rewrite_llm_api_key: str | None = Field(default=None)
    rewrite_llm_api_base: str | None = Field(default=None)
    rewrite_temperature: float = Field(default=0.1, ge=0.0, le=2.0)
    rewrite_timeout_ms: int = Field(default=3000, ge=1)
    rewrite_token_budget: int = Field(default=2048, ge=1)
    rewrite_history_messages: int = Field(default=10, ge=1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_config.py -v`
Expected: ALL PASS

- [ ] **Step 5: Propose commit**

Suggested message: `feat(config): add query rewriting settings (S4-04)`
Files: `backend/app/core/config.py`, `backend/tests/unit/test_config.py`
**Do NOT commit without explicit user permission** (see CLAUDE.md Git Policy).

---

## Task 2: Add `rewritten_query` column to Message model + migration

**Files:**
- Modify: `backend/app/db/models/dialogue.py:95`
- Create: `backend/migrations/versions/008_add_rewritten_query_to_messages.py`

- [ ] **Step 1: Add column to SQLAlchemy model**

In `backend/app/db/models/dialogue.py`, add after line 95 (`config_content_hash`):

```python
    rewritten_query: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 2: Create Alembic migration**

Create `backend/migrations/versions/008_add_rewritten_query_to_messages.py`:

```python
"""add_rewritten_query_to_messages

Revision ID: 008
Revises: 007
Create Date: 2026-03-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "008"
down_revision: str | Sequence[str] | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("rewritten_query", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "rewritten_query")
```

- [ ] **Step 3: Verify migration applies**

Run: `cd backend && alembic upgrade head`
Expected: migration 008 applies successfully

- [ ] **Step 4: Run existing tests to ensure no regressions**

Run: `cd backend && python -m pytest tests/ -x -q`
Expected: ALL PASS

- [ ] **Step 5: Propose commit**

Suggested message: `feat(db): add rewritten_query column to messages (S4-04)`
Files: `backend/app/db/models/dialogue.py`, `backend/migrations/versions/008_add_rewritten_query_to_messages.py`
**Do NOT commit without explicit user permission.**

---

## Task 3: Create `QueryRewriteService`

**Files:**
- Create: `backend/app/services/query_rewrite.py`
- Create: `backend/tests/unit/test_query_rewrite.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/unit/test_query_rewrite.py`:

```python
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.llm_types import LLMResponse
from app.services.query_rewrite import QueryRewriteService, RewriteResult


def _make_message(role: str, content: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid7(),
        role=SimpleNamespace(value=role),
        content=content,
    )


def _make_service(
    *,
    llm_complete_return: str = "rewritten query",
    llm_complete_side_effect: Exception | None = None,
    rewrite_enabled: bool = True,
    timeout_ms: int = 3000,
    token_budget: int = 2048,
    history_messages: int = 10,
) -> tuple[QueryRewriteService, AsyncMock]:
    mock_complete = AsyncMock()
    if llm_complete_side_effect is not None:
        mock_complete.side_effect = llm_complete_side_effect
    else:
        mock_complete.return_value = LLMResponse(
            content=llm_complete_return,
            model_name="test-model",
            token_count_prompt=10,
            token_count_completion=5,
        )

    llm_service = SimpleNamespace(complete=mock_complete)

    service = QueryRewriteService(
        llm_service=llm_service,
        rewrite_enabled=rewrite_enabled,
        timeout_ms=timeout_ms,
        token_budget=token_budget,
        history_messages=history_messages,
        temperature=0.1,
    )
    return service, mock_complete


@pytest.mark.asyncio
async def test_rewrite_with_history() -> None:
    service, mock_complete = _make_service(llm_complete_return="full question about AI")
    history = [
        _make_message("user", "What do you know about AI?"),
        _make_message("assistant", "I know a lot about AI."),
    ]

    result = await service.rewrite("tell me more", history, session_id="test-session")

    assert result.query == "full question about AI"
    assert result.is_rewritten is True
    assert result.original_query == "tell me more"
    mock_complete.assert_called_once()


@pytest.mark.asyncio
async def test_rewrite_skip_empty_history() -> None:
    service, mock_complete = _make_service()

    result = await service.rewrite("what is AI?", [], session_id="test-session")

    assert result.query == "what is AI?"
    assert result.is_rewritten is False
    mock_complete.assert_not_called()


@pytest.mark.asyncio
async def test_rewrite_skip_when_disabled() -> None:
    service, mock_complete = _make_service(rewrite_enabled=False)
    history = [_make_message("user", "hi"), _make_message("assistant", "hello")]

    result = await service.rewrite("tell me more", history)

    assert result.query == "tell me more"
    assert result.is_rewritten is False
    mock_complete.assert_not_called()


@pytest.mark.asyncio
async def test_rewrite_timeout_fallback() -> None:
    async def _slow_complete(*args, **kwargs):
        await asyncio.sleep(10)

    service, _ = _make_service(timeout_ms=50)
    service._llm_service.complete = _slow_complete
    history = [_make_message("user", "hi"), _make_message("assistant", "hello")]

    result = await service.rewrite("tell me more", history)

    assert result.query == "tell me more"
    assert result.is_rewritten is False


@pytest.mark.asyncio
async def test_rewrite_error_fallback() -> None:
    service, _ = _make_service(llm_complete_side_effect=RuntimeError("LLM down"))
    history = [_make_message("user", "hi"), _make_message("assistant", "hello")]

    result = await service.rewrite("tell me more", history)

    assert result.query == "tell me more"
    assert result.is_rewritten is False


@pytest.mark.asyncio
async def test_rewrite_empty_response_fallback() -> None:
    service, _ = _make_service(llm_complete_return="   ")
    history = [_make_message("user", "hi"), _make_message("assistant", "hello")]

    result = await service.rewrite("tell me more", history)

    assert result.query == "tell me more"
    assert result.is_rewritten is False


@pytest.mark.asyncio
async def test_token_budget_trimming() -> None:
    # Budget = 500 tokens. SYSTEM_PROMPT_RESERVE = 200. Query "tell me more" ≈ 4 tokens.
    # Available ≈ 500 - 200 - 4 = 296 tokens.
    # With CHARS_PER_TOKEN=3: 600 chars ≈ 200 tokens, 60 chars ≈ 20 tokens.
    # Walking backwards: D(20) + C(20) = 40 → fits. B(200) → 240 → fits. A(200) → 440 → exceeds 296.
    # So only B, C, D should be included; A should be trimmed.
    service, mock_complete = _make_service(token_budget=500)
    long_history = [
        _make_message("user", "A" * 600),       # oldest — should be trimmed
        _make_message("assistant", "B" * 600),   # fits
        _make_message("user", "C" * 60),         # fits
        _make_message("assistant", "D" * 60),    # fits (most recent)
    ]

    result = await service.rewrite("tell me more", long_history)

    assert result.is_rewritten is True
    mock_complete.assert_called_once()
    call_messages = mock_complete.call_args[0][0]
    user_content = call_messages[1]["content"]
    # Oldest long message should be trimmed
    assert "A" * 600 not in user_content
    # Recent messages should be present
    assert "C" * 60 in user_content
    assert "D" * 60 in user_content


@pytest.mark.asyncio
async def test_history_messages_cap() -> None:
    service, mock_complete = _make_service(history_messages=2)
    history = [
        _make_message("user", "first"),
        _make_message("assistant", "first reply"),
        _make_message("user", "second"),
        _make_message("assistant", "second reply"),
        _make_message("user", "third"),
        _make_message("assistant", "third reply"),
    ]

    result = await service.rewrite("fourth", history)

    assert result.is_rewritten is True
    mock_complete.assert_called_once()
    call_messages = mock_complete.call_args[0][0]
    user_content = call_messages[1]["content"]
    # Only last 2 messages should be in the prompt
    assert "first" not in user_content
    assert "second" not in user_content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_query_rewrite.py -v`
Expected: FAIL — `app.services.query_rewrite` module not found

- [ ] **Step 3: Write the implementation**

Create `backend/app/services/query_rewrite.py`:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import structlog

if TYPE_CHECKING:
    from app.services.llm import LLMService

CHARS_PER_TOKEN = 3  # Conservative estimate for multilingual safety (CJK ≈ 1-2 chars/token)
SYSTEM_PROMPT_RESERVE_TOKENS = 200

REWRITE_SYSTEM_PROMPT = (
    "You are a query rewriting assistant. Given a conversation history and "
    "the user's latest message, reformulate the latest message into a "
    "self-contained search query that captures the full intent.\n\n"
    "Rules:\n"
    "- Output ONLY the rewritten query, nothing else\n"
    "- If the message is already self-contained, return it as-is\n"
    "- Preserve the language of the original query\n"
    "- Do not answer the question, only reformulate it\n"
    "- Include relevant context from the conversation history"
)


class MessageLike(Protocol):
    @property
    def role(self) -> Any: ...
    @property
    def content(self) -> str: ...


@dataclass(slots=True, frozen=True)
class RewriteResult:
    query: str
    is_rewritten: bool
    original_query: str


class QueryRewriteService:
    def __init__(
        self,
        *,
        llm_service: LLMService,
        rewrite_enabled: bool = True,
        timeout_ms: int = 3000,
        token_budget: int = 2048,
        history_messages: int = 10,
        temperature: float = 0.1,
    ) -> None:
        self._llm_service = llm_service
        self._rewrite_enabled = rewrite_enabled
        self._timeout_ms = timeout_ms
        self._token_budget = token_budget
        self._history_messages = history_messages
        self._temperature = temperature
        self._logger = structlog.get_logger(__name__)

    async def rewrite(
        self,
        query: str,
        history: list[MessageLike],
        *,
        session_id: str | None = None,
    ) -> RewriteResult:
        no_rewrite = RewriteResult(
            query=query,
            is_rewritten=False,
            original_query=query,
        )

        if not self._rewrite_enabled:
            self._logger.debug("query_rewrite.skip", reason="disabled", session_id=session_id)
            return no_rewrite

        if not history:
            self._logger.debug("query_rewrite.skip", reason="empty_history", session_id=session_id)
            return no_rewrite

        trimmed = self._trim_history(history, query)
        prompt = self._build_prompt(trimmed, query)

        start = asyncio.get_event_loop().time()
        try:
            response = await asyncio.wait_for(
                self._llm_service.complete(prompt, temperature=self._temperature),
                timeout=self._timeout_ms / 1000,
            )
            rewritten = response.content.strip()
            if not rewritten:
                self._logger.warning(
                    "query_rewrite.error",
                    error="empty response",
                    session_id=session_id,
                )
                return no_rewrite

            elapsed_ms = round((asyncio.get_event_loop().time() - start) * 1000)
            self._logger.info(
                "query_rewrite.success",
                history_messages=len(trimmed),
                latency_ms=elapsed_ms,
                session_id=session_id,
            )
            return RewriteResult(
                query=rewritten,
                is_rewritten=True,
                original_query=query,
            )
        except asyncio.TimeoutError:
            self._logger.warning(
                "query_rewrite.timeout",
                timeout_ms=self._timeout_ms,
                session_id=session_id,
            )
            return no_rewrite
        except Exception as error:
            self._logger.warning(
                "query_rewrite.error",
                error=str(error),
                session_id=session_id,
            )
            return no_rewrite

    def _trim_history(
        self,
        history: list[MessageLike],
        query: str,
    ) -> list[MessageLike]:
        # Cap by message count first (take most recent)
        capped = history[-self._history_messages :]

        # Then trim by token budget (most recent messages that fit)
        query_tokens = len(query) / CHARS_PER_TOKEN
        available = self._token_budget - SYSTEM_PROMPT_RESERVE_TOKENS - query_tokens
        if available <= 0:
            return []

        result: list[MessageLike] = []
        token_sum = 0.0
        # Walk backwards from most recent
        for msg in reversed(capped):
            msg_tokens = len(msg.content) / CHARS_PER_TOKEN
            if token_sum + msg_tokens > available:
                break
            result.append(msg)
            token_sum += msg_tokens

        result.reverse()
        return result

    @staticmethod
    def _build_prompt(
        history: list[MessageLike],
        query: str,
    ) -> list[dict[str, str]]:
        history_lines: list[str] = []
        for msg in history:
            role_label = msg.role.value.capitalize()
            history_lines.append(f"{role_label}: {msg.content}")

        user_content = (
            "Conversation history:\n"
            + "\n".join(history_lines)
            + f"\n\nCurrent message: {query}"
        )

        return [
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_query_rewrite.py -v`
Expected: ALL PASS

- [ ] **Step 5: Propose commit**

Suggested message: `feat(query-rewrite): add QueryRewriteService with fail-open and token budget (S4-04)`
Files: `backend/app/services/query_rewrite.py`, `backend/tests/unit/test_query_rewrite.py`
**Do NOT commit without explicit user permission.**

---

## Task 4: Initialize `QueryRewriteService` in lifespan and wire DI

**Files:**
- Modify: `backend/app/main.py:54-62,117`
- Modify: `backend/app/api/dependencies.py:90-108`
- Modify: `backend/app/services/chat.py:94-113`
- Modify: `backend/tests/conftest.py:287-313`

- [ ] **Step 1: Add factory function in `main.py`**

In `backend/app/main.py`, add after the `_create_llm_service` function (after line 62):

```python
def _create_query_rewrite_service(settings, llm_service):
    from app.services.query_rewrite import QueryRewriteService

    if settings.rewrite_llm_model is not None:
        from app.services.llm import LLMService

        rewrite_llm = LLMService(
            model=settings.rewrite_llm_model,
            api_key=settings.rewrite_llm_api_key or settings.llm_api_key,
            api_base=settings.rewrite_llm_api_base or settings.llm_api_base,
            temperature=settings.rewrite_temperature,
        )
    else:
        rewrite_llm = llm_service

    return QueryRewriteService(
        llm_service=rewrite_llm,
        rewrite_enabled=settings.rewrite_enabled,
        timeout_ms=settings.rewrite_timeout_ms,
        token_budget=settings.rewrite_token_budget,
        history_messages=settings.rewrite_history_messages,
        temperature=settings.rewrite_temperature,
    )
```

- [ ] **Step 2: Initialize in lifespan**

In `backend/app/main.py` lifespan function, add after `app.state.llm_service = _create_llm_service(settings)` (line 117):

```python
        app.state.query_rewrite_service = _create_query_rewrite_service(
            settings,
            app.state.llm_service,
        )
```

- [ ] **Step 3: Add DI getter and wire into `get_chat_service`**

In `backend/app/api/dependencies.py`, add after `get_llm_service` (after line 71):

```python
def get_query_rewrite_service(request: Request):
    return request.app.state.query_rewrite_service
```

Update `get_chat_service` to accept and pass the rewrite service:

```python
def get_chat_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    retrieval_service: Annotated[RetrievalService, Depends(get_retrieval_service)],
    llm_service: Annotated[LLMService, Depends(get_llm_service)],
    persona_context: Annotated[PersonaContext, Depends(get_persona_context)],
) -> ChatService:
    from app.services.chat import ChatService

    return ChatService(
        session=session,
        snapshot_service=snapshot_service,
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        persona_context=persona_context,
        query_rewrite_service=request.app.state.query_rewrite_service,
        min_retrieved_chunks=request.app.state.settings.min_retrieved_chunks,
        max_citations_per_response=request.app.state.settings.max_citations_per_response,
    )
```

- [ ] **Step 4: Update `ChatService.__init__` to accept `query_rewrite_service`**

In `backend/app/services/chat.py`, update the `__init__` signature. Add import at top:

```python
if TYPE_CHECKING:
    from app.services.llm import LLMService
    from app.services.query_rewrite import QueryRewriteService
    from app.services.retrieval import RetrievalService
    from app.services.snapshot import SnapshotService
```

Update `__init__`:

```python
    def __init__(
        self,
        *,
        session: AsyncSession,
        snapshot_service: SnapshotService,
        retrieval_service: RetrievalService,
        llm_service: LLMService,
        persona_context: PersonaContext,
        query_rewrite_service: QueryRewriteService,
        min_retrieved_chunks: int,
        max_citations_per_response: int = 5,
    ) -> None:
        self._session = session
        self._snapshot_service = snapshot_service
        self._retrieval_service = retrieval_service
        self._llm_service = llm_service
        self._persona_context = persona_context
        self._query_rewrite_service = query_rewrite_service
        self._min_retrieved_chunks = min_retrieved_chunks
        self._max_citations_per_response = max_citations_per_response
        self._logger = structlog.get_logger(__name__)
```

- [ ] **Step 5: Update test fixtures**

In `backend/tests/conftest.py`, add a `mock_rewrite_service` fixture and wire it into `chat_app`:

```python
@pytest.fixture
def mock_rewrite_service() -> SimpleNamespace:
    from app.services.query_rewrite import RewriteResult

    async def _no_rewrite(query, history):
        return RewriteResult(query=query, is_rewritten=False, original_query=query)

    return SimpleNamespace(rewrite=AsyncMock(side_effect=_no_rewrite))
```

Update `chat_app` fixture to accept `mock_rewrite_service` and set `app.state.query_rewrite_service`:

```python
@pytest.fixture
def chat_app(
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service: SimpleNamespace,
    mock_llm_service: SimpleNamespace,
    mock_rewrite_service: SimpleNamespace,
) -> FastAPI:
    from app.api.chat import router as chat_router
    from app.persona.loader import PersonaContext

    app = FastAPI()
    app.include_router(chat_router)
    app.state.settings = SimpleNamespace(
        min_retrieved_chunks=1,
        max_citations_per_response=5,
        sse_heartbeat_interval_seconds=15,
        sse_inter_token_timeout_seconds=30,
    )
    app.state.session_factory = session_factory
    app.state.retrieval_service = mock_retrieval_service
    app.state.llm_service = mock_llm_service
    app.state.query_rewrite_service = mock_rewrite_service
    app.state.persona_context = PersonaContext(
        identity="Test twin identity",
        soul="Test twin soul",
        behavior="Test twin behavior",
        config_commit_hash="test-commit-sha",
        config_content_hash="test-content-hash",
    )
    return app
```

- [ ] **Step 6: Update existing unit tests that construct `ChatService` directly**

The `ChatService.__init__` signature now requires `query_rewrite_service`. Two existing test files construct `ChatService` via helper functions and must be updated.

In `backend/tests/unit/test_chat_service.py`, update the `_make_service` function (line ~88) to pass `query_rewrite_service`:

```python
from app.services.query_rewrite import RewriteResult

# Add inside _make_service, before the ChatService constructor:
    async def _no_rewrite(query, history, **kwargs):
        return RewriteResult(query=query, is_rewritten=False, original_query=query)

    rewrite_service = SimpleNamespace(rewrite=AsyncMock(side_effect=_no_rewrite))

    service = ChatService(
        session=db_session,
        snapshot_service=SnapshotService(session=db_session),
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        persona_context=persona_context,
        query_rewrite_service=rewrite_service,
        min_retrieved_chunks=min_retrieved_chunks,
    )
```

In `backend/tests/unit/test_chat_streaming.py`, update the `_make_service` function (line ~108) the same way:

```python
from app.services.query_rewrite import RewriteResult

# Add inside _make_service, before the ChatService constructor:
    async def _no_rewrite(query, history, **kwargs):
        return RewriteResult(query=query, is_rewritten=False, original_query=query)

    rewrite_service = SimpleNamespace(rewrite=AsyncMock(side_effect=_no_rewrite))

    service = ChatService(
        session=db_session,
        snapshot_service=SnapshotService(session=db_session),
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        persona_context=persona_context,
        query_rewrite_service=rewrite_service,
        min_retrieved_chunks=min_retrieved_chunks,
        max_citations_per_response=max_citations_per_response,
    )
```

- [ ] **Step 7: Run all tests to verify no regressions**

Run: `cd backend && python -m pytest tests/ -x -q`
Expected: ALL PASS

- [ ] **Step 8: Propose commit**

Suggested message: `feat(di): wire QueryRewriteService into chat pipeline (S4-04)`
Files: `backend/app/main.py`, `backend/app/api/dependencies.py`, `backend/app/services/chat.py`, `backend/tests/conftest.py`, `backend/tests/unit/test_chat_service.py`, `backend/tests/unit/test_chat_streaming.py`
**Do NOT commit without explicit user permission.**

---

## Task 5: Integrate query rewriting into `ChatService.stream_answer()` and `answer()`

Both methods get the same rewrite logic. `stream_answer()` is the primary SSE path; `answer()` is the non-streaming path used for API completeness (both are part of the runtime contract). The shared `_do_rewrite()` helper avoids duplication.

**Files:**
- Modify: `backend/app/services/chat.py:280-318` (stream_answer) and `chat.py:143-167` (answer)

- [ ] **Step 1: Add `_load_history` private method to `ChatService`**

In `backend/app/services/chat.py`, add a helper method:

```python
    async def _load_history(self, session_id: uuid.UUID, exclude_message_id: uuid.UUID) -> list[Message]:
        # Only RECEIVED (user messages) and COMPLETE (finished assistant responses).
        # Excluded statuses:
        # - STREAMING: response in progress, incomplete content
        # - PARTIAL: client disconnected mid-stream, content is truncated
        # - FAILED: error response, content is error message not conversation
        # These non-terminal states could give misleading context to the rewriter.
        result = await self._session.execute(
            select(Message)
            .where(
                Message.session_id == session_id,
                Message.id != exclude_message_id,
                Message.status.in_([MessageStatus.RECEIVED, MessageStatus.COMPLETE]),
            )
            .order_by(Message.created_at)
        )
        return list(result.scalars().all())
```

- [ ] **Step 2: Add `_do_rewrite` private method**

```python
    async def _do_rewrite(
        self,
        text: str,
        session_id: uuid.UUID,
        user_message: Message,
    ) -> str:
        history = await self._load_history(session_id, exclude_message_id=user_message.id)
        rewrite_result = await self._query_rewrite_service.rewrite(
            text, history, session_id=str(session_id),
        )

        if rewrite_result.is_rewritten:
            user_message.rewritten_query = rewrite_result.query
            await self._session.commit()

        return rewrite_result.query
```

- [ ] **Step 3: Insert rewrite into `stream_answer()`**

In `stream_answer()`, replace the retrieval call block (lines ~316-318):

**Before:**
```python
        retrieved_chunks: list[RetrievedChunk] = []
        try:
            retrieved_chunks = await self._retrieval_service.search(text, snapshot_id=snapshot_id)
```

**After:**
```python
        search_query = await self._do_rewrite(text, chat_session.id, user_message)

        retrieved_chunks: list[RetrievedChunk] = []
        try:
            retrieved_chunks = await self._retrieval_service.search(search_query, snapshot_id=snapshot_id)
```

- [ ] **Step 4: Insert rewrite into `answer()`**

In `answer()`, between user message persistence (line ~158) and retrieval (line ~167):

**Before:**
```python
        retrieved_chunks: list[RetrievedChunk] = []
        try:
            retrieved_chunks = await self._retrieval_service.search(text, snapshot_id=snapshot_id)
```

**After:**
```python
        search_query = await self._do_rewrite(text, chat_session.id, user_message)

        retrieved_chunks: list[RetrievedChunk] = []
        try:
            retrieved_chunks = await self._retrieval_service.search(search_query, snapshot_id=snapshot_id)
```

**Note:** `_persist_message` is NOT modified. The `_do_rewrite` method updates the user message directly after creation (via `user_message.rewritten_query = rewrite_result.query` + commit). This keeps `_persist_message` unchanged and avoids adding an unused parameter (YAGNI).

- [ ] **Step 5: Run all tests**

Run: `cd backend && python -m pytest tests/ -x -q`
Expected: ALL PASS (the mock_rewrite_service returns original query by default, so existing tests should still work)

- [ ] **Step 6: Propose commit**

Suggested message: `feat(chat): integrate query rewriting before retrieval (S4-04)`
Files: `backend/app/services/chat.py`
**Do NOT commit without explicit user permission.**

---

## Task 6: Integration tests for query rewriting

**Files:**
- Modify: `backend/tests/integration/test_chat_sse.py`

This task covers two behavioral contracts:
1. **Persistence:** `rewritten_query` is saved in the `messages` table for multi-turn queries.
2. **Retrieval routing:** `retrieval_service.search()` is called with the rewritten query, not the original.

The `chat_app` fixture uses `mock_rewrite_service` which passes through the original query by default. For rewrite tests, we need a `chat_app` variant that uses a real `QueryRewriteService` with a mocked LLM that returns a predictable rewritten query.

- [ ] **Step 1: Write test fixtures and integration tests**

Add to `backend/tests/integration/test_chat_sse.py` (or create alongside existing SSE tests):

```python
@pytest.fixture
def rewriting_chat_app(
    session_factory,
    mock_retrieval_service,
    mock_llm_service,
):
    """chat_app variant with a real QueryRewriteService backed by a mock LLM."""
    from app.api.chat import router as chat_router
    from app.persona.loader import PersonaContext
    from app.services.llm_types import LLMResponse
    from app.services.query_rewrite import QueryRewriteService

    # This mock LLM is used ONLY by the rewrite service.
    # It returns a predictable reformulated query.
    rewrite_llm = SimpleNamespace(
        complete=AsyncMock(
            return_value=LLMResponse(
                content="expanded: tell me more about AI books",
                model_name="test-rewrite-model",
                token_count_prompt=20,
                token_count_completion=10,
            )
        )
    )
    rewrite_service = QueryRewriteService(
        llm_service=rewrite_llm,
        rewrite_enabled=True,
        timeout_ms=3000,
        token_budget=2048,
        history_messages=10,
        temperature=0.1,
    )

    app = FastAPI()
    app.include_router(chat_router)
    app.state.settings = SimpleNamespace(
        min_retrieved_chunks=1,
        max_citations_per_response=5,
        sse_heartbeat_interval_seconds=15,
        sse_inter_token_timeout_seconds=30,
    )
    app.state.session_factory = session_factory
    app.state.retrieval_service = mock_retrieval_service
    app.state.llm_service = mock_llm_service
    app.state.query_rewrite_service = rewrite_service
    app.state.persona_context = PersonaContext(
        identity="Test identity",
        soul="Test soul",
        behavior="Test behavior",
        config_commit_hash="test-commit",
        config_content_hash="test-content-hash",
    )
    return app


@pytest_asyncio.fixture
async def rewriting_chat_client(rewriting_chat_app):
    transport = httpx.ASGITransport(app=rewriting_chat_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
```

Then add the tests. These use the same `_create_snapshot` helper and `aconnect_sse` pattern as the existing SSE tests in this file:

```python
@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_first_message_no_rewrite(
    rewriting_chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    sample_retrieved_chunk,
):
    """First message in session has no history → rewritten_query should be NULL."""
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]

    session_id = (await rewriting_chat_client.post("/api/chat/sessions", json={})).json()["id"]

    async with aconnect_sse(
        rewriting_chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": session_id, "text": "What is AI?"},
    ) as event_source:
        _ = [sse async for sse in event_source.aiter_sse()]

    async with session_factory() as session:
        user_msg = await session.scalar(
            select(Message).where(
                Message.session_id == uuid.UUID(session_id),
                Message.role == MessageRole.USER,
            )
        )
        assert user_msg is not None
        assert user_msg.rewritten_query is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_second_message_rewrite_persisted(
    rewriting_chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    sample_retrieved_chunk,
):
    """Second message should have rewritten_query populated in DB."""
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]

    session_id = (await rewriting_chat_client.post("/api/chat/sessions", json={})).json()["id"]

    # First message
    async with aconnect_sse(
        rewriting_chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": session_id, "text": "What is AI?"},
    ) as event_source:
        _ = [sse async for sse in event_source.aiter_sse()]

    # Second message (triggers rewrite)
    async with aconnect_sse(
        rewriting_chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": session_id, "text": "tell me more"},
    ) as event_source:
        _ = [sse async for sse in event_source.aiter_sse()]

    async with session_factory() as session:
        user_msgs = list(
            (
                await session.scalars(
                    select(Message)
                    .where(
                        Message.session_id == uuid.UUID(session_id),
                        Message.role == MessageRole.USER,
                    )
                    .order_by(Message.created_at)
                )
            ).all()
        )
        assert len(user_msgs) == 2
        assert user_msgs[0].rewritten_query is None
        assert user_msgs[1].rewritten_query == "expanded: tell me more about AI books"


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_retrieval_called_with_rewritten_query(
    rewriting_chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    sample_retrieved_chunk,
):
    """Retrieval service MUST be called with the rewritten query, not the original."""
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]

    session_id = (await rewriting_chat_client.post("/api/chat/sessions", json={})).json()["id"]

    # First message (no rewrite — first in session)
    async with aconnect_sse(
        rewriting_chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": session_id, "text": "What is AI?"},
    ) as event_source:
        _ = [sse async for sse in event_source.aiter_sse()]

    mock_retrieval_service.search.reset_mock()

    # Second message (triggers rewrite)
    async with aconnect_sse(
        rewriting_chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": session_id, "text": "tell me more"},
    ) as event_source:
        _ = [sse async for sse in event_source.aiter_sse()]

    # Verify: retrieval was called with the REWRITTEN query, not "tell me more"
    mock_retrieval_service.search.assert_called_once()
    call_args = mock_retrieval_service.search.call_args
    assert call_args[0][0] == "expanded: tell me more about AI books"
```

- [ ] **Step 2: Run integration tests**

Run: `cd backend && python -m pytest tests/integration/test_chat_sse.py -v -k rewrite`
Expected: ALL PASS

- [ ] **Step 3: Run full test suite**

Run: `cd backend && python -m pytest tests/ -x -q`
Expected: ALL PASS

- [ ] **Step 4: Propose commit**

Suggested message: `test(chat): add integration tests for query rewrite persistence and retrieval routing (S4-04)`
Files: `backend/tests/integration/test_chat_sse.py`
**Do NOT commit without explicit user permission.**

---

## Task 7: Final review and cleanup

- [ ] **Step 1: Re-read `docs/development.md`**

Read `docs/development.md` and self-review all changes against it:
- No mocks outside `tests/`
- No stubs without story reference
- Fail-open fallback is a real alternative (original query), not a stub
- SOLID: `QueryRewriteService` has single responsibility
- KISS: minimal implementation, no over-engineering
- YAGNI: no extra features beyond spec

- [ ] **Step 2: Verify all tests pass**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 3: Verify migration applies on fresh DB**

Run: `cd backend && alembic downgrade base && alembic upgrade head`
Expected: All migrations apply cleanly

- [ ] **Step 4: Propose final commit (if any cleanup needed)**

Suggested message: `chore(s4-04): final review cleanup`
**Do NOT commit without explicit user permission.**
