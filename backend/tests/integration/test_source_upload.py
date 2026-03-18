from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.constants import DEFAULT_AGENT_ID
from app.db.models import BackgroundTask, Source
from app.db.models.enums import BackgroundTaskStatus, BackgroundTaskType, SourceStatus, SourceType
from app.workers.tasks.ingestion import process_ingestion


async def _load_source_and_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[list[Source], list[BackgroundTask]]:
    async with session_factory() as session:
        sources = (await session.scalars(select(Source))).all()
        tasks = (await session.scalars(select(BackgroundTask))).all()
    return sources, tasks


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
@pytest.mark.parametrize(
    ("filename", "expected_type"),
    [("doc.md", SourceType.MARKDOWN), ("notes.TXT", SourceType.TXT)],
)
async def test_upload_endpoint_accepts_markdown_and_txt(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
    filename: str,
    expected_type: SourceType,
) -> None:
    response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": '{"title":"My document"}'},
        files={"file": (filename, b"hello world", "text/plain")},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["message"] == "Source uploaded and queued for ingestion."

    sources, tasks = await _load_source_and_task(session_factory)
    assert len(sources) == 1
    assert len(tasks) == 1
    assert sources[0].id == uuid.UUID(body["source_id"])
    assert sources[0].agent_id == DEFAULT_AGENT_ID
    assert sources[0].source_type is expected_type
    assert sources[0].status is SourceStatus.PENDING
    assert tasks[0].source_id == sources[0].id
    assert tasks[0].task_type is BackgroundTaskType.INGESTION
    assert tasks[0].status is BackgroundTaskStatus.PENDING
    mock_storage_service.upload.assert_awaited_once()

    task_response = await api_client.get(f"/api/admin/tasks/{body['task_id']}")
    assert task_response.status_code == 200
    task_body = task_response.json()
    assert task_body["status"] == "pending"
    assert task_body["task_type"] == "ingestion"
    assert task_body["source_id"] == body["source_id"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_upload_endpoint_rejects_unsupported_extension(api_client) -> None:
    response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": '{"title":"Bad document"}'},
        files={"file": ("doc.pdf", b"fake-pdf", "application/pdf")},
    )

    assert response.status_code == 422
    assert "Allowed extensions" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_upload_endpoint_rejects_empty_file(api_client) -> None:
    response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": '{"title":"Empty document"}'},
        files={"file": ("empty.md", b"", "text/markdown")},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_upload_endpoint_rejects_oversized_file(admin_app) -> None:
    original_limit = admin_app.state.settings.upload_max_file_size_mb
    admin_app.state.settings.upload_max_file_size_mb = 1

    try:
        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/admin/sources",
                data={"metadata": '{"title":"Big document"}'},
                files={"file": ("big.md", b"x" * (1024 * 1024 + 1), "text/markdown")},
            )
    finally:
        admin_app.state.settings.upload_max_file_size_mb = original_limit

    assert response.status_code == 413


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
@pytest.mark.parametrize(
    "metadata",
    [
        "{}",
        "not json",
        '{"title":"Doc","public_url":"ftp://example.com"}',
    ],
)
async def test_upload_endpoint_rejects_invalid_metadata(api_client, metadata: str) -> None:
    response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": metadata},
        files={"file": ("doc.md", b"hello", "text/markdown")},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_upload_endpoint_marks_records_failed_when_enqueue_fails(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
    mock_arq_pool: SimpleNamespace,
) -> None:
    mock_arq_pool.enqueue_job = AsyncMock(side_effect=RuntimeError("redis unavailable"))

    response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": '{"title":"Queue failure"}'},
        files={"file": ("doc.md", b"hello", "text/markdown")},
    )

    assert response.status_code == 500

    sources, tasks = await _load_source_and_task(session_factory)
    assert len(sources) == 1
    assert len(tasks) == 1
    assert sources[0].status is SourceStatus.FAILED
    assert tasks[0].status is BackgroundTaskStatus.FAILED
    assert "Failed to enqueue ingestion task" in (tasks[0].error_message or "")


@pytest.mark.asyncio
async def test_get_task_returns_404_for_missing_task(api_client) -> None:
    response = await api_client.get(f"/api/admin/tasks/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_upload_worker_and_task_status_round_trip(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    upload_response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": '{"title":"Round trip document"}'},
        files={"file": ("doc.md", b"hello world", "text/markdown")},
    )
    assert upload_response.status_code == 202
    task_id = upload_response.json()["task_id"]

    await process_ingestion({"session_factory": session_factory}, task_id)

    task_response = await api_client.get(f"/api/admin/tasks/{task_id}")
    assert task_response.status_code == 200
    task_body = task_response.json()
    assert task_body["status"] == "complete"
    assert task_body["progress"] == 100
    assert task_body["started_at"] is not None
    assert task_body["completed_at"] is not None
