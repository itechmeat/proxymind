from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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
from app.services.context_assembler import ContextAssembler
from app.services.conversation_memory import MemoryBlock
from app.services.llm_types import LLMError, LLMResponse
from app.services.promotions import PromotionsService
from app.services.prompt import NO_CONTEXT_REFUSAL
from app.services.qdrant import RetrievedChunk
from app.services.query_rewrite import RewriteResult
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
    rewritten_query: str | None = None,
    rewrite_error: Exception | None = None,
    conversation_memory_service: object | None = None,
    summary_enqueuer: object | None = None,
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

    async def _rewrite(query, history, **kwargs):
        if rewrite_error is not None:
            raise rewrite_error
        if rewritten_query is None:
            return RewriteResult(query=query, is_rewritten=False, original_query=query)
        return RewriteResult(query=rewritten_query, is_rewritten=True, original_query=query)

    rewrite_service = SimpleNamespace(rewrite=AsyncMock(side_effect=_rewrite))
    audit_service = SimpleNamespace(log_response=AsyncMock())
    context_assembler = ContextAssembler(
        persona_context=persona_context,
        promotions_service=PromotionsService(promotions_text=""),
        retrieval_context_budget=4096,
        max_citations=5,
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
        conversation_memory_service=conversation_memory_service,
        summary_enqueuer=summary_enqueuer,
        audit_service=audit_service,
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

    assert result.assistant_message.source_ids == [source_id]

    assert result.retrieved_chunks_count == 1
    assert result.assistant_message.content == "Grounded answer"
    assert result.assistant_message.snapshot_id == active_snapshot.id
    assert result.assistant_message.source_ids == [source_id]
    retrieval_service.search.assert_awaited_once_with("Question?", snapshot_id=active_snapshot.id)
    llm_service.complete.assert_awaited_once()

    messages = await _message_rows(db_session, chat_session.id)
    assert [message.role for message in messages] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert messages[1].status is MessageStatus.COMPLETE
    assert messages[1].content_type_spans == [
        {"start": 0, "end": len("Grounded answer"), "type": "inference"}
    ]
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
    assert result.assistant_message.content_type_spans is None
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
async def test_answer_passes_memory_block_to_assembler(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    memory_block = MemoryBlock(
        summary_text="Earlier context",
        messages=[
            {"role": "user", "content": "Earlier question"},
            {"role": "assistant", "content": "Earlier answer"},
        ],
        total_tokens=20,
        needs_summary_update=False,
        window_start_message_id=None,
    )
    memory_service = SimpleNamespace(build_memory_block=MagicMock(return_value=memory_block))
    service, _, llm_service = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk()],
        llm_result=LLMResponse(
            content="Grounded answer",
            model_name="openai/gpt-4o",
            token_count_prompt=12,
            token_count_completion=6,
        ),
        conversation_memory_service=memory_service,
    )
    chat_session = await service.create_session()
    original_assemble = service._context_assembler.assemble
    service._context_assembler.assemble = MagicMock(side_effect=original_assemble)  # type: ignore[method-assign]

    await service.answer(session_id=chat_session.id, text="Question?")

    memory_service.build_memory_block.assert_called_once()
    assert service._context_assembler.assemble.call_args.kwargs["memory_block"] == memory_block
    llm_service.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_answer_enqueues_summary_when_needed(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    window_start_id = uuid.uuid7()
    memory_service = SimpleNamespace(
        build_memory_block=MagicMock(
            return_value=MemoryBlock(
                summary_text=None,
                messages=[],
                total_tokens=0,
                needs_summary_update=True,
                window_start_message_id=window_start_id,
            )
        )
    )
    summary_enqueuer = AsyncMock()
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
        conversation_memory_service=memory_service,
        summary_enqueuer=summary_enqueuer,
    )
    chat_session = await service.create_session()

    await service.answer(session_id=chat_session.id, text="Question?")

    summary_enqueuer.assert_awaited_once_with(str(chat_session.id), str(window_start_id))


@pytest.mark.asyncio
async def test_answer_skips_summary_enqueue_when_not_needed(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    memory_service = SimpleNamespace(
        build_memory_block=MagicMock(
            return_value=MemoryBlock(
                summary_text=None,
                messages=[],
                total_tokens=0,
                needs_summary_update=False,
                window_start_message_id=None,
            )
        )
    )
    summary_enqueuer = AsyncMock()
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
        conversation_memory_service=memory_service,
        summary_enqueuer=summary_enqueuer,
    )
    chat_session = await service.create_session()

    await service.answer(session_id=chat_session.id, text="Question?")

    summary_enqueuer.assert_not_awaited()


