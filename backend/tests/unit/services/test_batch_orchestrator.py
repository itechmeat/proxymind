from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import (
    BackgroundTask,
    BatchJob,
    Chunk,
    ChunkParent,
    Document,
    DocumentVersion,
    EmbeddingProfile,
    KnowledgeSnapshot,
    Source,
)
from app.db.models.enums import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    BatchOperationType,
    BatchStatus,
    ChunkStatus,
    DocumentStatus,
    DocumentVersionStatus,
    ProcessingPath,
    SnapshotStatus,
    SourceStatus,
    SourceType,
)
from app.services.batch_embedding import BatchEmbeddingResultItem
from app.services.batch_orchestrator import BatchOrchestrator


async def _seed_batch_context(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_count: int,
    with_parent: bool = False,
) -> tuple[uuid.UUID, uuid.UUID, list[uuid.UUID]]:
    snapshot_id = uuid.uuid7()
    task_id = uuid.uuid7()
    batch_job_id = uuid.uuid7()
    ordered_chunk_ids: list[uuid.UUID] = []

    async with session_factory() as session:
        snapshot = KnowledgeSnapshot(
            id=snapshot_id,
            agent_id=DEFAULT_AGENT_ID,
            knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
            name="Draft",
            status=SnapshotStatus.DRAFT,
            chunk_count=0,
        )
        task = BackgroundTask(
            id=task_id,
            agent_id=DEFAULT_AGENT_ID,
            task_type=BackgroundTaskType.BATCH_EMBEDDING,
            status=BackgroundTaskStatus.PROCESSING,
            source_id=None,
            result_metadata={"source_ids": [], "snapshot_id": str(snapshot_id)},
        )
        session.add_all([snapshot, task])
        await session.flush()

        source_ids: list[uuid.UUID] = []
        for index in range(source_count):
            source_id = uuid.uuid7()
            source_ids.append(source_id)
            document_id = uuid.uuid7()
            document_version_id = uuid.uuid7()
            chunk_id = uuid.uuid7()
            parent_id = uuid.uuid7() if with_parent else None
            ordered_chunk_ids.append(chunk_id)

            session.add_all(
                [
                    Source(
                        id=source_id,
                        agent_id=DEFAULT_AGENT_ID,
                        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
                        source_type=SourceType.MARKDOWN,
                        title=f"Source {index}",
                        file_path=f"{DEFAULT_AGENT_ID}/{source_id}/doc-{index}.md",
                        file_size_bytes=128,
                        mime_type="text/markdown",
                        language=None,
                        status=SourceStatus.PROCESSING,
                    ),
                    Document(
                        id=document_id,
                        agent_id=DEFAULT_AGENT_ID,
                        source_id=source_id,
                        title=f"Document {index}",
                        status=DocumentStatus.PROCESSING,
                    ),
                    DocumentVersion(
                        id=document_version_id,
                        document_id=document_id,
                        version_number=1,
                        file_path=f"{DEFAULT_AGENT_ID}/{source_id}/doc-{index}.md",
                        processing_path=ProcessingPath.PATH_B,
                        status=DocumentVersionStatus.PROCESSING,
                    ),
                ]
            )
            await session.flush()
            if parent_id is not None:
                session.add(
                    ChunkParent(
                        id=parent_id,
                        agent_id=DEFAULT_AGENT_ID,
                        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
                        document_version_id=document_version_id,
                        snapshot_id=snapshot_id,
                        source_id=source_id,
                        parent_index=0,
                        text_content=f"parent-{index}",
                        token_count=100,
                        anchor_page=index + 1,
                        anchor_chapter=f"Chapter {index}",
                        anchor_section=f"Section {index}",
                        anchor_timecode=None,
                        heading_path=[f"Chapter {index}", f"Section {index}"],
                    )
                )
                await session.flush()

            session.add(
                Chunk(
                    id=chunk_id,
                    agent_id=DEFAULT_AGENT_ID,
                    knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
                    document_version_id=document_version_id,
                    parent_id=parent_id,
                    snapshot_id=snapshot_id,
                    source_id=source_id,
                    chunk_index=0,
                    text_content=f"chunk-{index}",
                    token_count=index + 1,
                    status=ChunkStatus.PENDING,
                )
            )

        task.result_metadata = {
            "source_ids": [str(source_id) for source_id in source_ids],
            "snapshot_id": str(snapshot_id),
        }
        session.add(
            BatchJob(
                id=batch_job_id,
                agent_id=DEFAULT_AGENT_ID,
                knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
                snapshot_id=snapshot_id,
                task_id=str(task_id),
                source_ids=source_ids,
                background_task_id=task_id,
                batch_operation_name="batches/123",
                operation_type=BatchOperationType.EMBEDDING,
                status=BatchStatus.PROCESSING,
                item_count=len(ordered_chunk_ids),
                request_count=len(ordered_chunk_ids),
                result_metadata={
                    "chunk_ids": [str(chunk_id) for chunk_id in ordered_chunk_ids],
                    "pipeline_version": "s3-06-test",
                },
            )
        )
        await session.commit()

    return task_id, batch_job_id, ordered_chunk_ids


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_apply_results_finalizes_multiple_sources_without_losing_task_metadata(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    task_id, batch_job_id, _ = await _seed_batch_context(session_factory, source_count=2)
    qdrant_service = SimpleNamespace(upsert_chunks=AsyncMock(), bm25_language="english")
    orchestrator = BatchOrchestrator(
        batch_client=SimpleNamespace(model="gemini-embedding-2-preview", dimensions=3),
        qdrant_service=qdrant_service,
    )

    async with session_factory() as session:
        batch_job = await session.get(BatchJob, batch_job_id)
        assert batch_job is not None
        await orchestrator._apply_results(
            session,
            batch_job=batch_job,
            results=[
                BatchEmbeddingResultItem(index=0, embedding=[0.1, 0.2, 0.3], error_message=None),
                BatchEmbeddingResultItem(index=1, embedding=[0.4, 0.5, 0.6], error_message=None),
            ],
        )

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        batch_job = await session.get(BatchJob, batch_job_id)
        sources = (await session.scalars(select(Source).order_by(Source.title.asc()))).all()
        documents = (await session.scalars(select(Document).order_by(Document.title.asc()))).all()
        versions = (
            await session.scalars(
                select(DocumentVersion).order_by(DocumentVersion.version_number.asc())
            )
        ).all()
        chunks = (await session.scalars(select(Chunk).order_by(Chunk.text_content.asc()))).all()
        snapshot = await session.scalar(select(KnowledgeSnapshot))
        embedding_profiles = (await session.scalars(select(EmbeddingProfile))).all()

    assert task is not None
    assert batch_job is not None
    assert snapshot is not None
    assert task.status is BackgroundTaskStatus.COMPLETE
    assert task.progress == 100
    assert task.result_metadata is not None
    assert task.result_metadata["batch_job_id"] == str(batch_job_id)
    assert task.result_metadata["chunk_count"] == 2
    assert task.result_metadata["failed_items"] == []
    assert batch_job.status is BatchStatus.COMPLETE
    assert batch_job.succeeded_count == 2
    assert batch_job.failed_count == 0
    assert snapshot.chunk_count == 2
    assert all(source.status is SourceStatus.READY for source in sources)
    assert all(document.status is DocumentStatus.READY for document in documents)
    assert all(version.status is DocumentVersionStatus.READY for version in versions)
    assert all(chunk.status is ChunkStatus.INDEXED for chunk in chunks)
    assert len(embedding_profiles) == 2

    qdrant_service.upsert_chunks.assert_awaited_once()
    qdrant_points = qdrant_service.upsert_chunks.await_args.args[0]
    assert [point.language for point in qdrant_points] == ["english", "english"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_apply_results_includes_persisted_enrichment_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _task_id, batch_job_id, ordered_chunk_ids = await _seed_batch_context(
        session_factory,
        source_count=1,
    )
    qdrant_service = SimpleNamespace(upsert_chunks=AsyncMock(), bm25_language="english")
    orchestrator = BatchOrchestrator(
        batch_client=SimpleNamespace(model="gemini-embedding-2-preview", dimensions=3),
        qdrant_service=qdrant_service,
    )

    async with session_factory() as session:
        chunk = await session.get(Chunk, ordered_chunk_ids[0])
        assert chunk is not None
        chunk.enriched_summary = "summary"
        chunk.enriched_keywords = ["keyword"]
        chunk.enriched_questions = ["question?"]
        chunk.enriched_text = "chunk-0\n\nSummary: summary"
        chunk.enrichment_model = "gemini-2.5-flash"
        chunk.enrichment_pipeline_version = "s9-01-enrichment-v1"
        await session.commit()

    async with session_factory() as session:
        batch_job = await session.get(BatchJob, batch_job_id)
        assert batch_job is not None
        await orchestrator._apply_results(
            session,
            batch_job=batch_job,
            results=[
                BatchEmbeddingResultItem(index=0, embedding=[0.1, 0.2, 0.3], error_message=None)
            ],
        )

    qdrant_service.upsert_chunks.assert_awaited_once()
    qdrant_points = qdrant_service.upsert_chunks.await_args.args[0]
    assert qdrant_points[0].enriched_summary == "summary"
    assert qdrant_points[0].enriched_keywords == ["keyword"]
    assert qdrant_points[0].enriched_questions == ["question?"]
    assert qdrant_points[0].enriched_text == "chunk-0\n\nSummary: summary"
    assert qdrant_points[0].enrichment_model == "gemini-2.5-flash"
    assert qdrant_points[0].enrichment_pipeline_version == "s9-01-enrichment-v1"


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_apply_results_includes_parent_payload_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _task_id, batch_job_id, _ordered_chunk_ids = await _seed_batch_context(
        session_factory,
        source_count=1,
        with_parent=True,
    )
    qdrant_service = SimpleNamespace(upsert_chunks=AsyncMock(), bm25_language="english")
    orchestrator = BatchOrchestrator(
        batch_client=SimpleNamespace(model="gemini-embedding-2-preview", dimensions=3),
        qdrant_service=qdrant_service,
    )

    async with session_factory() as session:
        batch_job = await session.get(BatchJob, batch_job_id)
        assert batch_job is not None
        await orchestrator._apply_results(
            session,
            batch_job=batch_job,
            results=[
                BatchEmbeddingResultItem(index=0, embedding=[0.1, 0.2, 0.3], error_message=None)
            ],
        )

    qdrant_service.upsert_chunks.assert_awaited_once()
    qdrant_point = qdrant_service.upsert_chunks.await_args.args[0][0]
    assert qdrant_point.parent_id is not None
    assert qdrant_point.parent_text_content == "parent-0"
    assert qdrant_point.parent_anchor_section == "Section 0"


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_submit_to_gemini_rejects_chunk_order_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    task_id, _, ordered_chunk_ids = await _seed_batch_context(session_factory, source_count=2)
    batch_client = SimpleNamespace(
        create_embedding_batch=AsyncMock(return_value="batches/new"),
        model="gemini-embedding-2-preview",
        dimensions=3,
    )
    orchestrator = BatchOrchestrator(
        batch_client=batch_client,
        qdrant_service=SimpleNamespace(upsert_chunks=AsyncMock(), bm25_language="english"),
    )

    async with session_factory() as session:
        batch_job = await session.scalar(
            select(BatchJob).where(BatchJob.background_task_id == task_id).limit(1)
        )
        assert batch_job is not None
        batch_job.batch_operation_name = None
        batch_job.status = BatchStatus.PENDING
        await session.commit()

        with pytest.raises(ValueError, match="stored batch ordering"):
            await orchestrator.submit_to_gemini(
                session,
                background_task_id=task_id,
                texts=["chunk-1", "chunk-0"],
                chunk_ids=list(reversed(ordered_chunk_ids)),
            )

    batch_client.create_embedding_batch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_submit_to_gemini_marks_batch_failed_when_client_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    task_id, batch_job_id, ordered_chunk_ids = await _seed_batch_context(
        session_factory,
        source_count=1,
    )
    batch_client = SimpleNamespace(
        create_embedding_batch=AsyncMock(side_effect=RuntimeError("gemini submit failed")),
        model="gemini-embedding-2-preview",
        dimensions=3,
    )
    orchestrator = BatchOrchestrator(
        batch_client=batch_client,
        qdrant_service=SimpleNamespace(upsert_chunks=AsyncMock(), bm25_language="english"),
    )

    async with session_factory() as session:
        batch_job = await session.scalar(
            select(BatchJob).where(BatchJob.background_task_id == task_id).limit(1)
        )
        assert batch_job is not None
        batch_job.batch_operation_name = None
        batch_job.status = BatchStatus.PENDING
        await session.commit()

        with pytest.raises(RuntimeError, match="gemini submit failed"):
            await orchestrator.submit_to_gemini(
                session,
                background_task_id=task_id,
                texts=["chunk-0"],
                chunk_ids=ordered_chunk_ids,
            )

    async with session_factory() as session:
        batch_job = await session.get(BatchJob, batch_job_id)

    assert batch_job is not None
    assert batch_job.status is BatchStatus.FAILED
    assert batch_job.error_message == "gemini submit failed"
    assert batch_job.completed_at is not None


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_apply_results_marks_partial_failures_on_source_and_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    task_id, batch_job_id, _ = await _seed_batch_context(session_factory, source_count=2)
    qdrant_service = SimpleNamespace(
        upsert_chunks=AsyncMock(),
        delete_chunks=AsyncMock(),
        bm25_language="english",
    )
    orchestrator = BatchOrchestrator(
        batch_client=SimpleNamespace(model="gemini-embedding-2-preview", dimensions=3),
        qdrant_service=qdrant_service,
    )

    async with session_factory() as session:
        batch_job = await session.get(BatchJob, batch_job_id)
        assert batch_job is not None
        await orchestrator._apply_results(
            session,
            batch_job=batch_job,
            results=[
                BatchEmbeddingResultItem(index=0, embedding=[0.1, 0.2, 0.3], error_message=None),
                BatchEmbeddingResultItem(index=1, embedding=None, error_message="bad row"),
            ],
        )

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        batch_job = await session.get(BatchJob, batch_job_id)
        sources = (await session.scalars(select(Source).order_by(Source.title.asc()))).all()
        documents = (await session.scalars(select(Document).order_by(Document.title.asc()))).all()
        versions = (
            await session.scalars(
                select(DocumentVersion).order_by(DocumentVersion.version_number.asc())
            )
        ).all()
        chunks = (await session.scalars(select(Chunk).order_by(Chunk.text_content.asc()))).all()

    assert task is not None
    assert batch_job is not None
    assert task.status is BackgroundTaskStatus.FAILED
    assert task.error_message == "Gemini batch completed with failed items"
    assert task.result_metadata is not None
    assert task.result_metadata["failed_items"] == [
        {"chunk_id": str(chunks[1].id), "error": "bad row"}
    ]
    assert batch_job.status is BatchStatus.COMPLETE
    assert batch_job.error_message == "Gemini batch completed with failed items"
    assert sources[0].status is SourceStatus.READY
    assert sources[1].status is SourceStatus.FAILED
    assert documents[0].status is DocumentStatus.READY
    assert documents[1].status is DocumentStatus.FAILED
    assert versions[0].status is DocumentVersionStatus.READY
    assert versions[1].status is DocumentVersionStatus.FAILED
    assert chunks[0].status is ChunkStatus.INDEXED
    assert chunks[1].status is ChunkStatus.FAILED


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_poll_and_complete_marks_batch_failed_when_qdrant_upsert_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    task_id, batch_job_id, _ = await _seed_batch_context(session_factory, source_count=1)
    batch_client = SimpleNamespace(
        model="gemini-embedding-2-preview",
        dimensions=3,
        get_batch_status=AsyncMock(
            return_value=SimpleNamespace(
                status=BatchStatus.COMPLETE,
                last_polled_at=None,
                succeeded_count=1,
                failed_count=0,
                error_message=None,
            )
        ),
        get_batch_results=AsyncMock(
            return_value=[
                BatchEmbeddingResultItem(index=0, embedding=[0.1, 0.2, 0.3], error_message=None)
            ]
        ),
    )
    qdrant_service = SimpleNamespace(
        upsert_chunks=AsyncMock(side_effect=RuntimeError("qdrant upsert failed")),
        delete_chunks=AsyncMock(),
        bm25_language="english",
    )
    orchestrator = BatchOrchestrator(batch_client=batch_client, qdrant_service=qdrant_service)

    async with session_factory() as session:
        batch_job = await session.get(BatchJob, batch_job_id)
        assert batch_job is not None
        with pytest.raises(RuntimeError, match="qdrant upsert failed"):
            await orchestrator.poll_and_complete(session, batch_job=batch_job)

    async with session_factory() as session:
        task = await session.get(BackgroundTask, task_id)
        batch_job = await session.get(BatchJob, batch_job_id)

    assert task is not None
    assert batch_job is not None
    assert task.status is BackgroundTaskStatus.FAILED
    assert task.error_message == "qdrant upsert failed"
    assert batch_job.status is BatchStatus.FAILED
    assert batch_job.error_message == "qdrant upsert failed"
    qdrant_service.delete_chunks.assert_awaited_once()
