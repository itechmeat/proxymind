from __future__ import annotations

import json
import uuid

import pytest
from httpx_sse import aconnect_sse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import AuditLog, Message
from app.db.models.enums import MessageRole, SnapshotStatus
from app.db.models.knowledge import KnowledgeSnapshot


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
async def test_chat_flow_persists_audit_log_record(
    chat_client,
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service,
    sample_retrieved_chunk,
) -> None:
    active_snapshot = await _create_snapshot(session_factory, status=SnapshotStatus.ACTIVE)
    mock_retrieval_service.search.return_value = [sample_retrieved_chunk]

    session_response = await chat_client.post("/api/chat/sessions", json={})
    session_id = uuid.UUID(session_response.json()["id"])

    async with aconnect_sse(
        chat_client,
        "POST",
        "/api/chat/messages",
        json={"session_id": str(session_id), "text": "What does it say?"},
    ) as event_source:
        events = [event async for event in event_source.aiter_sse()]

    assert events[0].event == "meta"
    assert events[-1].event == "done"
    done_payload = json.loads(events[-1].data)
    assert done_payload["retrieved_chunks_count"] == 1

    async with session_factory() as session:
        assistant_message = await session.scalar(
            select(Message)
            .where(
                Message.session_id == session_id,
                Message.role == MessageRole.ASSISTANT,
            )
            .order_by(Message.created_at.desc())
        )
        audit_logs = list(
            (
                await session.scalars(
                    select(AuditLog)
                    .where(AuditLog.session_id == session_id)
                    .order_by(AuditLog.created_at)
                )
            ).all()
        )

    assert assistant_message is not None
    assert len(audit_logs) == 1

    audit_log = audit_logs[0]
    assert audit_log.agent_id == DEFAULT_AGENT_ID
    assert audit_log.session_id == session_id
    assert audit_log.message_id == assistant_message.id
    assert audit_log.snapshot_id == active_snapshot.id
    assert audit_log.source_ids == [sample_retrieved_chunk.source_id]
    assert audit_log.config_commit_hash == "test-commit-sha"
    assert audit_log.config_content_hash == "test-content-hash"
    assert audit_log.model_name == "openai/gpt-4o"
    assert audit_log.token_count_prompt == 10
    assert audit_log.token_count_completion == 5
    assert audit_log.retrieval_chunks_count == 1
    assert audit_log.latency_ms is not None
    assert audit_log.latency_ms >= 0
    assert audit_log.status == "complete"
