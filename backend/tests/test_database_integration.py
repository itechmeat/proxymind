from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Agent, Chunk, Document, DocumentVersion, Message, Session, Source
from app.db.models.dialogue import MessageRole, MessageStatus, SessionChannel, SessionStatus
from app.db.models.knowledge import ChunkStatus, DocumentStatus, SourceStatus, SourceType

EXPECTED_TABLES = {
    "agents",
    "audit_logs",
    "batch_jobs",
    "catalog_items",
    "chunks",
    "document_versions",
    "documents",
    "embedding_profiles",
    "knowledge_snapshots",
    "messages",
    "sessions",
    "sources",
}
EXPECTED_AGENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.mark.asyncio
async def test_schema_integrity(db_session: AsyncSession) -> None:
    tables = await db_session.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
            """
        )
    )
    table_names = {row[0] for row in tables}
    assert EXPECTED_TABLES <= table_names

    indexes = await db_session.execute(
        text(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public' AND tablename = 'messages'
            """
        )
    )
    message_indexes = {row[0] for row in indexes}
    assert "ix_messages_session_id" in message_indexes
    assert "uq_messages_idempotency_key_not_null" in message_indexes

    seed_agent = await db_session.get(Agent, EXPECTED_AGENT_ID)
    assert seed_agent is not None
    assert seed_agent.default_knowledge_base_id is not None


@pytest.mark.asyncio
async def test_agent_crud_sets_timestamps_and_uuid_v7(db_session: AsyncSession) -> None:
    agent = Agent(
        name="Integration Agent",
        description="CRUD verification",
        default_knowledge_base_id=uuid.uuid4(),
        language="en",
        timezone="Europe/Belgrade",
    )
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)

    assert agent.id.version == 7
    assert agent.created_at is not None
    assert agent.updated_at is not None

    original_created_at = agent.created_at
    agent.name = "Updated Integration Agent"
    await db_session.commit()
    await db_session.refresh(agent)

    assert agent.name == "Updated Integration Agent"
    assert agent.created_at == original_created_at
    assert agent.updated_at >= original_created_at


@pytest.mark.asyncio
async def test_relationships_and_fk_constraints(
    db_session: AsyncSession,
    seeded_agent: Agent,
) -> None:
    source_id = uuid.uuid7()
    document_id = uuid.uuid7()
    document_version_id = uuid.uuid7()
    snapshot_id = uuid.uuid4()
    source = Source(
        id=source_id,
        owner_id=seeded_agent.owner_id,
        agent_id=seeded_agent.id,
        knowledge_base_id=seeded_agent.default_knowledge_base_id,
        source_type=SourceType.MARKDOWN,
        title="Source",
        file_path="/tmp/source.md",
        status=SourceStatus.READY,
    )
    document = Document(
        id=document_id,
        owner_id=seeded_agent.owner_id,
        agent_id=seeded_agent.id,
        source=source,
        title="Document",
        status=DocumentStatus.READY,
    )
    document_version = DocumentVersion(
        id=document_version_id,
        document=document,
        version_number=1,
        file_path="/tmp/source-v1.md",
        status=DocumentStatus.READY,
    )
    chunk = Chunk(
        owner_id=seeded_agent.owner_id,
        agent_id=seeded_agent.id,
        knowledge_base_id=seeded_agent.default_knowledge_base_id,
        document_version=document_version,
        snapshot_id=snapshot_id,
        source_id=source_id,
        chunk_index=0,
        text_content="chunk body",
        status=ChunkStatus.INDEXED,
    )
    db_session.add_all([source, document, document_version, chunk])
    await db_session.commit()

    loaded_source = await db_session.scalar(
        select(Source).options(selectinload(Source.documents)).where(Source.id == source.id)
    )
    assert loaded_source is not None
    assert [item.id for item in loaded_source.documents] == [document.id]
    assert document.source_id == source.id
    assert document_version.document_id == document.id
    assert chunk.document_version_id == document_version.id

    orphan_document = Document(
        owner_id=seeded_agent.owner_id,
        agent_id=seeded_agent.id,
        source_id=uuid.uuid4(),
        title="Orphan",
        status=DocumentStatus.PENDING,
    )
    db_session.add(orphan_document)
    with pytest.raises(IntegrityError):
        await db_session.commit()


@pytest.mark.asyncio
async def test_source_soft_delete_preserves_row(
    db_session: AsyncSession,
    seeded_agent: Agent,
) -> None:
    source = Source(
        owner_id=seeded_agent.owner_id,
        agent_id=seeded_agent.id,
        knowledge_base_id=seeded_agent.default_knowledge_base_id,
        source_type=SourceType.TXT,
        title="Soft delete source",
        file_path="/tmp/source.txt",
        status=SourceStatus.READY,
    )
    db_session.add(source)
    await db_session.commit()

    deleted_at = datetime.now(UTC)
    source.deleted_at = deleted_at
    await db_session.commit()
    await db_session.refresh(source)

    assert source.deleted_at == deleted_at
    assert await db_session.get(Source, source.id) is not None


@pytest.mark.asyncio
async def test_invalid_enum_value_is_rejected(db_session: AsyncSession) -> None:
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(
                """
                INSERT INTO sources (id, source_type, title, file_path, status)
                VALUES (:id, 'markdown', 'Invalid Enum Source', '/tmp/invalid.md', 'not_a_status')
                """
            ),
            {"id": str(uuid.uuid4())},
        )
        await db_session.commit()


@pytest.mark.asyncio
async def test_partial_unique_index_on_message_idempotency_key(
    db_session: AsyncSession,
    seeded_agent: Agent,
) -> None:
    session = Session(
        owner_id=seeded_agent.owner_id,
        agent_id=seeded_agent.id,
        snapshot_id=None,
        status=SessionStatus.ACTIVE,
        channel=SessionChannel.WEB,
    )
    db_session.add(session)
    await db_session.commit()
    session_id = session.id

    first_message = Message(
        session_id=session_id,
        role=MessageRole.USER,
        content="hello",
        status=MessageStatus.RECEIVED,
        idempotency_key="dedupe-key",
    )
    second_message = Message(
        session_id=session_id,
        role=MessageRole.USER,
        content="hello again",
        status=MessageStatus.RECEIVED,
        idempotency_key="dedupe-key",
    )
    db_session.add(first_message)
    await db_session.commit()

    db_session.add(second_message)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    nullable_one = Message(
        session_id=session_id,
        role=MessageRole.ASSISTANT,
        content="nullable one",
        status=MessageStatus.COMPLETE,
        idempotency_key=None,
    )
    nullable_two = Message(
        session_id=session_id,
        role=MessageRole.ASSISTANT,
        content="nullable two",
        status=MessageStatus.COMPLETE,
        idempotency_key=None,
    )
    db_session.add_all([nullable_one, nullable_two])
    await db_session.commit()

    rows = await db_session.execute(
        select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
    )
    assert [message.idempotency_key for message in rows.scalars()] == [
        "dedupe-key",
        None,
        None,
    ]
