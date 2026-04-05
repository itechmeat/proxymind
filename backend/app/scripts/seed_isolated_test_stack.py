from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.engine import create_database_engine, create_session_factory
from app.db.models import Agent
from app.db.models.enums import SnapshotStatus
from app.db.models.knowledge import KnowledgeSnapshot


async def ensure_e2e_seed(session: AsyncSession) -> uuid.UUID:
    agent = await session.get(Agent, DEFAULT_AGENT_ID)
    if agent is None:
        raise RuntimeError("Default agent is missing; run migrations before seeding the isolated stack")

    existing_snapshot = await session.scalar(
        select(KnowledgeSnapshot).where(
            KnowledgeSnapshot.agent_id == DEFAULT_AGENT_ID,
            KnowledgeSnapshot.knowledge_base_id == DEFAULT_KNOWLEDGE_BASE_ID,
            KnowledgeSnapshot.status == SnapshotStatus.ACTIVE,
        )
    )
    if existing_snapshot is not None:
        if agent.active_snapshot_id != existing_snapshot.id:
            agent.active_snapshot_id = existing_snapshot.id
            await session.commit()
        return existing_snapshot.id

    now = datetime.now(UTC)
    snapshot = KnowledgeSnapshot(
        id=uuid.uuid7(),
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        name="E2E baseline snapshot",
        description="Minimal active snapshot for isolated browser and integration tests.",
        status=SnapshotStatus.ACTIVE,
        published_at=now,
        activated_at=now,
        chunk_count=0,
    )
    session.add(snapshot)
    await session.flush()
    agent.active_snapshot_id = snapshot.id
    await session.commit()
    return snapshot.id


async def _main() -> None:
    settings = get_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)

    try:
        async with session_factory() as session:
            snapshot_id = await ensure_e2e_seed(session)
            print(snapshot_id)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
