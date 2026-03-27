from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.db.models.enums import MessageRole, MessageStatus
from app.workers.tasks import summarize
from app.workers.tasks.summarize import generate_session_summary


class _SessionContextManager:
    def __init__(self, session) -> None:
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def patch_async_sessionmaker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(summarize, "async_sessionmaker", object)


def _message(role: MessageRole, content: str, message_id: uuid.UUID | None = None):
    return SimpleNamespace(
        id=message_id or uuid.uuid7(),
        role=role,
        content=content,
        status=MessageStatus.COMPLETE,
    )


@pytest.mark.asyncio
async def test_summary_generated_and_saved() -> None:
    session_id = uuid.uuid7()
    boundary_id = uuid.uuid7()
    window_start_id = uuid.uuid7()
    session_row = SimpleNamespace(
        id=session_id,
        summary="Previous summary.",
        summary_token_count=5,
        summary_up_to_message_id=boundary_id,
    )
    history = [
        _message(MessageRole.USER, "old question"),
        _message(MessageRole.ASSISTANT, "old answer", boundary_id),
        _message(MessageRole.USER, "middle question"),
        _message(MessageRole.ASSISTANT, "middle answer"),
        _message(MessageRole.USER, "latest question", window_start_id),
    ]
    llm_service = SimpleNamespace(
        complete=AsyncMock(return_value=SimpleNamespace(content="Updated summary"))
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=session_row),
        execute=AsyncMock(
            return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: history))
        ),
        commit=AsyncMock(),
    )

    await generate_session_summary(
        {
            "session_factory": lambda: _SessionContextManager(session),
            "summary_llm_service": llm_service,
            "settings": SimpleNamespace(
                conversation_memory_budget=100,
                conversation_summary_ratio=0.3,
                conversation_summary_timeout_ms=1000,
                conversation_summary_temperature=0.1,
            ),
        },
        str(session_id),
        str(window_start_id),
    )

    llm_service.complete.assert_awaited_once()
    prompt = llm_service.complete.await_args.args[0]
    assert "Previous summary: Previous summary." in prompt[1]["content"]
    assert "middle question" in prompt[1]["content"]
    assert session_row.summary == "Updated summary"
    assert session_row.summary_up_to_message_id == history[3].id
    assert session.commit.await_count == 1


