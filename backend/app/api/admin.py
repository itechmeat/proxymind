from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.batch_schemas import (
    BatchEmbedRequest,
    BatchEmbedResponse,
    BatchJobDetailResponse,
    BatchJobListResponse,
    BatchJobResponse,
)
from app.api.auth import verify_admin_key
from app.api.catalog_schemas import (
    CatalogItemCreate,
    CatalogItemDetail,
    CatalogItemListResponse,
    CatalogItemResponse,
    CatalogItemUpdate,
    LinkedSourceInfo,
    SourceUpdateRequest,
)
from app.api.dependencies import (
    get_catalog_service,
    get_embedding_service,
    get_qdrant_service,
    get_snapshot_service,
    get_source_service,
    get_storage_service,
    get_task_enqueuer,
)
from app.api.schemas import (
    KeywordSearchRequest,
    KeywordSearchResponse,
    KeywordSearchResult,
    SourceUploadMetadata,
    SourceUploadResponse,
    TaskStatusResponse,
)
from app.api.snapshot_schemas import (
    DraftTestAnchor,
    DraftTestRequest,
    DraftTestResponse,
    DraftTestResult,
    RetrievalMode,
    RollbackResponse,
    RollbackSnapshotResponse,
    SnapshotResponse,
)
from app.api.source_schemas import SourceDeleteResponse, SourceListItem
from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models import BackgroundTask, BatchJob, Chunk, Source
from app.db.models.enums import (
    BackgroundTaskStatus,
    BackgroundTaskType,
    BatchOperationType,
    CatalogItemType,
    BatchStatus,
    ChunkStatus,
    SnapshotStatus,
    SourceStatus,
)
from app.db.session import get_session
from app.services.embedding import EmbeddingService
from app.services.catalog import (
    CatalogItemConflictError,
    CatalogItemNotFoundError,
    CatalogService,
)
from app.services.qdrant import QdrantService
from app.services.snapshot import (
    SnapshotConflictError,
    SnapshotNotFoundError,
    SnapshotService,
    SnapshotValidationError,
)
from app.services.source import (
    SourcePersistenceError,
    SourceService,
    TaskEnqueueError,
    TaskEnqueuer,
)
from app.services.source_delete import SourceDeleteService, SourceNotFoundError
from app.services.storage import (
    StorageService,
    determine_mime_type,
    determine_source_type,
    validate_file_extension,
)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
    dependencies=[Depends(verify_admin_key)],
)
UPLOAD_READ_CHUNK_SIZE = 64 * 1024


def get_admin_agent_id(
    agent_id: uuid.UUID | None = Query(default=None),
) -> uuid.UUID:
    return agent_id or DEFAULT_AGENT_ID


def get_admin_knowledge_base_id(
    knowledge_base_id: uuid.UUID | None = Query(default=None),
) -> uuid.UUID:
    return knowledge_base_id or DEFAULT_KNOWLEDGE_BASE_ID


AdminAgentId = Annotated[uuid.UUID, Depends(get_admin_agent_id)]
AdminKnowledgeBaseId = Annotated[uuid.UUID, Depends(get_admin_knowledge_base_id)]


