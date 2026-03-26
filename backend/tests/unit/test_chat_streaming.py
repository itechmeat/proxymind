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
    ChatStreamCitations,
    ChatStreamDone,
    ChatStreamError,
    ChatStreamMeta,
    ChatStreamToken,
    ConcurrentStreamError,
    IdempotencyConflictError,
    NoActiveSnapshotError,
    SessionNotFoundError,
)
from app.services.context_assembler import AssembledPrompt, ContextAssembler
from app.services.citation import SourceInfo
from app.services.llm_types import LLMError, LLMStreamEnd, LLMToken
from app.services.prompt import NO_CONTEXT_REFUSAL
from app.services.promotions import PromotionsService
from app.services.query_rewrite import RewriteResult
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
    anchor_page: int | None = None,
    anchor_chapter: str | None = None,
    anchor_section: str | None = None,
    anchor_timecode: str | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id or uuid.uuid4(),
        text_content=text_content,
        score=0.91,
        anchor_metadata={
            "anchor_page": anchor_page,
            "anchor_chapter": anchor_chapter,
            "anchor_section": anchor_section,
            "anchor_timecode": anchor_timecode,
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
    max_citations_per_response: int = 5,
    rewritten_query: str | None = None,
    rewrite_error: Exception | None = None,
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

    async def _rewrite(query, history, **kwargs):
        if rewrite_error is not None:
            raise rewrite_error
        if rewritten_query is None:
            return RewriteResult(query=query, is_rewritten=False, original_query=query)
        return RewriteResult(query=rewritten_query, is_rewritten=True, original_query=query)

    rewrite_service = SimpleNamespace(rewrite=AsyncMock(side_effect=_rewrite))
    context_assembler = ContextAssembler(
        persona_context=persona_context,
        promotions_service=PromotionsService(promotions_text=""),
        retrieval_context_budget=4096,
        max_citations=max_citations_per_response,
        min_retrieved_chunks=min_retrieved_chunks,
        max_promotions_per_response=1,
    )

    service = ChatService(
        session=db_session,
        snapshot_service=SnapshotService(session=db_session),
        retrieval_service=retrieval_service,
        llm_service=llm_service,
        query_rewrite_service=rewrite_service,
        context_assembler=context_assembler,
        min_retrieved_chunks=min_retrieved_chunks,
        max_citations_per_response=max_citations_per_response,
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
async def test_stream_answer_emits_citations_event(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    source_id = uuid.uuid4()
    chunk = _chunk(
        source_id=source_id,
        text_content="Chapter about clean code",
        anchor_page=42,
        anchor_chapter="Chapter 5",
    )
    source_info = SourceInfo(
        id=source_id,
        title="Clean Architecture",
        public_url=None,
        source_type="pdf",
    )
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[chunk],
        stream_tokens=("Based on the book [source:1], clean code matters.",),
    )
    service._load_source_map = AsyncMock(return_value={source_id: source_info})
    session = await service.create_session()

    events = await _collect_events(service, session_id=session.id, text="question")

    citation_events = [event for event in events if isinstance(event, ChatStreamCitations)]
    assert len(citation_events) == 1
    assert len(citation_events[0].citations) == 1
    assert citation_events[0].citations[0].source_title == "Clean Architecture"
    event_types = [type(event).__name__ for event in events]
    assert event_types.index("ChatStreamCitations") < event_types.index("ChatStreamDone")


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
    assert messages[1].content_type_spans == [{"start": 0, "end": 6, "type": "inference"}]
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
    citation_events = [event for event in events if isinstance(event, ChatStreamCitations)]
    assert len(citation_events) == 1
    assert citation_events[0].citations == []
    messages = await _message_rows(db_session, session.id)
    assert messages[1].content_type_spans is None
    llm_service.stream.assert_not_called()


@pytest.mark.asyncio
async def test_llm_prompt_uses_original_query_when_rewrite_occurs(
    db_session: AsyncSession,
    persona_context: PersonaContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, retrieval_service, llm_service = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk()],
        stream_tokens=("answer",),
        rewritten_query="expanded query",
    )
    session = await service.create_session()
    captured_prompt_text: dict[str, str] = {}

    def _capture_assemble(*, chunks, query, source_map):
        captured_prompt_text["text"] = query
        return AssembledPrompt(
            messages=[{"role": "user", "content": query}],
            token_estimate=1,
            included_promotions=[],
            retrieval_chunks_used=len(chunks),
            retrieval_chunks_total=len(chunks),
            layer_token_counts={},
        )

    monkeypatch.setattr(service._context_assembler, "assemble", _capture_assemble)

    await _collect_events(service, session_id=session.id, text="original question")

    retrieval_service.search.assert_awaited_once_with("expanded query", snapshot_id=session.snapshot_id)
    llm_service.stream.assert_called_once()
    assert captured_prompt_text["text"] == "original question"


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
async def test_stream_answer_persists_failed_assistant_when_rewrite_raises(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, retrieval_service, llm_service = _make_service(
        db_session,
        persona_context=persona_context,
        rewrite_error=RuntimeError("rewrite exploded"),
    )
    session = await service.create_session()

    with pytest.raises(RuntimeError, match="rewrite exploded"):
        await _collect_events(service, session_id=session.id, text="Q?")

    retrieval_service.search.assert_not_awaited()
    llm_service.stream.assert_not_called()
    messages = await _message_rows(db_session, session.id)
    assert [message.role for message in messages] == [MessageRole.USER, MessageRole.ASSISTANT]
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
async def test_idempotent_replay_includes_citations_event(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    source_id = uuid.uuid4()
    source_info = SourceInfo(
        id=source_id,
        title="Test Source",
        public_url=None,
        source_type="pdf",
    )
    service, _, _ = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[
            _chunk(
                source_id=source_id,
                anchor_page=42,
                anchor_chapter="Chapter 5",
            )
        ],
        stream_tokens=("Answer [source:1].",),
    )
    service._load_source_map = AsyncMock(return_value={source_id: source_info})
    session = await service.create_session()

    first_events = await _collect_events(
        service,
        session_id=session.id,
        text="Q?",
        idempotency_key="key-1",
    )
    assert any(isinstance(event, ChatStreamCitations) for event in first_events)

    replay_events = await _collect_events(
        service,
        session_id=session.id,
        text="Q?",
        idempotency_key="key-1",
    )

    citation_events = [event for event in replay_events if isinstance(event, ChatStreamCitations)]
    assert len(citation_events) == 1
    assert citation_events[0].citations == [
        citation
        for event in first_events
        if isinstance(event, ChatStreamCitations)
        for citation in event.citations
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
