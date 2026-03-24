from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BackgroundTask, BatchJob, Chunk, Document, DocumentVersion, Source
from app.db.models.enums import (
    BackgroundTaskStatus,
    BatchOperationType,
    BatchStatus,
    ChunkStatus,
    DocumentStatus,
    DocumentVersionStatus,
    SourceStatus,
)
from app.services.batch_embedding import (
    BatchEmbeddingClient,
    BatchEmbeddingRequest,
)
from app.services.qdrant import QdrantChunkPoint, QdrantService
from app.workers.tasks.ingestion import _apply_pipeline_success_state
from app.workers.tasks.pipeline import cleanup_qdrant_chunks


class BatchOrchestrator:
    def __init__(
        self,
        *,
        batch_client: BatchEmbeddingClient,
        qdrant_service: QdrantService,
    ) -> None:
        self._batch_client = batch_client
        self._qdrant_service = qdrant_service

    async def create_batch_job_for_threshold(
        self,
        session: AsyncSession,
        *,
        task: BackgroundTask,
        source: Source,
        snapshot_id: uuid.UUID,
        chunk_ids: list[uuid.UUID],
        document_id: uuid.UUID,
        document_version_id: uuid.UUID,
        chunk_count: int,
        token_count_total: int,
        processing_path: str,
        pipeline_version: str,
    ) -> BatchJob:
        batch_job = BatchJob(
            id=uuid.uuid7(),
            agent_id=source.agent_id,
            knowledge_base_id=source.knowledge_base_id,
            snapshot_id=snapshot_id,
            task_id=str(task.id),
            source_ids=[source.id],
            background_task_id=task.id,
            operation_type=BatchOperationType.EMBEDDING,
            status=BatchStatus.PENDING,
            item_count=chunk_count,
            result_metadata={
                "chunk_ids": [str(chunk_id) for chunk_id in chunk_ids],
                "document_id": str(document_id),
                "document_version_id": str(document_version_id),
                "token_count_total": token_count_total,
                "processing_path": processing_path,
                "pipeline_version": pipeline_version,
            },
        )
        session.add(batch_job)
        await session.commit()
        return batch_job

    async def submit_to_gemini(
        self,
        session: AsyncSession,
        *,
        background_task_id: uuid.UUID,
        texts: list[str],
        chunk_ids: list[uuid.UUID],
        display_name: str | None = None,
    ) -> BatchJob:
        batch_job = await session.scalar(
            select(BatchJob)
            .where(BatchJob.background_task_id == background_task_id)
            .with_for_update()
            .limit(1)
        )
        if batch_job is None:
            raise ValueError("Batch job not found for background task")
        if batch_job.batch_operation_name and batch_job.status in {
            BatchStatus.PENDING,
            BatchStatus.PROCESSING,
        }:
            return batch_job

        if len(texts) != len(chunk_ids):
            raise ValueError("Submitted texts and chunk_ids must have the same length")

        metadata = dict(batch_job.result_metadata or {})
        submitted_chunk_ids = [str(chunk_id) for chunk_id in chunk_ids]
        stored_chunk_ids = metadata.get("chunk_ids")
        if stored_chunk_ids is None:
            metadata["chunk_ids"] = submitted_chunk_ids
        elif list(stored_chunk_ids) != submitted_chunk_ids:
            raise ValueError("Submitted chunk_ids do not match stored batch ordering")

        try:
            operation_name = await self._batch_client.create_embedding_batch(
                [
                    BatchEmbeddingRequest(chunk_id=chunk_id, text=text)
                    for chunk_id, text in zip(chunk_ids, texts, strict=True)
                ],
                display_name=display_name,
            )
        except Exception as error:
            batch_job.status = BatchStatus.FAILED
            batch_job.error_message = str(error) or type(error).__name__
            batch_job.completed_at = datetime.now(UTC)
            await session.commit()
            raise
        batch_job.batch_operation_name = operation_name
        batch_job.status = BatchStatus.PROCESSING
        batch_job.request_count = len(chunk_ids)
        batch_job.item_count = len(chunk_ids)
        batch_job.started_at = datetime.now(UTC)
        batch_job.result_metadata = metadata
        await session.commit()
        return batch_job

    async def poll_and_complete(self, session: AsyncSession, *, batch_job: BatchJob) -> BatchJob:
        if not batch_job.batch_operation_name:
            raise ValueError("Cannot poll batch job without a Gemini operation name")

        status = await self._batch_client.get_batch_status(batch_job.batch_operation_name)
        batch_job.status = status.status
        batch_job.last_polled_at = status.last_polled_at
        batch_job.succeeded_count = status.succeeded_count
        batch_job.failed_count = status.failed_count
        batch_job.processed_count = status.succeeded_count + status.failed_count
        batch_job.error_message = status.error_message

        task = (
            await session.get(BackgroundTask, batch_job.background_task_id)
            if batch_job.background_task_id is not None
            else None
        )
        if status.status is BatchStatus.PROCESSING:
            await session.commit()
            return batch_job

        if status.status in {BatchStatus.FAILED, BatchStatus.CANCELLED}:
            batch_job.completed_at = datetime.now(UTC)
            if task is not None:
                task.status = (
                    BackgroundTaskStatus.CANCELLED
                    if status.status is BatchStatus.CANCELLED
                    else BackgroundTaskStatus.FAILED
                )
                task.error_message = status.error_message
                task.completed_at = datetime.now(UTC)
            await session.commit()
            return batch_job

        results = await self._batch_client.get_batch_results(
            batch_job.batch_operation_name,
            expected_count=batch_job.request_count or batch_job.item_count or 0,
        )
        batch_job_id = batch_job.id
        try:
            await self._apply_results(session, batch_job=batch_job, results=results)
        except Exception as error:
            await session.rollback()
            failed_batch_job = await session.get(BatchJob, batch_job_id)
            if failed_batch_job is not None:
                failed_batch_job.status = BatchStatus.FAILED
                failed_batch_job.error_message = str(error) or type(error).__name__
                failed_batch_job.completed_at = datetime.now(UTC)
                if failed_batch_job.background_task_id is not None:
                    failed_task = await session.get(
                        BackgroundTask,
                        failed_batch_job.background_task_id,
                    )
                    if failed_task is not None:
                        failed_task.status = BackgroundTaskStatus.FAILED
                        failed_task.error_message = failed_batch_job.error_message
                        failed_task.completed_at = datetime.now(UTC)
                await session.commit()
            raise
        return batch_job

    async def _apply_results(self, session: AsyncSession, *, batch_job: BatchJob, results) -> None:
        metadata = dict(batch_job.result_metadata or {})
        raw_chunk_ids = metadata.get("chunk_ids") or []
        if len(raw_chunk_ids) != len(results):
            raise ValueError("Stored chunk_ids length does not match Gemini batch results")

        chunk_ids = [uuid.UUID(raw_chunk_id) for raw_chunk_id in raw_chunk_ids]
        chunk_rows = (
            await session.scalars(select(Chunk).where(Chunk.id.in_(chunk_ids)))
        ).all()
        if len(chunk_rows) != len(chunk_ids):
            raise ValueError("Stored batch chunk_ids could not all be loaded from the database")
        chunk_by_id = {chunk.id: chunk for chunk in chunk_rows}

        source_ids = {chunk.source_id for chunk in chunk_rows}
        sources = (
            await session.scalars(select(Source).where(Source.id.in_(source_ids)))
        ).all()
        source_by_id = {source.id: source for source in sources}

        document_version_ids = {chunk.document_version_id for chunk in chunk_rows}
        document_versions = (
            await session.scalars(
                select(DocumentVersion).where(DocumentVersion.id.in_(document_version_ids))
            )
        ).all()
        document_version_by_id = {
            document_version.id: document_version for document_version in document_versions
        }
        document_ids = {document_version.document_id for document_version in document_versions}
        documents = (
            await session.scalars(select(Document).where(Document.id.in_(document_ids)))
        ).all()
        document_by_id = {document.id: document for document in documents}

        succeeded_chunk_ids: list[uuid.UUID] = []
        failed_chunk_ids: list[uuid.UUID] = []
        failed_items: list[dict[str, str]] = []
        qdrant_points: list[QdrantChunkPoint] = []
        for chunk_id, result in zip(chunk_ids, results, strict=True):
            chunk = chunk_by_id[chunk_id]
            if result.embedding is None:
                failed_chunk_ids.append(chunk_id)
                failed_items.append(
                    {
                        "chunk_id": str(chunk_id),
                        "error": result.error_message or "Unknown Gemini batch error",
                    }
                )
                continue
            source = source_by_id[chunk.source_id]
            document_version = document_version_by_id[chunk.document_version_id]
            qdrant_points.append(
                QdrantChunkPoint(
                    chunk_id=chunk.id,
                    vector=result.embedding,
                    snapshot_id=chunk.snapshot_id,
                    source_id=chunk.source_id,
                    document_version_id=chunk.document_version_id,
                    agent_id=chunk.agent_id,
                    knowledge_base_id=chunk.knowledge_base_id,
                    text_content=chunk.text_content,
                    chunk_index=chunk.chunk_index,
                    token_count=chunk.token_count,
                    anchor_page=chunk.anchor_page,
                    anchor_chapter=chunk.anchor_chapter,
                    anchor_section=chunk.anchor_section,
                    anchor_timecode=chunk.anchor_timecode,
                    source_type=source.source_type,
                    language=source.language or self._qdrant_service.bm25_language,
                    status=ChunkStatus.INDEXED,
                )
            )
            succeeded_chunk_ids.append(chunk.id)

        if qdrant_points:
            try:
                await self._qdrant_service.upsert_chunks(qdrant_points)
            except Exception:
                await cleanup_qdrant_chunks(
                    self._qdrant_service,
                    [point.chunk_id for point in qdrant_points],
                )
                raise
            await session.execute(
                update(Chunk)
                .where(Chunk.id.in_(succeeded_chunk_ids))
                .values(status=ChunkStatus.INDEXED)
            )
        if failed_chunk_ids:
            await session.execute(
                update(Chunk)
                .where(Chunk.id.in_(failed_chunk_ids))
                .values(status=ChunkStatus.FAILED)
            )

        batch_job.succeeded_count = len(succeeded_chunk_ids)
        batch_job.failed_count = len(failed_items)
        batch_job.processed_count = len(results)
        batch_job.completed_at = datetime.now(UTC)
        metadata["failed_items"] = failed_items
        batch_job.result_metadata = metadata

        task = (
            await session.get(BackgroundTask, batch_job.background_task_id)
            if batch_job.background_task_id is not None
            else None
        )
        if task is None:
            raise ValueError("Background task not found for batch job")
        if not succeeded_chunk_ids:
            batch_job.status = BatchStatus.FAILED
            batch_job.error_message = "All Gemini batch items failed"
            task.status = BackgroundTaskStatus.FAILED
            task.error_message = "All Gemini batch items failed"
            task.completed_at = datetime.now(UTC)
            for source in source_by_id.values():
                if source.status is not SourceStatus.DELETED:
                    source.status = SourceStatus.FAILED
            for document in document_by_id.values():
                document.status = DocumentStatus.FAILED
            for document_version in document_version_by_id.values():
                document_version.status = DocumentVersionStatus.FAILED
            await session.commit()
            return

        grouped_chunk_ids: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        failed_chunk_ids_by_source: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for chunk_id in succeeded_chunk_ids:
            grouped_chunk_ids[chunk_by_id[chunk_id].source_id].append(chunk_id)
        for chunk_id in failed_chunk_ids:
            failed_chunk_ids_by_source[chunk_by_id[chunk_id].source_id].append(chunk_id)

        for source_id, source in source_by_id.items():
            source_failed_chunk_ids = failed_chunk_ids_by_source.get(source_id, [])
            source_chunk_ids = grouped_chunk_ids.get(source_id, [])
            representative_chunk_id = (source_chunk_ids or source_failed_chunk_ids)[0]
            document_version_id = chunk_by_id[representative_chunk_id].document_version_id
            document_version = document_version_by_id[document_version_id]
            document = document_by_id[document_version.document_id]
            if source_failed_chunk_ids:
                if source.status is not SourceStatus.DELETED:
                    source.status = SourceStatus.FAILED
                document.status = DocumentStatus.FAILED
                document_version.status = DocumentVersionStatus.FAILED
                continue
            await _apply_pipeline_success_state(
                session=session,
                source=source,
                snapshot_id=chunk_by_id[representative_chunk_id].snapshot_id,
                document_id=document_version.document_id,
                document_version_id=document_version.id,
                chunk_ids=source_chunk_ids,
                chunk_count=len(source_chunk_ids),
                pipeline_version=metadata.get("pipeline_version", "s3-06-gemini-batch"),
                embedding_model=self._batch_client.model,
                embedding_dimensions=self._batch_client.dimensions,
            )

        task.status = (
            BackgroundTaskStatus.FAILED if failed_items else BackgroundTaskStatus.COMPLETE
        )
        task.progress = 100
        task.result_metadata = {
            **(task.result_metadata or {}),
            "batch_job_id": str(batch_job.id),
            "failed_items": failed_items,
            "chunk_count": len(succeeded_chunk_ids),
            "embedding_model": self._batch_client.model,
            "embedding_dimensions": self._batch_client.dimensions,
        }
        task.error_message = (
            "Gemini batch completed with failed items" if failed_items else None
        )
        task.completed_at = datetime.now(UTC)

        batch_job.status = BatchStatus.COMPLETE
        batch_job.error_message = task.error_message
        await session.commit()
