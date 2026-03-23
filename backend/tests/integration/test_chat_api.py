from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import httpx
import pytest
from httpx_sse import aconnect_sse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import Message, Session
from app.db.models.enums import MessageRole, SessionChannel, SnapshotStatus
from app.db.models.knowledge import KnowledgeSnapshot
from app.persona.safety import SYSTEM_SAFETY_POLICY


async def _collect_sse_events(
    client: httpx.AsyncClient,
    payload: dict[str, str],
) -> list[object]:
    async with aconnect_sse(client, "POST", "/api/chat/messages", json=payload) as event_source:
        return [event async for event in event_source.aiter_sse()]


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


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_create_session_returns_201_with_explicit_and_default_channel(
    chat_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    active_snapshot = await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)

    explicit = await chat_client.post("/api/chat/sessions", json={"channel": "api"})
    assert explicit.status_code == 201
    assert explicit.json()["channel"] == SessionChannel.API.value
    assert explicit.json()["snapshot_id"] == str(active_snapshot.id)

    default = await chat_client.post("/api/chat/sessions", json={})
    assert default.status_code == 201
    assert default.json()["channel"] == SessionChannel.WEB.value

    no_body = await chat_client.post("/api/chat/sessions", content=b"")
    assert no_body.status_code == 201
    assert no_body.json()["channel"] == SessionChannel.WEB.value


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_send_message_returns_assistant_response(
    chat_client,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    mock_llm_service,
    sample_retrieved_chunk,
) -> None:
    active_snapshot = await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]
    session_response = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_response.json()["id"]

    events = await _collect_sse_events(
        chat_client,
        {"session_id": session_id, "text": "What does it say?"},
    )

    assert events[0].event == "meta"
    assert [json.loads(event.data)["content"] for event in events if event.event == "token"] == [
        "Assistant",
        " answer",
    ]
    assert events[-1].event == "done"
    done = json.loads(events[-1].data)
    assert done["model_name"] == "openai/gpt-4o"
    assert done["retrieved_chunks_count"] == 1

    async with session_factory() as session:
        session_row = await session.get(Session, uuid.UUID(session_id))
        assert session_row is not None
        assert session_row.snapshot_id == active_snapshot.id
        assert session_row.message_count == 2
        messages = list(
            (
                await session.scalars(
                    select(Message)
                    .where(Message.session_id == session_row.id)
                    .order_by(Message.created_at)
                )
            ).all()
        )
        assert [message.role for message in messages] == [MessageRole.USER, MessageRole.ASSISTANT]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_send_message_returns_422_without_snapshot(
    chat_client,
) -> None:
    session_response = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_response.json()["id"]

    response = await chat_client.post(
        "/api/chat/messages",
        json={"session_id": session_id, "text": "What does it say?"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "No active snapshot is available"


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_send_message_returns_404_for_unknown_session(
    chat_client,
) -> None:
    response = await chat_client.post(
        "/api/chat/messages",
        json={"session_id": str(uuid.uuid7()), "text": "What does it say?"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": str(uuid.uuid7()), "text": "   "},
        {"session_id": str(uuid.uuid7())},
    ],
)
async def test_send_message_returns_422_for_empty_or_missing_text(
    chat_client,
    payload: dict[str, str],
) -> None:
    response = await chat_client.post("/api/chat/messages", json=payload)

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_get_session_returns_history(
    chat_client,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    mock_llm_service,
    sample_retrieved_chunk,
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]
    session_response = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_response.json()["id"]
    await _collect_sse_events(
        chat_client,
        {"session_id": session_id, "text": "What does it say?"},
    )

    response = await chat_client.get(f"/api/chat/sessions/{session_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["message_count"] == 2
    assert [message["role"] for message in body["messages"]] == [
        MessageRole.USER.value,
        MessageRole.ASSISTANT.value,
    ]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_get_session_returns_404_for_unknown_session(
    chat_client,
) -> None:
    response = await chat_client.get(f"/api/chat/sessions/{uuid.uuid7()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Session not found"


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_lazy_bind_e2e_create_before_publish_send_after(
    chat_client,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    mock_llm_service,
    sample_retrieved_chunk,
) -> None:
    session_response = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_response.json()["id"]
    assert session_response.json()["snapshot_id"] is None

    active_snapshot = await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]
    events = await _collect_sse_events(
        chat_client,
        {"session_id": session_id, "text": "What does it say?"},
    )

    assert events[0].event == "meta"

    async with session_factory() as session:
        session_row = await session.get(Session, uuid.UUID(session_id))
        assert session_row is not None
        assert session_row.snapshot_id == active_snapshot.id


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_persona_content_reaches_llm_prompt(
    chat_client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    mock_llm_service: SimpleNamespace,
    mock_retrieval_service: SimpleNamespace,
    sample_retrieved_chunk,
) -> None:
    await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]

    session_response = await chat_client.post("/api/chat/sessions", json={})
    session_id = session_response.json()["id"]

    events = await _collect_sse_events(
        chat_client,
        {"session_id": session_id, "text": "Hello"},
    )

    assert events[0].event == "meta"

    sent_messages = mock_llm_service.stream.call_args.args[0]
    system_message = sent_messages[0]["content"]

    assert system_message.startswith(SYSTEM_SAFETY_POLICY)
    assert "Test twin identity" in system_message
    assert "Test twin soul" in system_message
    assert "Test twin behavior" in system_message
