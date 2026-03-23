from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import Agent, Chunk, Document, DocumentVersion, KnowledgeSnapshot, Source
from app.db.models.enums import (
    ChunkStatus,
    DocumentStatus,
    DocumentVersionStatus,
    ProcessingPath,
    SnapshotStatus,
    SourceStatus,
    SourceType,
)
from app.services.snapshot import (
    SnapshotConflictError,
    SnapshotNotFoundError,
    SnapshotService,
    SnapshotValidationError,
)


async def _create_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: SnapshotStatus,
    chunk_statuses: list[ChunkStatus] | None = None,
    chunk_count_override: int | None = None,
    name: str | None = None,
    activated_at: datetime | None = None,
    knowledge_base_id: uuid.UUID = DEFAULT_KNOWLEDGE_BASE_ID,
) -> uuid.UUID:
    snapshot_id = uuid.uuid7()
    chunk_statuses = chunk_statuses or []

    async with session_factory() as session:
        snapshot = KnowledgeSnapshot(
            id=snapshot_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=knowledge_base_id,
            name=name or f"Snapshot {status.value}",
            status=status,
            chunk_count=(
                chunk_count_override if chunk_count_override is not None else len(chunk_statuses)
            ),
            published_at=datetime.now(UTC)
            if status in {SnapshotStatus.PUBLISHED, SnapshotStatus.ACTIVE}
            else None,
            activated_at=activated_at
            if status in {SnapshotStatus.PUBLISHED, SnapshotStatus.ACTIVE}
            else None,
            archived_at=datetime.now(UTC) if status is SnapshotStatus.ARCHIVED else None,
        )
        session.add(snapshot)

        if status is SnapshotStatus.ACTIVE:
            agent = await session.get(Agent, DEFAULT_AGENT_ID)
            assert agent is not None
            agent.active_snapshot_id = snapshot_id

        if chunk_statuses:
            source = Source(
                id=uuid.uuid7(),
                agent_id=DEFAULT_AGENT_ID,
                knowledge_base_id=knowledge_base_id,
                source_type=SourceType.MARKDOWN,
                title=f"Source for {snapshot_id}",
                file_path=f"{snapshot_id}/source.md",
                status=SourceStatus.READY,
            )
            document = Document(
                id=uuid.uuid7(),
                agent_id=DEFAULT_AGENT_ID,
                source_id=source.id,
                title="Snapshot document",
                status=DocumentStatus.READY,
            )
            document_version = DocumentVersion(
                id=uuid.uuid7(),
                document_id=document.id,
                version_number=1,
                file_path=f"{snapshot_id}/source-v1.md",
                processing_path=ProcessingPath.PATH_B,
                status=DocumentVersionStatus.READY,
            )
            session.add_all([source, document, document_version])
            session.add_all(
                [
                    Chunk(
                        id=uuid.uuid7(),
                        agent_id=DEFAULT_AGENT_ID,
                        knowledge_base_id=knowledge_base_id,
                        document_version_id=document_version.id,
                        snapshot_id=snapshot_id,
                        source_id=source.id,
                        chunk_index=index,
                        text_content=f"chunk {index}",
                        status=chunk_status,
                    )
                    for index, chunk_status in enumerate(chunk_statuses)
                ]
            )

        await session.commit()

    return snapshot_id


