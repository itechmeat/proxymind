from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID
from app.db.models import Message, Session
from app.db.models.enums import MessageRole, MessageStatus, SessionChannel, SessionStatus
from app.services.conversation_memory import ConversationMemoryService
from app.services.token_counter import estimate_tokens
from app.workers.tasks.summarize import generate_session_summary


async def _create_session_with_messages(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    summary: str | None = None,
    summary_token_count: int | None = None,
    summary_up_to_message_id: uuid.UUID | None = None,
    messages: list[tuple[MessageRole, str]],
) -> tuple[Session, list[Message]]:
    session_id = uuid.uuid7()
    message_rows: list[Message] = []

    async with session_factory() as session:
        session_row = Session(
            id=session_id,
            agent_id=DEFAULT_AGENT_ID,
            status=SessionStatus.ACTIVE,
            channel=SessionChannel.API,
            message_count=len(messages),
            summary=summary,
            summary_token_count=summary_token_count,
            summary_up_to_message_id=summary_up_to_message_id,
        )
        session.add(session_row)
        await session.flush()

        for role, content in messages:
            message_row = Message(
                id=uuid.uuid7(),
                session_id=session_id,
                role=role,
                content=content,
                status=MessageStatus.COMPLETE,
            )
            session.add(message_row)
            message_rows.append(message_row)

        await session.commit()

    return session_row, message_rows


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_build_memory_block_from_real_session_history(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, created_messages = await _create_session_with_messages(
        session_factory,
        messages=[
            (MessageRole.USER, "123456789"),
            (MessageRole.ASSISTANT, "abcdefgh1234"),
            (MessageRole.USER, "latest-message!!"),
        ],
    )
    service = ConversationMemoryService(budget=10, summary_ratio=0.3)

    async with session_factory() as session:
        session_row = await session.scalar(select(Session))
        history = list((await session.scalars(select(Message).order_by(Message.created_at))).all())

    block = service.build_memory_block(session=session_row, messages=history)

    assert [message["role"] for message in block.messages] == [
        MessageRole.ASSISTANT.value,
        MessageRole.USER.value,
    ]
    assert [message["content"] for message in block.messages] == [
        created_messages[1].content,
        created_messages[2].content,
    ]
    assert block.total_tokens == estimate_tokens(created_messages[1].content) + estimate_tokens(
        created_messages[2].content
    )
    assert block.needs_summary_update is True
    assert block.window_start_message_id == created_messages[1].id


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_persisted_summary_is_used_in_next_memory_block(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    session_row, created_messages = await _create_session_with_messages(
        session_factory,
        messages=[
            (MessageRole.USER, "first question"),
            (MessageRole.ASSISTANT, "first answer"),
            (MessageRole.USER, "latest question"),
            (MessageRole.ASSISTANT, "latest answer"),
        ],
    )
    summary_text = "Condensed summary of the first exchange"
    llm_service = SimpleNamespace(
        complete=AsyncMock(return_value=SimpleNamespace(content=summary_text))
    )

    await generate_session_summary(
        {
            "session_factory": session_factory,
            "summary_llm_service": llm_service,
            "settings": SimpleNamespace(
                conversation_memory_budget=128,
                conversation_summary_ratio=0.25,
                conversation_summary_timeout_ms=1000,
                conversation_summary_temperature=0.1,
            ),
        },
        str(session_row.id),
        str(created_messages[2].id),
    )

    service = ConversationMemoryService(budget=512, summary_ratio=0.25)

    async with session_factory() as session:
        persisted_session = await session.get(Session, session_row.id)
        assert persisted_session is not None
        history = list(
            (
                await session.scalars(
                    select(Message)
                    .where(Message.session_id == session_row.id)
                    .order_by(Message.created_at)
                )
            ).all()
        )

    block = service.build_memory_block(session=persisted_session, messages=history)

    assert persisted_session.summary == summary_text
    assert persisted_session.summary_up_to_message_id == created_messages[1].id
    assert block.summary_text == summary_text
    assert [message["content"] for message in block.messages] == [
        created_messages[2].content,
        created_messages[3].content,
    ]
    assert block.needs_summary_update is False
    assert block.window_start_message_id == created_messages[2].id
    assert block.total_tokens == estimate_tokens(summary_text) + estimate_tokens(
        created_messages[2].content
    ) + estimate_tokens(created_messages[3].content)
