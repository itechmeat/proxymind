from __future__ import annotations

from datetime import UTC, datetime
import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import Agent
from app.db.models.enums import SnapshotStatus
from app.db.models.knowledge import KnowledgeSnapshot
from app.scripts.seed_isolated_test_stack import ensure_e2e_seed


async def _load_snapshots(session: AsyncSession) -> list[KnowledgeSnapshot]:
    return list(
        (
            await session.scalars(
                select(KnowledgeSnapshot).where(
                    KnowledgeSnapshot.agent_id == DEFAULT_AGENT_ID,
                    KnowledgeSnapshot.knowledge_base_id == DEFAULT_KNOWLEDGE_BASE_ID,
                )
            )
        ).all()
    )


async def test_ensure_e2e_seed_creates_active_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    committed_data_cleanup: None,
) -> None:
    async with session_factory() as session:
        snapshot_id = await ensure_e2e_seed(session)

    async with session_factory() as session:
        agent = await session.get(Agent, DEFAULT_AGENT_ID)
        snapshots = await _load_snapshots(session)

        assert agent is not None
        assert agent.active_snapshot_id == snapshot_id
        assert len(snapshots) == 1
        assert snapshots[0].id == snapshot_id
        assert snapshots[0].status is SnapshotStatus.ACTIVE
        assert snapshots[0].chunk_count == 0


async def test_ensure_e2e_seed_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
    committed_data_cleanup: None,
) -> None:
    async with session_factory() as session:
        first_snapshot_id = await ensure_e2e_seed(session)
        second_snapshot_id = await ensure_e2e_seed(session)

    async with session_factory() as session:
        agent = await session.get(Agent, DEFAULT_AGENT_ID)
        snapshots = await _load_snapshots(session)

        assert agent is not None
        assert first_snapshot_id == second_snapshot_id
        assert agent.active_snapshot_id == first_snapshot_id
        assert len(snapshots) == 1


async def test_ensure_e2e_seed_reuses_existing_active_snapshot_and_syncs_agent_pointer(
    session_factory: async_sessionmaker[AsyncSession],
    committed_data_cleanup: None,
) -> None:
    async with session_factory() as session:
        snapshot = KnowledgeSnapshot(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            name="Seed snapshot",
            description="A",
            status=SnapshotStatus.ACTIVE,
            published_at=datetime.now(UTC),
            activated_at=datetime.now(UTC),
            chunk_count=0,
        )
        agent = await session.get(Agent, DEFAULT_AGENT_ID)
        assert agent is not None
        agent.active_snapshot_id = None
        session.add(snapshot)
        await session.commit()

        snapshot_id = await ensure_e2e_seed(session)

    async with session_factory() as session:
        agent = await session.get(Agent, DEFAULT_AGENT_ID)
        snapshots = await _load_snapshots(session)

        assert agent is not None
        assert snapshot_id == snapshot.id
        assert agent.active_snapshot_id == snapshot.id
        assert len(snapshots) == 1
