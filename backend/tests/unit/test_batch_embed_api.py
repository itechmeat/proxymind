from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import Chunk, Document, DocumentVersion, Source
from app.db.models.enums import (
    ChunkStatus,
    DocumentStatus,
    DocumentVersionStatus,
    ProcessingPath,
    SourceStatus,
    SourceType,
)


async def _seed_ready_source_with_pending_chunks(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    source_id = uuid.uuid7()
    snapshot_id = uuid.uuid7()
    document_id = uuid.uuid7()
    document_version_id = uuid.uuid7()
    async with session_factory() as session:
        source = Source(
            id=source_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            source_type=SourceType.MARKDOWN,
            title="Batch source",
            file_path=f"{DEFAULT_AGENT_ID}/{source_id}/doc.md",
            file_size_bytes=123,
            mime_type="text/markdown",
            status=SourceStatus.READY,
        )
        document = Document(
            id=document_id,
            agent_id=DEFAULT_AGENT_ID,
            source_id=source_id,
            title="Batch source",
            status=DocumentStatus.READY,
        )
        document_version = DocumentVersion(
            id=document_version_id,
            document_id=document_id,
            version_number=1,
            file_path=source.file_path,
            processing_path=ProcessingPath.PATH_B,
            status=DocumentVersionStatus.READY,
        )
        chunk_one = Chunk(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            document_version_id=document_version_id,
            snapshot_id=snapshot_id,
            source_id=source_id,
            chunk_index=0,
            text_content="one",
            token_count=1,
            status=ChunkStatus.PENDING,
        )
        chunk_two = Chunk(
            id=uuid.uuid7(),
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            document_version_id=document_version_id,
            snapshot_id=snapshot_id,
            source_id=source_id,
            chunk_index=1,
            text_content="two",
            token_count=1,
            status=ChunkStatus.PENDING,
        )
        session.add_all([source, document, document_version, chunk_one, chunk_two])
        await session.commit()
    return source_id, snapshot_id


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_batch_embed_endpoint_creates_task_and_job(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, _ = await _seed_ready_source_with_pending_chunks(session_factory)

    response = await api_client.post(
        "/api/admin/batch-embed",
        json={"source_ids": [str(source_id)]},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["chunk_count"] == 2
    assert body["message"] == "Batch embedding job created"

    task_response = await api_client.get(f"/api/admin/tasks/{body['task_id']}")
    assert task_response.status_code == 200
    assert task_response.json()["task_type"] == "batch_embedding"


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_batch_embed_endpoint_rejects_sources_without_pending_chunks(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    source_id, _ = await _seed_ready_source_with_pending_chunks(session_factory)

    async with session_factory() as session:
        chunks = (await session.scalars(select(Chunk).where(Chunk.source_id == source_id))).all()
        for chunk in chunks:
            chunk.status = ChunkStatus.INDEXED
        await session.commit()

    response = await api_client.post(
        "/api/admin/batch-embed",
        json={"source_ids": [str(source_id)]},
    )

    assert response.status_code == 422
