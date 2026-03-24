from __future__ import annotations

import asyncio
import json
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx_sse import aconnect_sse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import Message, Source
from app.db.models.enums import MessageRole, MessageStatus, SnapshotStatus, SourceStatus, SourceType
from app.db.models.knowledge import KnowledgeSnapshot
from app.services.llm_types import LLMStreamEnd, LLMToken
from app.services.qdrant import RetrievedChunk
from app.services.retrieval import RetrievalError


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


async def _create_source(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_id: uuid.UUID,
    title: str,
    public_url: str | None,
    source_type: SourceType = SourceType.PDF,
) -> Source:
    async with session_factory() as session:
        source = Source(
            id=source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            source_type=source_type,
            title=title,
            public_url=public_url,
            file_path=str(Path(tempfile.gettempdir()) / f"{source_id}.pdf"),
            status=SourceStatus.READY,
        )
        session.add(source)
        await session.commit()
        await session.refresh(source)
        return source


def _retrieved_chunk(
    *,
    source_id: uuid.UUID,
    text_content: str = "retrieved chunk",
    anchor_page: int | None = None,
    anchor_chapter: str | None = None,
    anchor_section: str | None = None,
    anchor_timecode: str | None = None,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id,
        text_content=text_content,
        score=0.91,
        anchor_metadata={
            "anchor_page": anchor_page,
            "anchor_chapter": anchor_chapter,
            "anchor_section": anchor_section,
            "anchor_timecode": anchor_timecode,
        },
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_send_message_returns_sse_stream(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
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
        assert event_source.response.headers["content-type"] == "text/event-stream; charset=utf-8"
        events = [sse async for sse in event_source.aiter_sse()]

    assert events[0].event == "meta"
    assert events[-1].event == "done"
    done_data = json.loads(events[-1].data)
    assert done_data["retrieved_chunks_count"] == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_persists_messages_as_complete(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
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
        assert messages[0].status is MessageStatus.RECEIVED
        assert messages[1].status is MessageStatus.COMPLETE


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_stream_includes_citations_event(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    mock_llm_service,
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    source_id = uuid.uuid4()
    await _create_source(
        session_factory,
        source_id=source_id,
        title="Clean Architecture",
        public_url="https://example.com/clean-architecture",
    )
    mock_retrieval_service.search.return_value = [
        _retrieved_chunk(
            source_id=source_id,
            text_content="Chapter about clean code",
            anchor_page=42,
            anchor_chapter="Chapter 5",
        )
    ]

    async def stream_with_citation(*args, **kwargs):
        yield LLMToken(content="Based on the book [source:1], clean code matters.")
        yield LLMStreamEnd(
            model_name="openai/gpt-4o",
            token_count_prompt=10,
            token_count_completion=1,
        )

    mock_llm_service.stream = AsyncMock(side_effect=stream_with_citation)

    session_id = (await chat_client.post("/api/chat/sessions", json={})).json()["id"]

    async with aconnect_sse(
        chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": session_id, "text": "Question?"},
    ) as event_source:
        events = [sse async for sse in event_source.aiter_sse()]

    event_names = [event.event for event in events]
    assert "citations" in event_names
    assert event_names.index("citations") < event_names.index("done")

    citations_payload = json.loads(next(event.data for event in events if event.event == "citations"))
    assert citations_payload == {
        "citations": [
            {
                "index": 1,
                "source_id": str(source_id),
                "source_title": "Clean Architecture",
                "source_type": "pdf",
                "url": "https://example.com/clean-architecture",
                "anchor": {
                    "page": 42,
                    "chapter": "Chapter 5",
                    "section": None,
                    "timecode": None,
                },
                "text_citation": '"Clean Architecture", Chapter 5, p. 42',
            }
        ]
    }


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_returns_404_for_unknown_session(chat_client: httpx.AsyncClient) -> None:
    response = await chat_client.post(
        "/api/chat/messages",
        json={"session_id": str(uuid.uuid7()), "text": "Q?"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_returns_422_without_snapshot(chat_client: httpx.AsyncClient) -> None:
    session_resp = await chat_client.post("/api/chat/sessions", json={})
    response = await chat_client.post(
        "/api/chat/messages",
        json={"session_id": session_resp.json()["id"], "text": "Q?"},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_returns_409_for_concurrent_stream(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    session_resp = await chat_client.post("/api/chat/sessions", json={})
    session_id = uuid.UUID(session_resp.json()["id"])

    async with session_factory() as session:
        session.add(
            Message(
                id=uuid.uuid7(),
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content="",
                status=MessageStatus.STREAMING,
            )
        )
        await session.commit()

    response = await chat_client.post(
        "/api/chat/messages",
        json={"session_id": str(session_id), "text": "Q?"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_returns_500_and_persists_failed_on_retrieval_error(
    chat_app,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.side_effect = RetrievalError("Retrieval failed")

    transport = httpx.ASGITransport(app=chat_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_resp = await client.post("/api/chat/sessions", json={})
        session_id = session_resp.json()["id"]
        response = await client.post(
            "/api/chat/messages",
            json={"session_id": session_id, "text": "Q?"},
        )

    assert response.status_code == 500

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
        assert [message.status for message in messages] == [
            MessageStatus.RECEIVED,
            MessageStatus.FAILED,
        ]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_idempotency_replay(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
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
        json={"session_id": session_id, "text": "Q?", "idempotency_key": "idem-1"},
    ) as event_source:
        first_events = [sse async for sse in event_source.aiter_sse()]

    async with aconnect_sse(
        chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": session_id, "text": "Q?", "idempotency_key": "idem-1"},
    ) as event_source:
        replay_events = [sse async for sse in event_source.aiter_sse()]

    assert (
        json.loads(first_events[0].data)["message_id"]
        == json.loads(replay_events[0].data)["message_id"]
    )
    assert json.loads(replay_events[-1].data)["retrieved_chunks_count"] == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_session_history_includes_citations(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    mock_llm_service,
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    source_id = uuid.uuid4()
    await _create_source(
        session_factory,
        source_id=source_id,
        title="Clean Architecture",
        public_url="https://example.com/clean-architecture",
    )
    mock_retrieval_service.search.return_value = [
        _retrieved_chunk(
            source_id=source_id,
            text_content="Chapter about clean code",
            anchor_page=42,
            anchor_chapter="Chapter 5",
        )
    ]

    async def stream_with_citation(*args, **kwargs):
        yield LLMToken(content="Based on the book [source:1], clean code matters.")
        yield LLMStreamEnd(
            model_name="openai/gpt-4o",
            token_count_prompt=10,
            token_count_completion=1,
        )

    mock_llm_service.stream = AsyncMock(side_effect=stream_with_citation)

    session_id = (await chat_client.post("/api/chat/sessions", json={})).json()["id"]
    async with aconnect_sse(
        chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": session_id, "text": "Question?"},
    ) as event_source:
        _ = [sse async for sse in event_source.aiter_sse()]

    response = await chat_client.get(f"/api/chat/sessions/{session_id}")

    assert response.status_code == 200
    assistant_message = response.json()["messages"][1]
    assert assistant_message["citations"] == [
        {
            "index": 1,
            "source_id": str(source_id),
            "source_title": "Clean Architecture",
            "source_type": "pdf",
            "url": "https://example.com/clean-architecture",
            "anchor": {
                "page": 42,
                "chapter": "Chapter 5",
                "section": None,
                "timecode": None,
            },
            "text_citation": '"Clean Architecture", Chapter 5, p. 42',
        }
    ]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_session_history_citations_null_vs_empty(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    source_id = uuid.uuid4()
    await _create_source(
        session_factory,
        source_id=source_id,
        title="Guide",
        public_url=None,
    )
    mock_retrieval_service.search.return_value = [_retrieved_chunk(source_id=source_id)]

    session_id = (await chat_client.post("/api/chat/sessions", json={})).json()["id"]
    async with aconnect_sse(
        chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": session_id, "text": "Question?"},
    ) as event_source:
        _ = [sse async for sse in event_source.aiter_sse()]

    response = await chat_client.get(f"/api/chat/sessions/{session_id}")

    assert response.status_code == 200
    user_message, assistant_message = response.json()["messages"]
    assert user_message["citations"] is None
    assert assistant_message["status"] == MessageStatus.COMPLETE.value
    assert assistant_message["citations"] == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_allows_same_idempotency_key_in_different_sessions(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    sample_retrieved_chunk,
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]

    first_session = (await chat_client.post("/api/chat/sessions", json={})).json()["id"]
    second_session = (await chat_client.post("/api/chat/sessions", json={})).json()["id"]

    async with aconnect_sse(
        chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": first_session, "text": "Q?", "idempotency_key": "shared-key"},
    ) as event_source:
        first_events = [sse async for sse in event_source.aiter_sse()]

    async with aconnect_sse(
        chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": second_session, "text": "Q?", "idempotency_key": "shared-key"},
    ) as event_source:
        second_events = [sse async for sse in event_source.aiter_sse()]

    assert (
        json.loads(first_events[0].data)["session_id"]
        != json.loads(second_events[0].data)["session_id"]
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_returns_409_for_idempotency_conflict_while_streaming(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    session_id = uuid.UUID((await chat_client.post("/api/chat/sessions", json={})).json()["id"])

    async with session_factory() as session:
        user_message = Message(
            id=uuid.uuid7(),
            session_id=session_id,
            role=MessageRole.USER,
            content="Q?",
            status=MessageStatus.RECEIVED,
            idempotency_key="idem-1",
        )
        session.add(user_message)
        await session.flush()
        session.add(
            Message(
                id=uuid.uuid7(),
                session_id=session_id,
                role=MessageRole.ASSISTANT,
                content="",
                status=MessageStatus.STREAMING,
                parent_message_id=user_message.id,
            )
        )
        await session.commit()

    response = await chat_client.post(
        "/api/chat/messages",
        json={"session_id": str(session_id), "text": "Q?", "idempotency_key": "idem-1"},
    )

    assert response.status_code == 409


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_emits_timeout_error_and_persists_failed(
    chat_app,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    mock_llm_service,
    sample_retrieved_chunk,
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    chat_app.state.settings.sse_heartbeat_interval_seconds = 10
    chat_app.state.settings.sse_inter_token_timeout_seconds = 1
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]

    async def hanging_stream(*args, **kwargs):
        await asyncio.sleep(2)
        yield LLMToken(content="late")

    mock_llm_service.stream = AsyncMock(side_effect=hanging_stream)

    transport = httpx.ASGITransport(app=chat_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_id = (await client.post("/api/chat/sessions", json={})).json()["id"]
        async with aconnect_sse(
            client,
            "POST",
            "/api/chat/messages",
            json={"session_id": session_id, "text": "Q?"},
        ) as event_source:
            events = [sse async for sse in event_source.aiter_sse()]

    assert events[-1].event == "error"
    assert json.loads(events[-1].data)["detail"] == "LLM response timed out"

    async with session_factory() as session:
        assistant_message = await session.scalar(
            select(Message)
            .where(Message.session_id == uuid.UUID(session_id))
            .where(Message.role == MessageRole.ASSISTANT)
        )
        assert assistant_message is not None
        assert assistant_message.status is MessageStatus.FAILED


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_emits_heartbeat_before_tokens(
    chat_app,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    mock_llm_service,
    sample_retrieved_chunk,
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    chat_app.state.settings.sse_heartbeat_interval_seconds = 1
    chat_app.state.settings.sse_inter_token_timeout_seconds = 5
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]

    async def slow_first_token(*args, **kwargs):
        await asyncio.sleep(2)
        yield LLMToken(content="hello")
        yield LLMStreamEnd(
            model_name="openai/gpt-4o",
            token_count_prompt=1,
            token_count_completion=1,
        )

    mock_llm_service.stream = AsyncMock(side_effect=slow_first_token)

    transport = httpx.ASGITransport(app=chat_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_id = (await client.post("/api/chat/sessions", json={})).json()["id"]

        async with client.stream(
            "POST",
            "/api/chat/messages",
            json={"session_id": session_id, "text": "Q?"},
        ) as response:
            lines: list[str] = []
            async for line in response.aiter_lines():
                lines.append(line)
                if line == "event: done":
                    break

    assert any(line.startswith(": heartbeat") for line in lines)


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_sse_saves_partial_on_early_disconnect(
    chat_app,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    mock_llm_service,
    sample_retrieved_chunk,
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]
    disconnect_event = asyncio.Event()

    async def slow_stream(*args, **kwargs):
        yield LLMToken(content="partial")
        disconnect_event.set()
        await asyncio.sleep(60)
        yield LLMToken(content=" content")
        yield LLMStreamEnd(
            model_name="openai/gpt-4o",
            token_count_prompt=5,
            token_count_completion=2,
        )

    mock_llm_service.stream = AsyncMock(side_effect=slow_stream)

    transport = httpx.ASGITransport(app=chat_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_resp = await client.post("/api/chat/sessions", json={})
        session_id = session_resp.json()["id"]

        async with client.stream(
            "POST",
            "/api/chat/messages",
            json={"session_id": session_id, "text": "Q?"},
        ) as response:
            async for _line in response.aiter_lines():
                if disconnect_event.is_set():
                    break

    deadline = time.monotonic() + 2.0
    while True:
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
            if len(messages) == 1 and messages[0].status is MessageStatus.PARTIAL:
                assert messages[0].content == "partial"
                break

        if time.monotonic() >= deadline:
            assert len(messages) == 1
            assert messages[0].status in {MessageStatus.PARTIAL, MessageStatus.STREAMING}
            if messages[0].status is MessageStatus.PARTIAL:
                assert messages[0].content == "partial"
            break

        await asyncio.sleep(0.1)