@pytest.mark.asyncio
async def test_answer_logs_enqueue_failure_without_failing_response(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    memory_service = SimpleNamespace(
        build_memory_block=MagicMock(
            return_value=MemoryBlock(
                summary_text=None,
                messages=[],
                total_tokens=0,
                needs_summary_update=True,
                window_start_message_id=uuid.uuid7(),
            )
        )
    )
    summary_enqueuer = AsyncMock(side_effect=RuntimeError("queue down"))
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
        conversation_memory_service=memory_service,
        summary_enqueuer=summary_enqueuer,
    )
    chat_session = await service.create_session()

    with structlog.testing.capture_logs() as captured_logs:
        result = await service.answer(session_id=chat_session.id, text="Question?")

    assert result.assistant_message.content == "Grounded answer"
    summary_enqueuer.assert_awaited_once()
    assert any(
        log.get("event") == "chat.summary_enqueue_failed"
        and log.get("session_id") == str(chat_session.id)
        for log in captured_logs
    )


@pytest.mark.asyncio
async def test_answer_enqueues_summary_without_window_start_when_window_is_empty(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    memory_service = SimpleNamespace(
        build_memory_block=MagicMock(
            return_value=MemoryBlock(
                summary_text="Existing summary",
                messages=[],
                total_tokens=4096,
                needs_summary_update=True,
                window_start_message_id=None,
            )
        )
    )
    summary_enqueuer = AsyncMock()
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
        conversation_memory_service=memory_service,
        summary_enqueuer=summary_enqueuer,
    )
    chat_session = await service.create_session()

    await service.answer(session_id=chat_session.id, text="Question?")

    summary_enqueuer.assert_awaited_once_with(str(chat_session.id), None)