async def _get_snapshot(
    session_factory: async_sessionmaker[AsyncSession], snapshot_id: uuid.UUID
) -> KnowledgeSnapshot:
    async with session_factory() as session:
        snapshot = await session.get(KnowledgeSnapshot, snapshot_id)
        assert snapshot is not None
        return snapshot


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_publish_valid_draft_succeeds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        chunk_statuses=[ChunkStatus.INDEXED, ChunkStatus.INDEXED],
    )

    async with session_factory() as session:
        snapshot = await SnapshotService().publish(snapshot_id, session=session)

    assert snapshot.status is SnapshotStatus.PUBLISHED
    assert snapshot.published_at is not None


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_publish_empty_draft_returns_422(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        chunk_count_override=10,
    )

    async with session_factory() as session:
        with pytest.raises(
            SnapshotValidationError,
            match="Cannot publish: snapshot has no indexed chunks",
        ):
            await SnapshotService().publish(snapshot_id, session=session)


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_publish_with_pending_chunks_returns_422(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        chunk_statuses=[ChunkStatus.INDEXED, ChunkStatus.PENDING, ChunkStatus.PENDING],
    )

    async with session_factory() as session:
        with pytest.raises(
            SnapshotValidationError,
            match="Cannot publish: 2 chunks are still processing",
        ):
            await SnapshotService().publish(snapshot_id, session=session)


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_publish_with_failed_chunks_returns_422(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        chunk_statuses=[ChunkStatus.INDEXED, ChunkStatus.FAILED],
    )

    async with session_factory() as session:
        with pytest.raises(
            SnapshotValidationError,
            match="Cannot publish: 1 chunks failed indexing",
        ):
            await SnapshotService().publish(snapshot_id, session=session)


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_publish_non_draft_returns_409(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
    )

    async with session_factory() as session:
        with pytest.raises(
            SnapshotConflictError,
            match="Cannot publish: snapshot status is 'published', expected 'draft'",
        ):
            await SnapshotService().publish(snapshot_id, session=session)


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_activate_published_snapshot_updates_agent_pointer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
    )

    async with session_factory() as session:
        snapshot = await SnapshotService().activate(snapshot_id, session=session)
        agent = await session.get(Agent, DEFAULT_AGENT_ID)
        assert agent is not None
        assert agent.active_snapshot_id == snapshot.id

    assert snapshot.status is SnapshotStatus.ACTIVE
    assert snapshot.activated_at is not None


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
@pytest.mark.parametrize(
    ("status", "expected_detail"),
    [
        (
            SnapshotStatus.DRAFT,
            "Cannot activate: snapshot status is 'draft', publish it first",
        ),
        (
            SnapshotStatus.ACTIVE,
            "Cannot activate: snapshot status is 'active', expected 'published'",
        ),
        (
            SnapshotStatus.ARCHIVED,
            "Cannot activate: snapshot status is 'archived', "
            "archived snapshots cannot be activated",
        ),
    ],
)
async def test_activate_invalid_status_returns_409(
    session_factory: async_sessionmaker[AsyncSession],
    status: SnapshotStatus,
    expected_detail: str,
) -> None:
    snapshot_id = await _create_snapshot(
        session_factory,
        status=status,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 3, 19, tzinfo=UTC),
    )

    async with session_factory() as session:
        with pytest.raises(SnapshotConflictError, match=expected_detail):
            await SnapshotService().activate(snapshot_id, session=session)


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_activate_deactivates_previous_active_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    previous_activation_time = datetime(2026, 3, 19, 12, 0, tzinfo=UTC)
    old_active_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.ACTIVE,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=previous_activation_time,
    )
    target_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
    )

    async with session_factory() as session:
        activated_snapshot = await SnapshotService().activate(target_id, session=session)
        agent = await session.get(Agent, DEFAULT_AGENT_ID)
        assert agent is not None
        assert agent.active_snapshot_id == target_id

    old_snapshot = await _get_snapshot(session_factory, old_active_id)
    assert old_snapshot.status is SnapshotStatus.PUBLISHED
    assert old_snapshot.activated_at == previous_activation_time
    assert activated_snapshot.status is SnapshotStatus.ACTIVE


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_publish_with_activate_convenience_activates_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    old_active_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.ACTIVE,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 3, 19, 11, 0, tzinfo=UTC),
    )
    draft_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        chunk_statuses=[ChunkStatus.INDEXED],
    )

    async with session_factory() as session:
        snapshot = await SnapshotService().publish(draft_id, activate=True, session=session)

    old_snapshot = await _get_snapshot(session_factory, old_active_id)
    assert snapshot.status is SnapshotStatus.ACTIVE
    assert snapshot.published_at is not None
    assert snapshot.activated_at is not None
    assert old_snapshot.status is SnapshotStatus.PUBLISHED


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_list_snapshots_filters_and_excludes_archived_by_default(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    draft_id = await _create_snapshot(session_factory, status=SnapshotStatus.DRAFT)
    published_id = await _create_snapshot(session_factory, status=SnapshotStatus.PUBLISHED)
    archived_id = await _create_snapshot(session_factory, status=SnapshotStatus.ARCHIVED)
    other_scope_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        name="Other scope snapshot",
        knowledge_base_id=uuid.uuid7(),
    )
    other_scope_snapshot = await _get_snapshot(session_factory, other_scope_id)
    service = SnapshotService()

    async with session_factory() as session:
        default_snapshots = await service.list_snapshots(
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            session=session,
        )
        published_only = await service.list_snapshots(
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            statuses=[SnapshotStatus.PUBLISHED],
            session=session,
        )
        archived_only = await service.list_snapshots(
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            statuses=[SnapshotStatus.ARCHIVED],
            session=session,
        )

    default_ids = {snapshot.id for snapshot in default_snapshots}
    assert draft_id in default_ids
    assert published_id in default_ids
    assert archived_id not in default_ids
    assert other_scope_snapshot.id not in default_ids
    assert {snapshot.id for snapshot in published_only} == {published_id}
    assert {snapshot.id for snapshot in archived_only} == {archived_id}


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_ensure_draft_or_rebind_returns_existing_draft(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    draft_id = await _create_snapshot(session_factory, status=SnapshotStatus.DRAFT)

    async with session_factory() as session:
        snapshot = await SnapshotService().ensure_draft_or_rebind(
            session,
            snapshot_id=draft_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )

    assert snapshot.id == draft_id
    assert snapshot.status is SnapshotStatus.DRAFT


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_ensure_draft_or_rebind_rebinds_published_snapshot_to_new_draft(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    published_id = await _create_snapshot(session_factory, status=SnapshotStatus.PUBLISHED)

    async with session_factory() as session:
        rebound_snapshot = await SnapshotService().ensure_draft_or_rebind(
            session,
            snapshot_id=published_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
        )
        await session.commit()

    assert rebound_snapshot.id != published_id
    assert rebound_snapshot.status is SnapshotStatus.DRAFT

    async with session_factory() as session:
        snapshots = (await session.scalars(select(KnowledgeSnapshot))).all()

    assert len(snapshots) == 2


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_rollback_reactivates_previous_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    snapshot_a_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    snapshot_b_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.ACTIVE,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    async with session_factory() as session:
        rolled_back_from, rolled_back_to = await SnapshotService(session).rollback(snapshot_b_id)

    assert rolled_back_from.id == snapshot_b_id
    assert rolled_back_from.status is SnapshotStatus.PUBLISHED
    assert rolled_back_to.id == snapshot_a_id
    assert rolled_back_to.status is SnapshotStatus.ACTIVE

    async with session_factory() as session:
        agent = await session.get(Agent, DEFAULT_AGENT_ID)
        assert agent is not None
        assert agent.active_snapshot_id == snapshot_a_id


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_rollback_non_active_raises_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
    )

    async with session_factory() as session:
        with pytest.raises(SnapshotConflictError, match="Only the active snapshot"):
            await SnapshotService(session).rollback(snapshot_id)


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_rollback_no_previous_raises_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.ACTIVE,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    async with session_factory() as session:
        with pytest.raises(SnapshotConflictError, match="No previously activated"):
            await SnapshotService(session).rollback(snapshot_id)


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_rollback_not_found_raises_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(SnapshotNotFoundError, match="Snapshot not found"):
            await SnapshotService(session).rollback(uuid.uuid4())


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_rollback_twice_toggles_between_two_most_recent_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    snapshot_a_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    snapshot_b_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.ACTIVE,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    async with session_factory() as session:
        _, first_target = await SnapshotService(session).rollback(snapshot_b_id)
    assert first_target.id == snapshot_a_id

    async with session_factory() as session:
        _, second_target = await SnapshotService(session).rollback(snapshot_a_id)
        agent = await session.get(Agent, DEFAULT_AGENT_ID)
        assert agent is not None
        assert agent.active_snapshot_id == snapshot_b_id

    assert second_target.id == snapshot_b_id
    snapshot_a = await _get_snapshot(session_factory, snapshot_a_id)
    snapshot_b = await _get_snapshot(session_factory, snapshot_b_id)
    assert snapshot_a.status is SnapshotStatus.PUBLISHED
    assert snapshot_b.status is SnapshotStatus.ACTIVE


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_rollback_selects_target_only_within_locked_snapshot_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    current_scope_target_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    active_snapshot_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.ACTIVE,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
        activated_at=datetime(2026, 1, 3, tzinfo=UTC),
        knowledge_base_id=uuid.uuid7(),
    )

    async with session_factory() as session:
        _, target = await SnapshotService(session).rollback(active_snapshot_id)

    assert target.id == current_scope_target_id
