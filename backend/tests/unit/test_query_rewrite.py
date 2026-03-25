from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog.testing

from app.services.llm_types import LLMResponse
from app.services.query_rewrite import QueryRewriteService


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
async def test_rewrite_same_text_is_not_marked_as_rewritten() -> None:
    service, _ = _make_service(llm_complete_return="tell me more")
    history = [_make_message("user", "hi"), _make_message("assistant", "hello")]

    result = await service.rewrite("tell me more", history)

    assert result.query == "tell me more"
    assert result.is_rewritten is False


@pytest.mark.asyncio
async def test_token_budget_trimming() -> None:
    service, mock_complete = _make_service(token_budget=500)
    long_history = [
        _make_message("user", "A" * 600),
        _make_message("assistant", "B" * 600),
        _make_message("user", "C" * 60),
        _make_message("assistant", "D" * 60),
    ]

    result = await service.rewrite("tell me more", long_history)

    assert result.is_rewritten is True
    mock_complete.assert_called_once()
    call_messages = mock_complete.call_args[0][0]
    user_content = call_messages[1]["content"]
    assert "A" * 600 not in user_content
    assert "B" * 600 in user_content
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
    assert "first" not in user_content
    assert "second" not in user_content
    assert "third" in user_content


@pytest.mark.asyncio
async def test_observability_contract_omits_raw_query_text() -> None:
    service, _ = _make_service(llm_complete_side_effect=RuntimeError("LLM down"))
    history = [_make_message("user", "hi"), _make_message("assistant", "hello")]

    with structlog.testing.capture_logs() as captured_logs:
        result = await service.rewrite("tell me more", history, session_id="session-1")

    assert result.query == "tell me more"
    assert result.is_rewritten is False
    assert captured_logs == [
        {
            "event": "query_rewrite.error",
            "error": "RuntimeError",
            "log_level": "warning",
            "session_id": "session-1",
        }
    ]


@pytest.mark.asyncio
async def test_success_log_includes_latency() -> None:
    service, _ = _make_service(llm_complete_return="rewritten query")
    history = [_make_message("user", "hi"), _make_message("assistant", "hello")]

    with structlog.testing.capture_logs() as captured_logs:
        result = await service.rewrite("tell me more", history, session_id="session-1")

    assert result.query == "rewritten query"
    assert result.is_rewritten is True
    assert captured_logs[0]["event"] == "query_rewrite.success"
    assert captured_logs[0]["history_messages"] == 2
    assert captured_logs[0]["is_rewritten"] is True
    assert captured_logs[0]["log_level"] == "info"
    assert captured_logs[0]["session_id"] == "session-1"
    assert isinstance(captured_logs[0]["latency_ms"], int)
    assert captured_logs[0]["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_logs_omit_session_id_when_not_provided() -> None:
    service, _ = _make_service(llm_complete_return="rewritten query")
    history = [_make_message("user", "hi"), _make_message("assistant", "hello")]

    with structlog.testing.capture_logs() as captured_logs:
        await service.rewrite("tell me more", history)

    assert captured_logs[0]["event"] == "query_rewrite.success"
    assert "session_id" not in captured_logs[0]
