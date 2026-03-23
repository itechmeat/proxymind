from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import Message
from app.db.models.enums import MessageRole, MessageStatus, SnapshotStatus
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

    llm_service = SimpleNamespace(complete=AsyncMock(), stream=AsyncMock())
    if stream_error is not None:
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


async def _collect_events(service: ChatService, **kwargs):
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
    )
    session = await service.create_session()

    events = await _collect_events(service, session_id=session.id, text="Q?")

    assert isinstance(events[0], ChatStreamMeta)
    assert events[0].snapshot_id == snapshot.id
    assert [event.content for event in events if isinstance(event, ChatStreamToken)] == [
        "Hello",
        " world",
    ]
    done_events = [event for event in events if isinstance(event, ChatStreamDone)]
    assert len(done_events) == 1
    assert done_events[0].retrieved_chunks_count == 1


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
    assert messages[1].status is MessageStatus.COMPLETE
    assert messages[1].content == "answer"
    assert messages[1].source_ids == [source_id]
    assert messages[1].parent_message_id == messages[0].id


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

    assert (
        "".join(event.content for event in events if isinstance(event, ChatStreamToken))
        == NO_CONTEXT_REFUSAL
    )
    llm_service.stream.assert_not_called()


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

    assert len([event for event in events if isinstance(event, ChatStreamError)]) == 1
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

    await _collect_events(service, session_id=session.id, text="Q?", idempotency_key="key-1")
    replay_events = await _collect_events(
        service,
        session_id=session.id,
        text="Q?",
        idempotency_key="key-1",
    )

    assert len([event for event in replay_events if isinstance(event, ChatStreamMeta)]) == 1
    assert [event.content for event in replay_events if isinstance(event, ChatStreamToken)] == [
        "original"
    ]


@pytest.mark.asyncio
async def test_stream_answer_reuses_existing_user_for_failed_retry(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk()],
        stream_tokens=("retry",),
    )
    session = await service.create_session()

    user_message = await service._persist_message(
        session,
        role=MessageRole.USER,
        content="Q?",
        status=MessageStatus.RECEIVED,
        snapshot_id=session.snapshot_id,
        idempotency_key="key-1",
    )
    await service._persist_message(
        session,
        role=MessageRole.ASSISTANT,
        content="partial",
        status=MessageStatus.FAILED,
        snapshot_id=session.snapshot_id,
        parent_message_id=user_message.id,
    )

    events = await _collect_events(
        service,
        session_id=session.id,
        text="Q?",
        idempotency_key="key-1",
    )

    messages = await _message_rows(db_session, session.id)
    assert len([message for message in messages if message.role is MessageRole.USER]) == 1
    assert messages[-1].parent_message_id == user_message.id
    assert [event.content for event in events if isinstance(event, ChatStreamToken)] == ["retry"]


@pytest.mark.asyncio
async def test_stream_answer_idempotency_conflict_for_streaming_message(
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

    user_message = await service._persist_message(
        session,
        role=MessageRole.USER,
        content="Q?",
        status=MessageStatus.RECEIVED,
        snapshot_id=session.snapshot_id,
        idempotency_key="key-1",
    )
    await service._persist_message(
        session,
        role=MessageRole.ASSISTANT,
        content="",
        status=MessageStatus.STREAMING,
        snapshot_id=session.snapshot_id,
        parent_message_id=user_message.id,
    )

    with pytest.raises(IdempotencyConflictError):
        await _collect_events(service, session_id=session.id, text="Q?", idempotency_key="key-1")


@pytest.mark.asyncio
async def test_replay_bypasses_concurrency_guard(
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

    user_message = await service._persist_message(
        session,
        role=MessageRole.USER,
        content="Q?",
        status=MessageStatus.RECEIVED,
        snapshot_id=session.snapshot_id,
        idempotency_key="key-1",
    )
    assistant_message = await service._persist_message(
        session,
        role=MessageRole.ASSISTANT,
        content="cached",
        status=MessageStatus.COMPLETE,
        snapshot_id=session.snapshot_id,
        parent_message_id=user_message.id,
    )
    await service._persist_message(
        session,
        role=MessageRole.ASSISTANT,
        content="",
        status=MessageStatus.STREAMING,
        snapshot_id=session.snapshot_id,
    )

    events = await _collect_events(
        service,
        session_id=session.id,
        text="Q?",
        idempotency_key="key-1",
    )

    assert isinstance(events[0], ChatStreamMeta)
    assert events[0].message_id == assistant_message.id
    assert [event.content for event in events if isinstance(event, ChatStreamToken)] == ["cached"]


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

    db_session.add(
        Message(
            id=uuid.uuid7(),
            session_id=session.id,
            role=MessageRole.ASSISTANT,
            content="",
            status=MessageStatus.STREAMING,
        )
    )
    await db_session.commit()

    with pytest.raises(ConcurrentStreamError):
        await _collect_events(service, session_id=session.id, text="Q?")


@pytest.mark.asyncio
async def test_save_partial_on_disconnect_updates_streaming_message(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(db_session, persona_context=persona_context)
    session = await service.create_session()
    assistant_message = await service._persist_message(
        session,
        role=MessageRole.ASSISTANT,
        content="",
        status=MessageStatus.STREAMING,
        snapshot_id=session.snapshot_id,
    )

    await service.save_partial_on_disconnect(assistant_message.id, "partial")

    refreshed_message = await db_session.get(Message, assistant_message.id)
    assert refreshed_message is not None
    assert refreshed_message.status is MessageStatus.PARTIAL
    assert refreshed_message.content == "partial"


@pytest.mark.asyncio
async def test_save_failed_on_timeout_updates_streaming_message(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(db_session, persona_context=persona_context)
    session = await service.create_session()
    assistant_message = await service._persist_message(
        session,
        role=MessageRole.ASSISTANT,
        content="",
        status=MessageStatus.STREAMING,
        snapshot_id=session.snapshot_id,
    )

    await service.save_failed_on_timeout(assistant_message.id, "timed out")

    refreshed_message = await db_session.get(Message, assistant_message.id)
    assert refreshed_message is not None
    assert refreshed_message.status is MessageStatus.FAILED
    assert refreshed_message.content == "timed out"
