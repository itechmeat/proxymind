from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import structlog.testing
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
from app.services.chat import ChatService, NoActiveSnapshotError, SessionNotFoundError
from app.services.llm_types import LLMError, LLMResponse
from app.services.prompt import NO_CONTEXT_REFUSAL
from app.services.qdrant import RetrievedChunk
from app.services.retrieval import RetrievalError
from app.services.snapshot import SnapshotService


async def _create_snapshot(
    db_session: AsyncSession,
    *,
    status: SnapshotStatus,
    knowledge_base_id: uuid.UUID = DEFAULT_KNOWLEDGE_BASE_ID,
) -> KnowledgeSnapshot:
    snapshot = KnowledgeSnapshot(
        id=uuid.uuid7(),
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=knowledge_base_id,
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


def _make_service(
    db_session: AsyncSession,
    *,
    persona_context: PersonaContext,
    retrieval_result: list[RetrievedChunk] | Exception | None = None,
    llm_result: LLMResponse | Exception | None = None,
    min_retrieved_chunks: int = 1,
) -> tuple[ChatService, SimpleNamespace, SimpleNamespace]:
    retrieval_service = SimpleNamespace(search=AsyncMock())
    if isinstance(retrieval_result, Exception):
        retrieval_service.search.side_effect = retrieval_result
    else:
        retrieval_service.search.return_value = retrieval_result or []

    llm_service = SimpleNamespace(complete=AsyncMock())
    if isinstance(llm_result, Exception):
        llm_service.complete.side_effect = llm_result
    elif llm_result is not None:
        llm_service.complete.return_value = llm_result

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


async def _message_rows(db_session: AsyncSession, session_id: uuid.UUID) -> list[Message]:
    return list(
        (
            await db_session.scalars(
                select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
            )
        ).all()
    )


@pytest.mark.asyncio
async def test_create_session_uses_active_snapshot_when_available(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    active_snapshot = await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(db_session, persona_context=persona_context)

    chat_session = await service.create_session(channel=SessionChannel.API)

    assert chat_session.snapshot_id == active_snapshot.id
    assert chat_session.channel is SessionChannel.API
    assert chat_session.message_count == 0


@pytest.mark.asyncio
async def test_create_session_leaves_snapshot_unbound_without_active_snapshot(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    service, _, _ = _make_service(db_session, persona_context=persona_context)

    chat_session = await service.create_session()

    assert chat_session.snapshot_id is None
    assert chat_session.channel is SessionChannel.WEB


@pytest.mark.asyncio
async def test_answer_saves_assistant_response_with_chunks(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    active_snapshot = await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    source_id = uuid.uuid4()
    service, retrieval_service, llm_service = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk(source_id=source_id)],
        llm_result=LLMResponse(
            content="Grounded answer",
            model_name="openai/gpt-4o",
            token_count_prompt=12,
            token_count_completion=6,
        ),
    )
    chat_session = await service.create_session()

    result = await service.answer(session_id=chat_session.id, text="Question?")

    assert result.retrieved_chunks_count == 1
    assert result.assistant_message.content == "Grounded answer"
    assert result.assistant_message.snapshot_id == active_snapshot.id
    assert result.assistant_message.source_ids == [source_id]
    retrieval_service.search.assert_awaited_once_with("Question?", snapshot_id=active_snapshot.id)
    llm_service.complete.assert_awaited_once()

    messages = await _message_rows(db_session, chat_session.id)
    assert [message.role for message in messages] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert messages[1].status is MessageStatus.COMPLETE
    session_row = await db_session.get(Session, chat_session.id)
    assert session_row is not None
    assert session_row.message_count == 2


@pytest.mark.asyncio
async def test_answer_returns_refusal_without_llm_when_no_chunks(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    active_snapshot = await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, retrieval_service, llm_service = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[],
    )
    chat_session = await service.create_session()

    result = await service.answer(session_id=chat_session.id, text="Question?")

    assert result.retrieved_chunks_count == 0
    assert result.assistant_message.content == NO_CONTEXT_REFUSAL
    assert result.assistant_message.status is MessageStatus.COMPLETE
    assert result.assistant_message.snapshot_id == active_snapshot.id
    assert result.assistant_message.source_ids == []
    retrieval_service.search.assert_awaited_once()
    llm_service.complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_answer_raises_when_no_snapshot_is_available(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    service, _, _ = _make_service(db_session, persona_context=persona_context)
    chat_session = await service.create_session()

    with pytest.raises(NoActiveSnapshotError, match="No active snapshot is available"):
        await service.answer(session_id=chat_session.id, text="Question?")

    messages = await _message_rows(db_session, chat_session.id)
    assert messages == []


@pytest.mark.asyncio
async def test_answer_persists_failed_assistant_on_llm_error(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk()],
        llm_result=LLMError("LLM completion failed"),
    )
    chat_session = await service.create_session()

    with pytest.raises(LLMError):
        await service.answer(session_id=chat_session.id, text="Question?")

    messages = await _message_rows(db_session, chat_session.id)
    assert [message.status for message in messages] == [
        MessageStatus.RECEIVED,
        MessageStatus.FAILED,
    ]
    assert messages[1].content == "Failed to generate assistant response."


@pytest.mark.asyncio
async def test_answer_persists_failed_assistant_on_retrieval_error(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, llm_service = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=RetrievalError("Retrieval failed"),
    )
    chat_session = await service.create_session()

    with pytest.raises(RetrievalError):
        await service.answer(session_id=chat_session.id, text="Question?")

    llm_service.complete.assert_not_awaited()
    messages = await _message_rows(db_session, chat_session.id)
    assert [message.status for message in messages] == [
        MessageStatus.RECEIVED,
        MessageStatus.FAILED,
    ]


@pytest.mark.asyncio
async def test_answer_preserves_original_error_when_failed_message_persist_fails(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=RetrievalError("Retrieval failed"),
    )
    chat_session = await service.create_session()
    original_persist_message = service._persist_message
    call_count = 0

    async def flaky_persist_message(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise RuntimeError("persist failed")
        return await original_persist_message(*args, **kwargs)

    service._persist_message = flaky_persist_message  # type: ignore[method-assign]

    with pytest.raises(RetrievalError, match="Retrieval failed"):
        await service.answer(session_id=chat_session.id, text="Question?")

    messages = await _message_rows(db_session, chat_session.id)
    assert [message.role for message in messages] == [MessageRole.USER]


@pytest.mark.asyncio
async def test_answer_lazy_binds_snapshot_when_it_appears_later(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk()],
        llm_result=LLMResponse(
            content="Bound answer",
            model_name="openai/gpt-4o",
            token_count_prompt=8,
            token_count_completion=4,
        ),
    )
    chat_session = await service.create_session()
    active_snapshot = await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)

    result = await service.answer(session_id=chat_session.id, text="Question?")

    assert result.assistant_message.snapshot_id == active_snapshot.id
    session_row = await db_session.get(Session, chat_session.id)
    assert session_row is not None
    assert session_row.snapshot_id == active_snapshot.id


@pytest.mark.asyncio
async def test_answer_keeps_bound_snapshot_immutable_after_new_active_snapshot(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    first_snapshot = await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, retrieval_service, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk()],
        llm_result=LLMResponse(
            content="Stable answer",
            model_name="openai/gpt-4o",
            token_count_prompt=8,
            token_count_completion=4,
        ),
    )
    chat_session = await service.create_session()

    first_snapshot.status = SnapshotStatus.PUBLISHED
    second_snapshot = KnowledgeSnapshot(
        id=uuid.uuid7(),
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        name="Snapshot active 2",
        status=SnapshotStatus.ACTIVE,
    )
    db_session.add(second_snapshot)
    await db_session.commit()

    await service.answer(session_id=chat_session.id, text="Question?")

    session_row = await db_session.get(Session, chat_session.id)
    assert session_row is not None
    assert session_row.snapshot_id == first_snapshot.id
    retrieval_service.search.assert_awaited_once_with("Question?", snapshot_id=first_snapshot.id)


