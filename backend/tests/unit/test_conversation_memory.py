from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from app.services.conversation_memory import ConversationMemoryService, MemoryBlock
from app.services.token_counter import estimate_tokens


def _msg(role: str, content: str, msg_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=msg_id or uuid.uuid4(),
        role=SimpleNamespace(value=role),
        content=content,
    )


def _session(
    *,
    summary: str | None = None,
    summary_token_count: int | None = None,
    summary_up_to_message_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        summary=summary,
        summary_token_count=summary_token_count,
        summary_up_to_message_id=summary_up_to_message_id,
    )


def test_memory_block_is_immutable() -> None:
    block = MemoryBlock(
        summary_text="summary",
        messages=[],
        total_tokens=1,
        needs_summary_update=False,
        window_start_message_id=None,
    )

    with pytest.raises(FrozenInstanceError):
        block.total_tokens = 2  # type: ignore[misc]


def test_empty_session_returns_empty_block() -> None:
    service = ConversationMemoryService(budget=4096, summary_ratio=0.3)

    block = service.build_memory_block(session=_session(), messages=[])

    assert block.summary_text is None
    assert block.messages == []
    assert block.total_tokens == 0
    assert block.needs_summary_update is False
    assert block.window_start_message_id is None


def test_short_session_fits_in_budget() -> None:
    messages = [
        _msg("user", "Hello"),
        _msg("assistant", "Hi there!"),
        _msg("user", "How are you?"),
        _msg("assistant", "I am fine."),
    ]
    service = ConversationMemoryService(budget=4096, summary_ratio=0.3)

    block = service.build_memory_block(session=_session(), messages=messages)

    assert block.summary_text is None
    assert block.messages == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "How are you?"},
        {"role": "assistant", "content": "I am fine."},
    ]
    assert block.needs_summary_update is False
    assert block.window_start_message_id == messages[0].id


def test_memory_block_fields_have_expected_types() -> None:
    messages = [_msg("user", "Hello"), _msg("assistant", "Hi there!")]
    service = ConversationMemoryService(budget=4096, summary_ratio=0.3)

    block = service.build_memory_block(session=_session(), messages=messages)

    assert block.summary_text is None
    assert isinstance(block.messages, list)
    assert all(isinstance(message, dict) for message in block.messages)
    assert all(isinstance(message["role"], str) for message in block.messages)
    assert all(isinstance(message["content"], str) for message in block.messages)
    assert isinstance(block.total_tokens, int)
    assert isinstance(block.needs_summary_update, bool)
    assert isinstance(block.window_start_message_id, uuid.UUID)


def test_long_session_triggers_needs_summary() -> None:
    messages = [
        _msg("user", "A" * 30),
        _msg("assistant", "B" * 30),
        _msg("user", "C" * 30),
        _msg("assistant", "D" * 30),
        _msg("user", "E" * 30),
        _msg("assistant", "F" * 30),
    ]
    service = ConversationMemoryService(budget=30, summary_ratio=0.3)

    block = service.build_memory_block(session=_session(), messages=messages)

    assert len(block.messages) < len(messages)
    assert block.needs_summary_update is True
    assert block.total_tokens <= 30
    expected_start = next(
        message.id for message in messages if message.content == block.messages[0]["content"]
    )
    assert block.window_start_message_id == expected_start


def test_session_with_existing_summary_uses_recent_window_only() -> None:
    boundary_id = uuid.uuid4()
    messages = [
        _msg("user", "old question"),
        _msg("assistant", "old answer", boundary_id),
        _msg("user", "recent question"),
        _msg("assistant", "recent answer"),
    ]
    service = ConversationMemoryService(budget=4096, summary_ratio=0.3)

    block = service.build_memory_block(
        session=_session(
            summary="Earlier topics.",
            summary_token_count=10,
            summary_up_to_message_id=boundary_id,
        ),
        messages=messages,
    )

    assert block.summary_text == "Earlier topics."
    assert block.messages == [
        {"role": "user", "content": "recent question"},
        {"role": "assistant", "content": "recent answer"},
    ]
    assert block.needs_summary_update is False


def test_summary_budget_deducted_at_face_value() -> None:
    boundary_id = uuid.uuid4()
    messages = [
        _msg("user", "old question"),
        _msg("assistant", "old answer", boundary_id),
        _msg("user", "A" * 150),
        _msg("assistant", "B" * 150),
        _msg("user", "C" * 30),
        _msg("assistant", "D" * 30),
    ]
    service = ConversationMemoryService(budget=100, summary_ratio=0.3)

    block = service.build_memory_block(
        session=_session(
            summary="Long summary",
            summary_token_count=80,
            summary_up_to_message_id=boundary_id,
        ),
        messages=messages,
    )

    assert block.total_tokens <= 100
    assert block.summary_text == "Long summary"
    assert [message["content"] for message in block.messages] == ["C" * 30, "D" * 30]


def test_messages_preserve_chronological_order() -> None:
    messages = [
        _msg("user", "first"),
        _msg("assistant", "reply first"),
        _msg("user", "second"),
        _msg("assistant", "reply second"),
    ]
    service = ConversationMemoryService(budget=4096, summary_ratio=0.3)

    block = service.build_memory_block(session=_session(), messages=messages)

    assert [message["content"] for message in block.messages] == [
        "first",
        "reply first",
        "second",
        "reply second",
    ]


def test_no_summary_uses_full_budget_independent_of_summary_ratio() -> None:
    messages = [
        _msg("user", "123456789"),
        _msg("assistant", "abcdefgh1234"),
        _msg("user", "latest-message!!"),
    ]
    low_ratio_service = ConversationMemoryService(budget=10, summary_ratio=0.1)
    high_ratio_service = ConversationMemoryService(budget=10, summary_ratio=0.9)

    low_ratio_block = low_ratio_service.build_memory_block(session=_session(), messages=messages)
    high_ratio_block = high_ratio_service.build_memory_block(session=_session(), messages=messages)

    assert low_ratio_block.messages == high_ratio_block.messages
    assert low_ratio_block.total_tokens == high_ratio_block.total_tokens
    assert low_ratio_block.total_tokens == (
        estimate_tokens("abcdefgh1234") + estimate_tokens("latest-message!!")
    )


def test_boundary_not_found_discards_stale_summary() -> None:
    messages = [
        _msg("user", "question one"),
        _msg("assistant", "answer one"),
    ]
    service = ConversationMemoryService(budget=4096, summary_ratio=0.3)

    block = service.build_memory_block(
        session=_session(
            summary="Stale summary",
            summary_token_count=10,
            summary_up_to_message_id=uuid.uuid4(),
        ),
        messages=messages,
    )

    assert block.summary_text is None
    assert block.total_tokens > 0
    assert block.needs_summary_update is False


def test_zero_window_budget_keeps_summary_and_drops_recent_messages() -> None:
    boundary_id = uuid.uuid4()
    messages = [
        _msg("user", "older question", boundary_id),
        _msg("assistant", "older answer"),
        _msg("user", "recent question"),
        _msg("assistant", "recent answer"),
    ]
    service = ConversationMemoryService(budget=10, summary_ratio=0.3)

    block = service.build_memory_block(
        session=_session(
            summary="Existing summary",
            summary_token_count=10,
            summary_up_to_message_id=boundary_id,
        ),
        messages=messages,
    )

    assert block.summary_text == "Existing summary"
    assert block.messages == []
    assert block.total_tokens == 10
    assert block.needs_summary_update is True
    assert block.window_start_message_id is None
