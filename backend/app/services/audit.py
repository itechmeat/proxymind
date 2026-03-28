from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_AGENT_ID
from app.db.models import AuditLog
from app.db.models.enums import AuditLogStatus
from app.services.metrics import AUDIT_LOG_COUNT

logger = structlog.get_logger(__name__)


class AuditService:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def log_response(
        self,
        *,
        session_id: uuid.UUID | None,
        message_id: uuid.UUID | None,
        snapshot_id: uuid.UUID | None,
        source_ids: list[uuid.UUID] | None,
        config_commit_hash: str | None,
        config_content_hash: str | None,
        model_name: str | None,
        token_count_prompt: int | None,
        token_count_completion: int | None,
        retrieval_chunks_count: int | None,
        latency_ms: int | None,
        status: AuditLogStatus | str,
        agent_id: uuid.UUID = DEFAULT_AGENT_ID,
    ) -> None:
        resolved_status = AuditLogStatus(status)
        audit_log = AuditLog(
            id=uuid.uuid7(),
            agent_id=agent_id,
            session_id=session_id,
            message_id=message_id,
            snapshot_id=snapshot_id,
            source_ids=source_ids,
            config_commit_hash=config_commit_hash,
            config_content_hash=config_content_hash,
            model_name=model_name,
            token_count_prompt=token_count_prompt,
            token_count_completion=token_count_completion,
            retrieval_chunks_count=retrieval_chunks_count,
            latency_ms=latency_ms,
            status=resolved_status.value,
        )
        self._session.add(audit_log)
        try:
            await self._session.commit()
            AUDIT_LOG_COUNT.inc()
            logger.info(
                "audit.response_logged",
                audit_id=str(audit_log.id),
                session_id=str(session_id) if session_id else None,
                message_id=str(message_id) if message_id else None,
                snapshot_id=str(snapshot_id) if snapshot_id else None,
                status=resolved_status.value,
            )
        except Exception as error:
            await self._session.rollback()
            logger.warning(
                "audit.response_log_failed",
                error=error.__class__.__name__,
                session_id=str(session_id) if session_id else None,
                message_id=str(message_id) if message_id else None,
                snapshot_id=str(snapshot_id) if snapshot_id else None,
                status=resolved_status.value,
            )


__all__ = ["AuditService"]
