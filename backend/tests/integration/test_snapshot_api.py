from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
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


async def _create_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    status: SnapshotStatus,
    chunk_statuses: list[ChunkStatus] | None = None,
    name: str | None = None,
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
            chunk_count=len(chunk_statuses),
            published_at=datetime.now(UTC)
            if status in {SnapshotStatus.PUBLISHED, SnapshotStatus.ACTIVE}
            else None,
            activated_at=datetime.now(UTC) if status is SnapshotStatus.ACTIVE else None,
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


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_list_snapshots_endpoint_supports_filters(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    draft_id = await _create_snapshot(session_factory, status=SnapshotStatus.DRAFT)
    published_id = await _create_snapshot(session_factory, status=SnapshotStatus.PUBLISHED)
    archived_id = await _create_snapshot(session_factory, status=SnapshotStatus.ARCHIVED)
    other_scope_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        knowledge_base_id=uuid.uuid7(),
    )

    response = await api_client.get("/api/admin/snapshots")
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {str(draft_id), str(published_id)}
    assert str(other_scope_id) not in {item["id"] for item in response.json()}

    published_only = await api_client.get("/api/admin/snapshots", params=[("status", "published")])
    assert published_only.status_code == 200
    assert {item["id"] for item in published_only.json()} == {str(published_id)}

    archived_only = await api_client.get("/api/admin/snapshots", params=[("status", "archived")])
    assert archived_only.status_code == 200
    assert {item["id"] for item in archived_only.json()} == {str(archived_id)}

    include_archived = await api_client.get(
        "/api/admin/snapshots",
        params={"include_archived": "true"},
    )
    assert include_archived.status_code == 200
    assert {item["id"] for item in include_archived.json()} == {
        str(draft_id),
        str(published_id),
        str(archived_id),
    }


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_get_snapshot_endpoint_returns_200_and_404(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    snapshot_id = await _create_snapshot(session_factory, status=SnapshotStatus.DRAFT)
    other_scope_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        knowledge_base_id=uuid.uuid7(),
    )

    response = await api_client.get(f"/api/admin/snapshots/{snapshot_id}")
    assert response.status_code == 200
    assert response.json()["id"] == str(snapshot_id)

    wrong_scope = await api_client.get(f"/api/admin/snapshots/{other_scope_id}")
    assert wrong_scope.status_code == 404
    assert wrong_scope.json()["detail"] == "Snapshot not found"

    missing = await api_client.get(f"/api/admin/snapshots/{uuid.uuid7()}")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Snapshot not found"


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_publish_endpoint_returns_200_and_handles_errors(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    empty_scope_id = uuid.uuid7()
    valid_draft_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        chunk_statuses=[ChunkStatus.INDEXED],
    )
    empty_draft_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        knowledge_base_id=empty_scope_id,
    )
    other_scope_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        chunk_statuses=[ChunkStatus.INDEXED],
        knowledge_base_id=uuid.uuid7(),
    )
    active_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.ACTIVE,
        chunk_statuses=[ChunkStatus.INDEXED],
    )

    ok_response = await api_client.post(f"/api/admin/snapshots/{valid_draft_id}/publish")
    assert ok_response.status_code == 200
    assert ok_response.json()["status"] == "published"

    empty_response = await api_client.post(
        f"/api/admin/snapshots/{empty_draft_id}/publish",
        params={"knowledge_base_id": str(empty_scope_id)},
    )
    assert empty_response.status_code == 422
    assert empty_response.json()["detail"] == "Cannot publish: snapshot has no indexed chunks"

    conflict_response = await api_client.post(f"/api/admin/snapshots/{active_id}/publish")
    assert conflict_response.status_code == 409
    assert (
        conflict_response.json()["detail"]
        == "Cannot publish: snapshot status is 'active', expected 'draft'"
    )

    wrong_scope_response = await api_client.post(f"/api/admin/snapshots/{other_scope_id}/publish")
    assert wrong_scope_response.status_code == 404
    assert wrong_scope_response.json()["detail"] == "Snapshot not found"

    missing_response = await api_client.post(f"/api/admin/snapshots/{uuid.uuid7()}/publish")
    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "Snapshot not found"


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_publish_with_activate_and_activate_endpoint_return_200(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    old_active_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.ACTIVE,
        chunk_statuses=[ChunkStatus.INDEXED],
    )
    draft_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        chunk_statuses=[ChunkStatus.INDEXED],
    )
    published_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
    )

    publish_activate_response = await api_client.post(
        f"/api/admin/snapshots/{draft_id}/publish",
        params={"activate": "true"},
    )
    assert publish_activate_response.status_code == 200
    assert publish_activate_response.json()["status"] == "active"

    activate_response = await api_client.post(f"/api/admin/snapshots/{published_id}/activate")
    assert activate_response.status_code == 200
    assert activate_response.json()["status"] == "active"

    archived_active = await api_client.get(
        "/api/admin/snapshots", params={"include_archived": "true"}
    )
    assert archived_active.status_code == 200
    snapshot_map = {item["id"]: item for item in archived_active.json()}
    assert snapshot_map[str(old_active_id)]["status"] == "published"


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_activate_endpoint_returns_409_for_non_published(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    draft_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.DRAFT,
        chunk_statuses=[ChunkStatus.INDEXED],
    )
    other_scope_id = await _create_snapshot(
        session_factory,
        status=SnapshotStatus.PUBLISHED,
        chunk_statuses=[ChunkStatus.INDEXED],
        knowledge_base_id=uuid.uuid7(),
    )

    response = await api_client.post(f"/api/admin/snapshots/{draft_id}/activate")
    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "Cannot activate: snapshot status is 'draft', publish it first"
    )

    wrong_scope_response = await api_client.post(f"/api/admin/snapshots/{other_scope_id}/activate")
    assert wrong_scope_response.status_code == 404
    assert wrong_scope_response.json()["detail"] == "Snapshot not found"
