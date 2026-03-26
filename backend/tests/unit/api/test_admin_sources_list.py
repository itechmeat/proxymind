from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import Source
from app.db.models.enums import SourceStatus, SourceType


async def _create_source(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    created_at: datetime | None = None,
    title: str,
    status: SourceStatus,
    knowledge_base_id: uuid.UUID = DEFAULT_KNOWLEDGE_BASE_ID,
) -> Source:
    async with session_factory() as session:
        source = Source(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=knowledge_base_id,
            source_type=SourceType.MARKDOWN,
            title=title,
            file_path=f"sources/{title}.md",
            status=status,
        )
        session.add(source)
        if created_at is not None:
            source.created_at = created_at
        await session.commit()
        await session.refresh(source)
        return source


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_list_sources_returns_empty_list_when_no_sources_exist(api_client) -> None:
    response = await api_client.get("/api/admin/sources")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_list_sources_returns_non_deleted_sources_in_descending_order(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    older = await _create_source(
        session_factory,
        created_at=datetime(2026, 3, 25, 12, 0, tzinfo=timezone.utc),
        title="older",
        status=SourceStatus.READY,
    )
    newer = await _create_source(
        session_factory,
        created_at=datetime(2026, 3, 25, 13, 0, tzinfo=timezone.utc),
        title="newer",
        status=SourceStatus.PROCESSING,
    )

    response = await api_client.get("/api/admin/sources")

    assert response.status_code == 200
    body = response.json()
    assert [item["id"] for item in body] == [str(newer.id), str(older.id)]
    assert body[0] == {
        "id": str(newer.id),
        "title": "newer",
        "source_type": "markdown",
        "status": "processing",
        "description": None,
        "public_url": None,
        "file_size_bytes": None,
        "language": None,
        "created_at": newer.created_at.isoformat().replace("+00:00", "Z"),
    }


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_list_sources_excludes_deleted_and_other_scope_sources(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    visible_source = await _create_source(
        session_factory,
        title="visible",
        status=SourceStatus.READY,
    )
    await _create_source(
        session_factory,
        title="deleted",
        status=SourceStatus.DELETED,
    )
    await _create_source(
        session_factory,
        title="other-scope",
        status=SourceStatus.READY,
        knowledge_base_id=uuid.uuid7(),
    )

    response = await api_client.get("/api/admin/sources")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()] == [str(visible_source.id)]
