from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import KnowledgeSnapshot
from app.db.models.enums import SnapshotStatus


class SnapshotService:
    async def get_or_create_draft(
        self,
        session: AsyncSession,
        *,
        agent_id: uuid.UUID,
        knowledge_base_id: uuid.UUID,
    ) -> KnowledgeSnapshot:
        statement = (
            insert(KnowledgeSnapshot)
            .values(
                id=uuid.uuid7(),
                agent_id=agent_id,
                knowledge_base_id=knowledge_base_id,
                name="Auto draft",
                description="Automatically created draft snapshot for ingestion.",
                status=SnapshotStatus.DRAFT,
            )
            .on_conflict_do_nothing(
                index_elements=["agent_id", "knowledge_base_id"],
                index_where=KnowledgeSnapshot.status == SnapshotStatus.DRAFT,
            )
        )
        await session.execute(statement)

        snapshot = await session.scalar(
            select(KnowledgeSnapshot).where(
                KnowledgeSnapshot.agent_id == agent_id,
                KnowledgeSnapshot.knowledge_base_id == knowledge_base_id,
                KnowledgeSnapshot.status == SnapshotStatus.DRAFT,
            )
        )
        if snapshot is None:
            raise RuntimeError("Failed to create or load draft knowledge snapshot")
        return snapshot