@pytest.mark.asyncio
async def test_answer_deduplicates_source_ids(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    shared_source_id = uuid.uuid4()
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[
            _chunk(source_id=shared_source_id, text_content="One"),
            _chunk(source_id=shared_source_id, text_content="Two"),
        ],
        llm_result=LLMResponse(
            content="Deduped",
            model_name="openai/gpt-4o",
            token_count_prompt=8,
            token_count_completion=4,
        ),
    )
    chat_session = await service.create_session()

    result = await service.answer(session_id=chat_session.id, text="Question?")

    assert result.assistant_message.source_ids == [shared_source_id]


@pytest.mark.asyncio
async def test_get_session_returns_history_and_raises_for_missing_session(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk()],
        llm_result=LLMResponse(
            content="History answer",
            model_name="openai/gpt-4o",
            token_count_prompt=8,
            token_count_completion=4,
        ),
    )
    chat_session = await service.create_session()
    await service.answer(session_id=chat_session.id, text="Question?")

    loaded_session = await service.get_session(chat_session.id)

    assert [message.role for message in loaded_session.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]

    with pytest.raises(SessionNotFoundError, match="Session not found"):
        await service.get_session(uuid.uuid7())


@pytest.mark.asyncio
async def test_config_hashes_logged_on_successful_response(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk()],
        llm_result=LLMResponse(
            content="Grounded answer",
            model_name="openai/gpt-4o",
            token_count_prompt=12,
            token_count_completion=6,
        ),
    )
    chat_session = await service.create_session()

    with structlog.testing.capture_logs() as logs:
        await service.answer(session_id=chat_session.id, text="Question?")

    completed_logs = [entry for entry in logs if entry.get("event") == "chat.assistant_completed"]
    assert len(completed_logs) == 1
    assert completed_logs[0]["config_commit_hash"] == persona_context.config_commit_hash
    assert completed_logs[0]["config_content_hash"] == persona_context.config_content_hash


@pytest.mark.asyncio
async def test_config_hashes_logged_on_refusal(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[],
    )
    chat_session = await service.create_session()

    with structlog.testing.capture_logs() as logs:
        await service.answer(session_id=chat_session.id, text="Question?")

    refusal_logs = [entry for entry in logs if entry.get("event") == "chat.refusal_returned"]
    assert len(refusal_logs) == 1
    assert refusal_logs[0]["config_commit_hash"] == persona_context.config_commit_hash
    assert refusal_logs[0]["config_content_hash"] == persona_context.config_content_hash
