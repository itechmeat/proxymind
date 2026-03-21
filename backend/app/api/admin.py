from __future__ import annotations

import uuid
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

from app.api.dependencies import get_snapshot_service, get_source_service, get_storage_service
from app.api.schemas import SourceUploadMetadata, SourceUploadResponse, TaskStatusResponse
from app.api.snapshot_schemas import SnapshotResponse
from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.db.models.enums import SnapshotStatus
from app.services import (
    SnapshotConflictError,
    SnapshotNotFoundError,
    SnapshotService,
    SnapshotValidationError,
    StorageService,
    determine_source_type,
    validate_file_extension,
)
from app.services.source import SourcePersistenceError, SourceService, TaskEnqueueError

router = APIRouter(prefix="/api/admin", tags=["admin"])
UPLOAD_READ_CHUNK_SIZE = 64 * 1024


def _raise_snapshot_http_error(error: Exception) -> None:
    if isinstance(error, SnapshotNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, SnapshotConflictError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, SnapshotValidationError):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


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
) -> SourceUploadResponse:
    # TODO(S7-01): Protect /api/admin/* with Bearer auth before any non-local deployment.
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
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        max_size_bytes = request.app.state.settings.upload_max_file_size_mb * 1024 * 1024
        content = await _read_upload_content(file, max_size_bytes)

        source_id = uuid.uuid7()
        object_key = storage_service.generate_object_key(DEFAULT_AGENT_ID, source_id, filename)

        try:
            await storage_service.upload(object_key, content, file.content_type)
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
                mime_type=file.content_type,
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
    agent_id: uuid.UUID = DEFAULT_AGENT_ID,
    knowledge_base_id: uuid.UUID = DEFAULT_KNOWLEDGE_BASE_ID,
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


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotResponse)
async def get_snapshot(
    snapshot_id: uuid.UUID,
    snapshot_service: Annotated[SnapshotService, Depends(get_snapshot_service)],
    agent_id: uuid.UUID = DEFAULT_AGENT_ID,
    knowledge_base_id: uuid.UUID = DEFAULT_KNOWLEDGE_BASE_ID,
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
    agent_id: uuid.UUID = DEFAULT_AGENT_ID,
    knowledge_base_id: uuid.UUID = DEFAULT_KNOWLEDGE_BASE_ID,
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
    agent_id: uuid.UUID = DEFAULT_AGENT_ID,
    knowledge_base_id: uuid.UUID = DEFAULT_KNOWLEDGE_BASE_ID,
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