@pytest.mark.asyncio
async def test_summary_skipped_when_no_messages_to_summarize() -> None:
    session_id = uuid.uuid7()
    boundary_id = uuid.uuid7()
    window_start_id = uuid.uuid7()
    session_row = SimpleNamespace(
        id=session_id,
        summary="Previous summary.",
        summary_token_count=5,
        summary_up_to_message_id=boundary_id,
    )
    history = [
        _message(MessageRole.USER, "old question"),
        _message(MessageRole.ASSISTANT, "old answer", boundary_id),
        _message(MessageRole.USER, "latest question", window_start_id),
    ]
    llm_service = SimpleNamespace(complete=AsyncMock())
    session = SimpleNamespace(
        get=AsyncMock(return_value=session_row),
        execute=AsyncMock(
            return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: history))
        ),
        commit=AsyncMock(),
    )

    await generate_session_summary(
        {
            "session_factory": lambda: _SessionContextManager(session),
            "summary_llm_service": llm_service,
            "settings": SimpleNamespace(
                conversation_memory_budget=100,
                conversation_summary_ratio=0.3,
                conversation_summary_timeout_ms=1000,
                conversation_summary_temperature=0.1,
            ),
        },
        str(session_id),
        str(window_start_id),
    )

    llm_service.complete.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_summary_failure_preserves_old_summary() -> None:
    session_id = uuid.uuid7()
    window_start_id = uuid.uuid7()
    session_row = SimpleNamespace(
        id=session_id,
        summary="Old summary",
        summary_token_count=5,
        summary_up_to_message_id=None,
    )
    history = [
        _message(MessageRole.USER, "first question"),
        _message(MessageRole.ASSISTANT, "first answer"),
        _message(MessageRole.USER, "latest question", window_start_id),
    ]
    llm_service = SimpleNamespace(complete=AsyncMock(side_effect=TimeoutError()))
    session = SimpleNamespace(
        get=AsyncMock(return_value=session_row),
        execute=AsyncMock(
            return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: history))
        ),
        commit=AsyncMock(),
    )

    await generate_session_summary(
        {
            "session_factory": lambda: _SessionContextManager(session),
            "summary_llm_service": llm_service,
            "settings": SimpleNamespace(
                conversation_memory_budget=100,
                conversation_summary_ratio=0.3,
                conversation_summary_timeout_ms=1,
                conversation_summary_temperature=0.1,
            ),
        },
        str(session_id),
        str(window_start_id),
    )

    assert session_row.summary == "Old summary"
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_dedup_guard_skips_when_boundary_already_advanced() -> None:
    session_id = uuid.uuid7()
    advanced_boundary_id = uuid.uuid7()
    window_start_id = uuid.uuid7()
    session_row = SimpleNamespace(
        id=session_id,
        summary="Updated already",
        summary_token_count=5,
        summary_up_to_message_id=advanced_boundary_id,
    )
    history = [
        _message(MessageRole.USER, "older question"),
        _message(MessageRole.ASSISTANT, "older answer"),
        _message(MessageRole.USER, "fresher question", advanced_boundary_id),
        _message(MessageRole.ASSISTANT, "latest answer", window_start_id),
    ]
    llm_service = SimpleNamespace(complete=AsyncMock())
    session = SimpleNamespace(
        get=AsyncMock(return_value=session_row),
        execute=AsyncMock(
            return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: history))
        ),
        commit=AsyncMock(),
    )

    await generate_session_summary(
        {
            "session_factory": lambda: _SessionContextManager(session),
            "summary_llm_service": llm_service,
            "settings": SimpleNamespace(
                conversation_memory_budget=100,
                conversation_summary_ratio=0.3,
                conversation_summary_timeout_ms=1000,
                conversation_summary_temperature=0.1,
            ),
        },
        str(session_id),
        str(window_start_id),
    )

    llm_service.complete.assert_not_awaited()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_max_summary_tokens_comes_from_config() -> None:
    session_id = uuid.uuid7()
    window_start_id = uuid.uuid7()
    session_row = SimpleNamespace(
        id=session_id,
        summary=None,
        summary_token_count=None,
        summary_up_to_message_id=None,
    )
    history = [
        _message(MessageRole.USER, "question"),
        _message(MessageRole.ASSISTANT, "answer"),
        _message(MessageRole.USER, "latest", window_start_id),
    ]
    llm_service = SimpleNamespace(
        complete=AsyncMock(return_value=SimpleNamespace(content="Summary"))
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=session_row),
        execute=AsyncMock(
            return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: history))
        ),
        commit=AsyncMock(),
    )

    await generate_session_summary(
        {
            "session_factory": lambda: _SessionContextManager(session),
            "summary_llm_service": llm_service,
            "settings": SimpleNamespace(
                conversation_memory_budget=4096,
                conversation_summary_ratio=0.25,
                conversation_summary_timeout_ms=1000,
                conversation_summary_temperature=0.1,
            ),
        },
        str(session_id),
        str(window_start_id),
    )

    prompt = llm_service.complete.await_args.args[0]
    assert "Keep summary under 1024 tokens." in prompt[0]["content"]


@pytest.mark.asyncio
async def test_summary_uses_asyncio_wait_for_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = uuid.uuid7()
    window_start_id = uuid.uuid7()
    session_row = SimpleNamespace(
        id=session_id,
        summary=None,
        summary_token_count=None,
        summary_up_to_message_id=None,
    )
    history = [
        _message(MessageRole.USER, "question"),
        _message(MessageRole.ASSISTANT, "answer"),
        _message(MessageRole.USER, "latest", window_start_id),
    ]
    llm_service = SimpleNamespace(
        complete=AsyncMock(return_value=SimpleNamespace(content="Summary"))
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=session_row),
        execute=AsyncMock(
            return_value=SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: history))
        ),
        commit=AsyncMock(),
    )
    captured_timeout: dict[str, float] = {}

    async def fake_wait_for(awaitable, timeout):
        captured_timeout["value"] = timeout
        return await awaitable

    monkeypatch.setattr(summarize.asyncio, "wait_for", fake_wait_for)

    await generate_session_summary(
        {
            "session_factory": lambda: _SessionContextManager(session),
            "summary_llm_service": llm_service,
            "settings": SimpleNamespace(
                conversation_memory_budget=100,
                conversation_summary_ratio=0.3,
                conversation_summary_timeout_ms=1234,
                conversation_summary_temperature=0.1,
            ),
        },
        str(session_id),
        str(window_start_id),
    )

    assert captured_timeout["value"] == pytest.approx(1.234)
