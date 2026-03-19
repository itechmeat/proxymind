from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import KnowledgeSnapshot
from app.db.models.enums import SnapshotStatus
from app.services.snapshot import SnapshotService


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_get_or_create_draft_creates_and_reuses_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SnapshotService()

    async with session_factory() as session:
        first = await service.get_or_create_draft(
            session,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )
        await session.commit()

    async with session_factory() as session:
        second = await service.get_or_create_draft(
            session,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )
        await session.commit()

        snapshots = (
            await session.scalars(
                select(KnowledgeSnapshot).where(KnowledgeSnapshot.status == SnapshotStatus.DRAFT)
            )
        ).all()

    assert first.id == second.id
    assert len(snapshots) == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_get_or_create_draft_keeps_scopes_separate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    service = SnapshotService()
    other_knowledge_base_id = uuid.uuid7()

    async with session_factory() as session:
        first = await service.get_or_create_draft(
            session,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )
        second = await service.get_or_create_draft(
            session,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=other_knowledge_base_id,
        )
        await session.commit()

    assert first.id != second.id


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_partial_unique_index_allows_only_one_draft_per_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(
            KnowledgeSnapshot(
                id=uuid.uuid7(),
                agent_id=DEFAULT_AGENT_ID,
                knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
                name="Draft 1",
                status=SnapshotStatus.DRAFT,
            )
        )
        await session.commit()

    async with session_factory() as session:
        session.add(
            KnowledgeSnapshot(
                id=uuid.uuid7(),
                agent_id=DEFAULT_AGENT_ID,
                knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
                name="Draft 2",
                status=SnapshotStatus.DRAFT,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()

        session.add(
            KnowledgeSnapshot(
                id=uuid.uuid7(),
                agent_id=DEFAULT_AGENT_ID,
                knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
                name="Published",
                status=SnapshotStatus.PUBLISHED,
            )
        )
        await session.commit()
