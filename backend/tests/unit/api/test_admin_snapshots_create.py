from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import KnowledgeSnapshot
from app.db.models.enums import SnapshotStatus


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_create_snapshot_creates_draft_when_missing(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await api_client.post("/api/admin/snapshots")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    assert body["name"] == "Auto draft"

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(KnowledgeSnapshot)
            .where(
                KnowledgeSnapshot.agent_id == DEFAULT_AGENT_ID,
                KnowledgeSnapshot.knowledge_base_id == DEFAULT_KNOWLEDGE_BASE_ID,
                KnowledgeSnapshot.status == SnapshotStatus.DRAFT,
            )
        )

    assert count == 1


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_create_snapshot_returns_existing_draft_when_present(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    first = await api_client.post("/api/admin/snapshots")
    second = await api_client.post("/api/admin/snapshots")

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]

    async with session_factory() as session:
        count = await session.scalar(
            select(func.count())
            .select_from(KnowledgeSnapshot)
            .where(
                KnowledgeSnapshot.agent_id == DEFAULT_AGENT_ID,
                KnowledgeSnapshot.knowledge_base_id == DEFAULT_KNOWLEDGE_BASE_ID,
                KnowledgeSnapshot.status == SnapshotStatus.DRAFT,
            )
        )

    assert count == 1