@pytest.mark.asyncio
async def test_log_audit_is_noop_without_audit_service(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    service, _, _ = _make_service(db_session, persona_context=persona_context)
    chat_session = await service.create_session()
    message = await service._persist_message(
        chat_session,
        role=MessageRole.ASSISTANT,
        content="audit",
        status=MessageStatus.COMPLETE,
        snapshot_id=None,
    )

    await service._log_audit(message=message, retrieval_chunks_count=0, latency_ms=10)


@pytest.mark.asyncio
async def test_log_audit_delegates_to_audit_service(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    audit_service = SimpleNamespace(log_response=AsyncMock())
    service, _, _ = _make_service(db_session, persona_context=persona_context)
    service._audit_service = audit_service
    chat_session = await service.create_session()
    message = await service._persist_message(
        chat_session,
        role=MessageRole.ASSISTANT,
        content="audit",
        status=MessageStatus.COMPLETE,
        snapshot_id=None,
    )

    await service._log_audit(message=message, retrieval_chunks_count=2, latency_ms=20)

    audit_service.log_response.assert_awaited_once()


@pytest.mark.asyncio
async def test_log_audit_swallows_audit_service_errors(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    audit_service = SimpleNamespace(log_response=AsyncMock(side_effect=RuntimeError("boom")))
    service, _, _ = _make_service(db_session, persona_context=persona_context)
    service._audit_service = audit_service
    service._logger = MagicMock()
    chat_session = await service.create_session()
    message = await service._persist_message(
        chat_session,
        role=MessageRole.ASSISTANT,
        content="audit",
        status=MessageStatus.COMPLETE,
        snapshot_id=None,
    )

    await service._log_audit(message=message, retrieval_chunks_count=2, latency_ms=20)

    service._logger.error.assert_called_once()


@pytest.mark.asyncio
async def test_save_partial_on_disconnect_logs_partial_audit(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(db_session, persona_context=persona_context)
    service._audit_service = SimpleNamespace(log_response=AsyncMock())
    chat_session = await service.create_session()
    message = await service._persist_message(
        chat_session,
        role=MessageRole.ASSISTANT,
        content="",
        status=MessageStatus.STREAMING,
        snapshot_id=chat_session.snapshot_id,
        source_ids=[uuid.uuid4()],
    )
    message.created_at = datetime.now(UTC) - timedelta(seconds=2)

    await service.save_partial_on_disconnect(message.id, "partial")

    service._audit_service.log_response.assert_awaited_once()
    assert service._audit_service.log_response.await_args.kwargs["status"] == "partial"
    assert service._audit_service.log_response.await_args.kwargs["latency_ms"] >= 2000


@pytest.mark.asyncio
async def test_save_failed_on_timeout_logs_failed_audit(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, _, _ = _make_service(db_session, persona_context=persona_context)
    service._audit_service = SimpleNamespace(log_response=AsyncMock())
    chat_session = await service.create_session()
    message = await service._persist_message(
        chat_session,
        role=MessageRole.ASSISTANT,
        content="",
        status=MessageStatus.STREAMING,
        snapshot_id=chat_session.snapshot_id,
        source_ids=[uuid.uuid4()],
    )
    message.created_at = datetime.now(UTC) - timedelta(seconds=3)

    await service.save_failed_on_timeout(message.id, "timed out")

    service._audit_service.log_response.assert_awaited_once()
    assert service._audit_service.log_response.await_args.kwargs["status"] == "failed"
    assert service._audit_service.log_response.await_args.kwargs["latency_ms"] >= 3000


@pytest.mark.asyncio
async def test_answer_without_memory_service_stays_backward_compatible(
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
    original_assemble = service._context_assembler.assemble
    service._context_assembler.assemble = MagicMock(side_effect=original_assemble)  # type: ignore[method-assign]

    await service.answer(session_id=chat_session.id, text="Question?")

    assert service._context_assembler.assemble.call_args.kwargs["memory_block"] is None


@pytest.mark.asyncio
async def test_refusal_path_does_not_enqueue_summary(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    memory_service = SimpleNamespace(
        build_memory_block=MagicMock(
            return_value=MemoryBlock(
                summary_text=None,
                messages=[],
                total_tokens=0,
                needs_summary_update=True,
                window_start_message_id=uuid.uuid7(),
            )
        )
    )
    summary_enqueuer = AsyncMock()
    service, _, llm_service = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[],
        conversation_memory_service=memory_service,
        summary_enqueuer=summary_enqueuer,
    )
    chat_session = await service.create_session()

    result = await service.answer(session_id=chat_session.id, text="Question?")

    assert result.assistant_message.content == NO_CONTEXT_REFUSAL
    summary_enqueuer.assert_not_awaited()
    llm_service.complete.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_answer_continues_when_rewrite_persistence_fails(
    db_session: AsyncSession,
    persona_context: PersonaContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_snapshot = await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    active_snapshot_id = active_snapshot.id
    service, retrieval_service, llm_service = _make_service(
        db_session,
        persona_context=persona_context,
        retrieval_result=[_chunk()],
        llm_result=LLMResponse(
            content="Grounded answer",
            model_name="openai/gpt-4o",
            token_count_prompt=12,
            token_count_completion=6,
        ),
        rewritten_query="expanded question",
    )
    chat_session = await service.create_session()

    original_commit = service._session.commit
    commit_calls = 0

    async def _commit_with_one_failure() -> None:
        nonlocal commit_calls
        commit_calls += 1
        if commit_calls == 2:
            raise RuntimeError("rewrite persist failed")
        await original_commit()

    monkeypatch.setattr(service._session, "commit", _commit_with_one_failure)

    with structlog.testing.capture_logs() as logs:
        result = await service.answer(session_id=chat_session.id, text="Question?")

    assert result.assistant_message.content == "Grounded answer"
    assert result.assistant_message.snapshot_id == active_snapshot_id
    retrieval_service.search.assert_awaited_once_with(
        "expanded question",
        snapshot_id=active_snapshot_id,
    )
    llm_service.complete.assert_awaited_once()

    persist_logs = [entry for entry in logs if entry.get("event") == "chat.rewrite_persist_failed"]
    assert len(persist_logs) == 1
    assert persist_logs[0]["error"] == "RuntimeError"

    messages = await _message_rows(db_session, chat_session.id)
    assert [message.role for message in messages] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert messages[0].rewritten_query is None
    assert messages[1].status is MessageStatus.COMPLETE


@pytest.mark.asyncio
async def test_answer_persists_failed_assistant_when_rewrite_raises(
    db_session: AsyncSession,
    persona_context: PersonaContext,
) -> None:
    await _create_snapshot(db_session, status=SnapshotStatus.ACTIVE)
    service, retrieval_service, llm_service = _make_service(
        db_session,
        persona_context=persona_context,
        rewrite_error=RuntimeError("rewrite exploded"),
    )
    chat_session = await service.create_session()

    with pytest.raises(RuntimeError, match="rewrite exploded"):
        await service.answer(session_id=chat_session.id, text="Question?")

    retrieval_service.search.assert_not_awaited()
    llm_service.complete.assert_not_awaited()
    messages = await _message_rows(db_session, chat_session.id)
    assert [message.role for message in messages] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert messages[1].status is MessageStatus.FAILED
