from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
from app.db.models.enums import AuditLogStatus
from app.services.audit import AuditService
from app.services.metrics import render_metrics


@pytest.mark.asyncio
async def test_audit_service_persists_chat_audit_log(db_session: AsyncSession) -> None:
    service = AuditService(session=db_session)
    session_id = uuid.uuid7()
    message_id = uuid.uuid7()
    snapshot_id = uuid.uuid7()
    source_ids = [uuid.uuid7()]

    await service.log_response(
        session_id=session_id,
        message_id=message_id,
        snapshot_id=snapshot_id,
        source_ids=source_ids,
        config_commit_hash="commit-123",
        config_content_hash="content-456",
        model_name="openai/gpt-4o",
        token_count_prompt=12,
        token_count_completion=5,
        retrieval_chunks_count=3,
        latency_ms=150,
        status="complete",
    )

    audit_log = await db_session.scalar(
        select(AuditLog).where(AuditLog.message_id == message_id)
    )

    assert audit_log is not None
    assert audit_log.session_id == session_id
    assert audit_log.snapshot_id == snapshot_id
    assert audit_log.source_ids == source_ids
    assert audit_log.status == AuditLogStatus.COMPLETE.value
    assert audit_log.latency_ms == 150
    assert "audit_logs_total" in render_metrics().decode("utf-8")