def _raise_snapshot_http_error(error: Exception) -> None:
    if isinstance(error, SnapshotNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, SnapshotConflictError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, SnapshotValidationError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


@router.get("/auth/me")
async def get_admin_auth_me() -> dict[str, bool]:
    return {"ok": True}


async def _read_upload_content(file: UploadFile, max_size_bytes: int) -> bytes:
    content = bytearray()

    while chunk := await file.read(UPLOAD_READ_CHUNK_SIZE):
        content.extend(chunk)
        if len(content) > max_size_bytes:
            raise HTTPException(
                status_code=413,
                detail="Uploaded file exceeds the configured size limit",
            )

    if not content:
        raise HTTPException(status_code=422, detail="Uploaded file must not be empty")

    return bytes(content)


@router.post(
    "/sources",
    response_model=SourceUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_source(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    metadata: Annotated[str, Form(...)],
    storage_service: Annotated[StorageService, Depends(get_storage_service)],
    source_service: Annotated[SourceService, Depends(get_source_service)],
    skip_embedding: Annotated[bool, Query()] = False,
) -> SourceUploadResponse:
    try:
        try:
            upload_metadata = SourceUploadMetadata.model_validate_json(metadata)
        except ValidationError as error:
            raise HTTPException(
                status_code=422,
                detail=error.errors(include_url=False),
            ) from error

        filename = file.filename or ""
        try:
            validate_file_extension(filename)
            source_type = determine_source_type(filename)
            mime_type = determine_mime_type(filename)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        max_size_bytes = request.app.state.settings.upload_max_file_size_mb * 1024 * 1024
        content = await _read_upload_content(file, max_size_bytes)

        source_id = uuid.uuid7()
        object_key = storage_service.generate_object_key(DEFAULT_AGENT_ID, source_id, filename)

        try:
            await storage_service.upload(object_key, content, mime_type)
        except Exception as error:
            raise HTTPException(
                status_code=500,
                detail="Failed to upload file to storage",
            ) from error

        try:
            bundle = await source_service.create_source_and_task(
                source_id=source_id,
                metadata=upload_metadata,
                source_type=source_type,
                file_path=object_key,
                file_size_bytes=len(content),
                mime_type=mime_type,
                skip_embedding=skip_embedding,
            )
        except SourcePersistenceError as error:
            await storage_service.delete(object_key)
            raise HTTPException(
                status_code=500,
                detail="Failed to persist source metadata",
            ) from error
        except TaskEnqueueError as error:
            raise HTTPException(
                status_code=500,
                detail="Failed to enqueue ingestion task",
            ) from error
    finally:
        await file.close()

    return SourceUploadResponse(
        source_id=bundle.source.id,
        task_id=bundle.task.id,
        status=bundle.task.status.value.lower(),
        file_path=bundle.source.file_path,
        message="Source uploaded and queued for ingestion.",
    )


@router.post(
    "/batch-embed",
    response_model=BatchEmbedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_batch_embed_job(
    request: Request,
    payload: BatchEmbedRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    task_enqueuer: Annotated[TaskEnqueuer, Depends(get_task_enqueuer)],
) -> BatchEmbedResponse:
    source_ids = list(dict.fromkeys(payload.source_ids))
    source_result = await session.scalars(select(Source).where(Source.id.in_(source_ids)))
    sources = source_result.all()
    if len(sources) != len(source_ids):
        raise HTTPException(status_code=422, detail="All source_ids must exist")

    scoped_agent_ids = {source.agent_id for source in sources}
    scoped_kb_ids = {source.knowledge_base_id for source in sources}
    if len(scoped_agent_ids) != 1 or len(scoped_kb_ids) != 1:
        raise HTTPException(status_code=422, detail="All sources must belong to one scope")
    if any(source.status is not SourceStatus.READY for source in sources):
        raise HTTPException(status_code=422, detail="All sources must be READY")

    active_batch = await session.scalar(
        select(BatchJob)
        .where(BatchJob.status.in_((BatchStatus.PENDING, BatchStatus.PROCESSING)))
        .where(BatchJob.source_ids.op("&&")(source_ids))
        .limit(1)
    )
    if active_batch is not None:
        raise HTTPException(
            status_code=409,
            detail="Active batch already exists for these sources",
        )

    chunks = (
        await session.scalars(
            select(Chunk)
            .where(Chunk.source_id.in_(source_ids), Chunk.status == ChunkStatus.PENDING)
            .order_by(Chunk.source_id.asc(), Chunk.chunk_index.asc())
        )
    ).all()
    if not chunks:
        raise HTTPException(status_code=422, detail="Sources have no pending chunks")
    pending_source_ids = {chunk.source_id for chunk in chunks}
    missing_pending_sources = [
        str(source_id) for source_id in source_ids if source_id not in pending_source_ids
    ]
    if missing_pending_sources:
        raise HTTPException(
            status_code=422,
            detail=(
                "Each source must have at least one pending chunk: "
                + ", ".join(missing_pending_sources)
            ),
        )

    snapshot_ids = {chunk.snapshot_id for chunk in chunks}
    if len(snapshot_ids) != 1:
        raise HTTPException(status_code=422, detail="Pending chunks must share one snapshot")

    chunk_count = len(chunks)
    if chunk_count > request.app.state.settings.batch_max_items_per_request:
        raise HTTPException(
            status_code=422,
            detail=(
                "Batch exceeds batch_max_items_per_request. Split source_ids into smaller groups"
            ),
        )

    task = BackgroundTask(
        id=uuid.uuid7(),
        agent_id=sources[0].agent_id,
        task_type=BackgroundTaskType.BATCH_EMBEDDING,
        status=BackgroundTaskStatus.PENDING,
        source_id=None,
        result_metadata={
            "source_ids": [str(source_id) for source_id in source_ids],
            "knowledge_base_id": str(sources[0].knowledge_base_id),
            "snapshot_id": str(next(iter(snapshot_ids))),
        },
    )
    batch_job = BatchJob(
        id=uuid.uuid7(),
        agent_id=sources[0].agent_id,
        knowledge_base_id=sources[0].knowledge_base_id,
        snapshot_id=next(iter(snapshot_ids)),
        task_id=str(task.id),
        source_ids=source_ids,
        background_task_id=task.id,
        operation_type=BatchOperationType.EMBEDDING,
        status=BatchStatus.PENDING,
        item_count=chunk_count,
        result_metadata={
            "chunk_ids": [str(chunk.id) for chunk in chunks],
        },
    )
    session.add_all([task, batch_job])
    await session.commit()

    enqueued_job_id: str | None = None
    try:
        enqueued_job_id = await task_enqueuer.enqueue_batch_embed(task.id)
        task.arq_job_id = enqueued_job_id
        await session.commit()
    except Exception as error:
        await session.rollback()
        task = await session.get(BackgroundTask, task.id)
        batch_job = await session.get(BatchJob, batch_job.id)
        if enqueued_job_id is not None and task is not None:
            task.arq_job_id = enqueued_job_id
            await session.commit()
        elif task is not None:
            task.status = BackgroundTaskStatus.FAILED
            task.error_message = f"Failed to enqueue batch embedding task: {error}"
            task.completed_at = datetime.now(UTC)
            if batch_job is not None:
                batch_job.status = BatchStatus.FAILED
                batch_job.error_message = str(error)
                batch_job.completed_at = datetime.now(UTC)
            await session.commit()
            raise HTTPException(
                status_code=500,
                detail="Failed to enqueue batch embedding task",
            ) from error
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to reconcile batch embedding enqueue state",
            ) from error

    return BatchEmbedResponse(
        task_id=task.id,
        batch_job_id=batch_job.id,
        chunk_count=chunk_count,
        message="Batch embedding job created",
    )


@router.get("/batch-jobs", response_model=BatchJobListResponse)
async def list_batch_jobs(
    session: Annotated[AsyncSession, Depends(get_session)],
    status_filter: Annotated[BatchStatus | None, Query(alias="status")] = None,
    operation_type: BatchOperationType | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> BatchJobListResponse:
    filters = []
    if status_filter is not None:
        filters.append(BatchJob.status == status_filter)
    if operation_type is not None:
        filters.append(BatchJob.operation_type == operation_type)

    total = int(
        await session.scalar(select(func.count()).select_from(BatchJob).where(*filters)) or 0
    )
    items = (
        await session.scalars(
            select(BatchJob)
            .where(*filters)
            .order_by(BatchJob.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return BatchJobListResponse(
        items=[BatchJobResponse.from_batch_job(item) for item in items],
        total=total,
    )


@router.get("/catalog", response_model=CatalogItemListResponse)
async def list_catalog_items(
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    item_type: CatalogItemType | None = None,
    is_active: bool = True,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
) -> CatalogItemListResponse:
    items, total = await catalog_service.list_items(
        agent_id=agent_id,
        item_type=item_type,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    response_items = [
        CatalogItemResponse.model_validate(item).model_copy(
            update={
                "linked_sources_count": sum(1 for source in item.sources if source.deleted_at is None)
            }
        )
        for item in items
    ]
    return CatalogItemListResponse(
        items=response_items,
        total=total,
    )


@router.get("/catalog/{catalog_item_id}", response_model=CatalogItemDetail)
async def get_catalog_item(
    catalog_item_id: uuid.UUID,
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
) -> CatalogItemDetail:
    try:
        item = await catalog_service.get_by_id(catalog_item_id, agent_id=agent_id)
    except CatalogItemNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    linked_sources = [
        LinkedSourceInfo.model_validate(source)
        for source in item.sources
        if source.deleted_at is None
    ]
    base_response = CatalogItemResponse.model_validate(item).model_copy(
        update={"linked_sources_count": len(linked_sources)}
    )
    return CatalogItemDetail(
        **base_response.model_dump(),
        linked_sources=linked_sources,
    )


@router.post("/catalog", response_model=CatalogItemResponse, status_code=status.HTTP_201_CREATED)
async def create_catalog_item(
    payload: CatalogItemCreate,
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
) -> CatalogItemResponse:
    try:
        item = await catalog_service.create(payload, agent_id=agent_id)
    except CatalogItemConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return CatalogItemResponse.model_validate(item)


@router.patch("/catalog/{catalog_item_id}", response_model=CatalogItemResponse)
async def update_catalog_item(
    catalog_item_id: uuid.UUID,
    payload: CatalogItemUpdate,
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
) -> CatalogItemResponse:
    try:
        item = await catalog_service.update(catalog_item_id, payload, agent_id=agent_id)
    except CatalogItemNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except CatalogItemConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return CatalogItemResponse.model_validate(item)


@router.delete("/catalog/{catalog_item_id}", response_model=CatalogItemResponse)
async def delete_catalog_item(
    catalog_item_id: uuid.UUID,
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
) -> CatalogItemResponse:
    try:
        item = await catalog_service.soft_delete(catalog_item_id, agent_id=agent_id)
    except CatalogItemNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return CatalogItemResponse.model_validate(item)


@router.get("/batch-jobs/{batch_job_id}", response_model=BatchJobDetailResponse)
async def get_batch_job_detail(
    batch_job_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> BatchJobDetailResponse:
    batch_job = await session.get(BatchJob, batch_job_id)
    if batch_job is None:
        raise HTTPException(status_code=404, detail="Batch job not found")
    return BatchJobDetailResponse.from_batch_job(batch_job)


@router.get("/sources", response_model=list[SourceListItem])
async def list_sources(
    session: Annotated[AsyncSession, Depends(get_session)],
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
    knowledge_base_id: AdminKnowledgeBaseId = DEFAULT_KNOWLEDGE_BASE_ID,
) -> list[SourceListItem]:
    sources = (
        await session.scalars(
            select(Source)
            .where(
                Source.agent_id == agent_id,
                Source.knowledge_base_id == knowledge_base_id,
                Source.status != SourceStatus.DELETED,
            )
            .order_by(Source.created_at.desc())
        )
    ).all()
    return [SourceListItem.model_validate(source) for source in sources]


@router.patch("/sources/{source_id}", response_model=SourceListItem)
async def update_source(
    source_id: uuid.UUID,
    payload: SourceUpdateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    catalog_service: Annotated[CatalogService, Depends(get_catalog_service)],
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
    knowledge_base_id: AdminKnowledgeBaseId = DEFAULT_KNOWLEDGE_BASE_ID,
) -> SourceListItem:
    source = await session.scalar(
        select(Source).where(
            Source.id == source_id,
            Source.agent_id == agent_id,
            Source.knowledge_base_id == knowledge_base_id,
            Source.deleted_at.is_(None),
            Source.status != SourceStatus.DELETED,
        )
    )
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "catalog_item_id" in update_data:
        catalog_item_id = update_data["catalog_item_id"]
        if catalog_item_id is None:
            source.catalog_item_id = None
        else:
            try:
                await catalog_service.get_by_id(catalog_item_id, agent_id=agent_id)
            except CatalogItemNotFoundError as error:
                raise HTTPException(status_code=404, detail=str(error)) from error
            source.catalog_item_id = catalog_item_id

        await session.commit()
        await session.refresh(source)

    return SourceListItem.model_validate(source)


@router.delete("/sources/{source_id}", response_model=SourceDeleteResponse)
async def delete_source(
    source_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    qdrant_service: Annotated[QdrantService, Depends(get_qdrant_service)],
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
    knowledge_base_id: AdminKnowledgeBaseId = DEFAULT_KNOWLEDGE_BASE_ID,
) -> SourceDeleteResponse:
    service = SourceDeleteService(session, qdrant_service=qdrant_service)
    try:
        result = await service.soft_delete(
            source_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
        )
    except SourceNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return SourceDeleteResponse(
        id=result.source.id,
        title=result.source.title,
        source_type=result.source.source_type,
        status=result.source.status,
        deleted_at=result.source.deleted_at,
        warnings=result.warnings,
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: uuid.UUID,
    source_service: Annotated[SourceService, Depends(get_source_service)],
) -> TaskStatusResponse:
    task = await source_service.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Background task not found")
    return TaskStatusResponse.from_task(task)


@router.get("/snapshots", response_model=list[SnapshotResponse])
async def list_snapshots(
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
    knowledge_base_id: AdminKnowledgeBaseId = DEFAULT_KNOWLEDGE_BASE_ID,
    status_filters: Annotated[list[SnapshotStatus] | None, Query(alias="status")] = None,
    include_archived: bool = False,
) -> list[SnapshotResponse]:
    snapshots = await snapshot_service.list_snapshots(
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
        statuses=status_filters,
        include_archived=include_archived,
    )
    return [SnapshotResponse.model_validate(snapshot) for snapshot in snapshots]


@router.post(
    "/snapshots",
    response_model=SnapshotResponse,
    status_code=status.HTTP_200_OK,
)
async def create_snapshot(
    session: Annotated[AsyncSession, Depends(get_session)],
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
    knowledge_base_id: AdminKnowledgeBaseId = DEFAULT_KNOWLEDGE_BASE_ID,
) -> SnapshotResponse:
    snapshot = await snapshot_service.get_or_create_draft(
        session=session,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )
    await session.commit()
    await session.refresh(snapshot)
    return SnapshotResponse.model_validate(snapshot)


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotResponse)
async def get_snapshot(
    snapshot_id: uuid.UUID,
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
    knowledge_base_id: AdminKnowledgeBaseId = DEFAULT_KNOWLEDGE_BASE_ID,
) -> SnapshotResponse:
    snapshot = await snapshot_service.get_snapshot(
        snapshot_id,
        agent_id=agent_id,
        knowledge_base_id=knowledge_base_id,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return SnapshotResponse.model_validate(snapshot)


@router.post("/snapshots/{snapshot_id}/publish", response_model=SnapshotResponse)
async def publish_snapshot(
    snapshot_id: uuid.UUID,
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    activate: bool = False,
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
    knowledge_base_id: AdminKnowledgeBaseId = DEFAULT_KNOWLEDGE_BASE_ID,
) -> SnapshotResponse:
    try:
        snapshot = await snapshot_service.publish(
            snapshot_id,
            activate=activate,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
        )
    except Exception as error:
        _raise_snapshot_http_error(error)

    return SnapshotResponse.model_validate(snapshot)


@router.post("/snapshots/{snapshot_id}/activate", response_model=SnapshotResponse)
async def activate_snapshot(
    snapshot_id: uuid.UUID,
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
    knowledge_base_id: AdminKnowledgeBaseId = DEFAULT_KNOWLEDGE_BASE_ID,
) -> SnapshotResponse:
    try:
        snapshot = await snapshot_service.activate(
            snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
        )
    except Exception as error:
        _raise_snapshot_http_error(error)

    return SnapshotResponse.model_validate(snapshot)


@router.post("/snapshots/{snapshot_id}/rollback", response_model=RollbackResponse)
async def rollback_snapshot(
    snapshot_id: uuid.UUID,
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
    knowledge_base_id: AdminKnowledgeBaseId = DEFAULT_KNOWLEDGE_BASE_ID,
) -> RollbackResponse:
    try:
        rolled_back_from, rolled_back_to = await snapshot_service.rollback(
            snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
        )
    except Exception as error:
        _raise_snapshot_http_error(error)

    return RollbackResponse(
        rolled_back_from=RollbackSnapshotResponse.model_validate(rolled_back_from),
        rolled_back_to=RollbackSnapshotResponse.model_validate(rolled_back_to),
    )


@router.post("/snapshots/{snapshot_id}/test", response_model=DraftTestResponse)
async def test_draft_snapshot(
    snapshot_id: uuid.UUID,
    payload: DraftTestRequest,
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    embedding_service: Annotated[EmbeddingService, Depends(get_embedding_service)],
    qdrant_service: Annotated[QdrantService, Depends(get_qdrant_service)],
    session: Annotated[AsyncSession, Depends(get_session)],
    agent_id: AdminAgentId = DEFAULT_AGENT_ID,
    knowledge_base_id: AdminKnowledgeBaseId = DEFAULT_KNOWLEDGE_BASE_ID,
) -> DraftTestResponse:
    try:
        snapshot = await snapshot_service.get_snapshot(
            snapshot_id,
            agent_id=agent_id,
            knowledge_base_id=knowledge_base_id,
        )
        if snapshot is None:
            raise SnapshotNotFoundError("Snapshot not found")
        if snapshot.status is not SnapshotStatus.DRAFT:
            raise SnapshotValidationError("Only draft snapshots can be tested")

        indexed_count = int(
            await session.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(
                    Chunk.snapshot_id == snapshot_id,
                    Chunk.status == ChunkStatus.INDEXED,
                )
            )
            or 0
        )
        if indexed_count == 0:
            raise SnapshotValidationError("Draft has no indexed chunks to search")

        if payload.mode is RetrievalMode.SPARSE:
            retrieved_chunks = await qdrant_service.keyword_search(
                text=payload.query,
                snapshot_id=snapshot.id,
                agent_id=agent_id,
                knowledge_base_id=knowledge_base_id,
                limit=payload.top_n,
            )
        else:
            embeddings = await embedding_service.embed_texts(
                [payload.query],
                task_type="RETRIEVAL_QUERY",
            )
            if payload.mode is RetrievalMode.DENSE:
                retrieved_chunks = await qdrant_service.dense_search(
                    vector=embeddings[0],
                    snapshot_id=snapshot.id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    limit=payload.top_n,
                )
            else:
                retrieved_chunks = await qdrant_service.hybrid_search(
                    text=payload.query,
                    vector=embeddings[0],
                    snapshot_id=snapshot.id,
                    agent_id=agent_id,
                    knowledge_base_id=knowledge_base_id,
                    limit=payload.top_n,
                )
    except (
        SnapshotNotFoundError,
        SnapshotConflictError,
        SnapshotValidationError,
    ) as error:
        _raise_snapshot_http_error(error)

    source_titles: dict[uuid.UUID, str | None] = {}
    source_ids = {chunk.source_id for chunk in retrieved_chunks}
    try:
        if source_ids:
            source_result = await session.scalars(select(Source).where(Source.id.in_(source_ids)))
            source_titles = {source.id: source.title for source in source_result.all()}
    except Exception as error:
        raise HTTPException(status_code=500, detail="Failed to enrich source titles") from error

    return DraftTestResponse(
        snapshot_id=snapshot.id,
        snapshot_name=snapshot.name,
        query=payload.query,
        mode=payload.mode,
        total_chunks_in_draft=indexed_count,
        results=[
            DraftTestResult(
                chunk_id=chunk.chunk_id,
                source_id=chunk.source_id,
                source_title=source_titles.get(chunk.source_id),
                text_content=chunk.text_content[:500],
                score=chunk.score,
                anchor=DraftTestAnchor(
                    page=chunk.anchor_metadata.get("anchor_page"),
                    chapter=chunk.anchor_metadata.get("anchor_chapter"),
                    section=chunk.anchor_metadata.get("anchor_section"),
                    timecode=chunk.anchor_metadata.get("anchor_timecode"),
                ),
            )
            for chunk in retrieved_chunks
        ],
    )


@router.post("/search/keyword", response_model=KeywordSearchResponse)
async def keyword_search(
    payload: KeywordSearchRequest,
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    qdrant_service: Annotated[QdrantService, Depends(get_qdrant_service)],
) -> KeywordSearchResponse:
    snapshot_id = payload.snapshot_id
    if snapshot_id is None:
        active_snapshot = await snapshot_service.get_active_snapshot(
            agent_id=payload.agent_id,
            knowledge_base_id=payload.knowledge_base_id,
        )
        if active_snapshot is None:
            raise HTTPException(
                status_code=422,
                detail="No active snapshot found for the requested scope",
            )
        snapshot_id = active_snapshot.id

    results = await qdrant_service.keyword_search(
        text=payload.query,
        snapshot_id=snapshot_id,
        agent_id=payload.agent_id,
        knowledge_base_id=payload.knowledge_base_id,
        limit=payload.limit,
    )
    return KeywordSearchResponse(
        query=payload.query,
        language=(
            qdrant_service.bm25_language if qdrant_service.sparse_backend == "bm25" else None
        ),
        bm25_language=qdrant_service.bm25_language,
        sparse_backend=qdrant_service.sparse_backend,
        sparse_model=qdrant_service.sparse_model,
        total=len(results),
        results=[KeywordSearchResult.from_retrieved_chunk(chunk) for chunk in results],
    )
