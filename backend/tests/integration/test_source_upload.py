from __future__ import annotations

import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.dependencies import get_source_service
from app.core.constants import DEFAULT_AGENT_ID
from app.db.models import BackgroundTask, Source
from app.db.models.enums import BackgroundTaskStatus, BackgroundTaskType, SourceStatus, SourceType
from app.services.snapshot import SnapshotService
from app.services.source import SourcePersistenceError
from app.workers.tasks.ingestion import process_ingestion


@dataclass(slots=True)
class FakeChunkData:
    text_content: str
    token_count: int
    chunk_index: int
    anchor_page: int | None
    anchor_chapter: str | None
    anchor_section: str | None
    anchor_timecode: str | None = None


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
    ("filename", "expected_type", "expected_mime_type"),
    [
        ("doc.md", SourceType.MARKDOWN, "text/markdown"),
        ("notes.TXT", SourceType.TXT, "text/plain"),
        ("report.pdf", SourceType.PDF, "application/pdf"),
        (
            "document.docx",
            SourceType.DOCX,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("page.html", SourceType.HTML, "text/html"),
        ("page.htm", SourceType.HTML, "text/html"),
        ("photo.png", SourceType.IMAGE, "image/png"),
        ("photo.JPG", SourceType.IMAGE, "image/jpeg"),
        ("clip.mp3", SourceType.AUDIO, "audio/mpeg"),
        ("clip.wav", SourceType.AUDIO, "audio/wav"),
        ("movie.mp4", SourceType.VIDEO, "video/mp4"),
    ],
)
async def test_upload_endpoint_accepts_supported_formats(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
    filename: str,
    expected_type: SourceType,
    expected_mime_type: str,
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
    assert sources[0].mime_type == expected_mime_type
    assert sources[0].status is SourceStatus.PENDING
    assert tasks[0].source_id == sources[0].id
    assert tasks[0].task_type is BackgroundTaskType.INGESTION
    assert tasks[0].status is BackgroundTaskStatus.PENDING
    mock_storage_service.upload.assert_awaited_once()
    assert mock_storage_service.upload.await_args.args[2] == expected_mime_type

    task_response = await api_client.get(f"/api/admin/tasks/{body['task_id']}")
    assert task_response.status_code == 200
    task_body = task_response.json()
    assert task_body["status"] == "pending"
    assert task_body["task_type"] == "ingestion"
    assert task_body["source_id"] == body["source_id"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_upload_endpoint_persists_language_metadata(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": '{"title":"Localized document","language":"russian"}'},
        files={"file": ("doc.md", b"hello world", "text/markdown")},
    )

    assert response.status_code == 202

    sources, _ = await _load_source_and_task(session_factory)
    assert len(sources) == 1
    assert sources[0].language == "russian"


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_upload_endpoint_accepts_max_length_language(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    language = "r" * 32

    response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": f'{{"title":"Localized document","language":"{language}"}}'},
        files={"file": ("doc.md", b"hello world", "text/markdown")},
    )

    assert response.status_code == 202

    sources, _ = await _load_source_and_task(session_factory)
    assert len(sources) == 1
    assert sources[0].language == language


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_upload_endpoint_normalizes_blank_language_to_null(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": '{"title":"Localized document","language":"   "}'},
        files={"file": ("doc.md", b"hello world", "text/markdown")},
    )

    assert response.status_code == 202

    sources, _ = await _load_source_and_task(session_factory)
    assert len(sources) == 1
    assert sources[0].language is None


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_upload_endpoint_omits_default_processing_hint_from_task_metadata(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": '{"title":"Default hint"}'},
        files={"file": ("doc.md", b"hello world", "text/markdown")},
    )

    assert response.status_code == 202

    _, tasks = await _load_source_and_task(session_factory)
    assert len(tasks) == 1
    assert tasks[0].result_metadata in (None, {}) or (
        "processing_hint" not in tasks[0].result_metadata
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_upload_endpoint_persists_external_processing_hint_in_task_metadata(
    api_client,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": '{"title":"External hint","processing_hint":"external"}'},
        files={"file": ("report.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 202

    _, tasks = await _load_source_and_task(session_factory)
    assert len(tasks) == 1
    assert tasks[0].result_metadata == {"processing_hint": "external"}


@pytest.mark.asyncio
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_upload_endpoint_rejects_unsupported_extension(api_client) -> None:
    response = await api_client.post(
        "/api/admin/sources",
        data={"metadata": '{"title":"Bad document"}'},
        files={"file": ("sheet.xlsx", b"fake-xlsx", "application/octet-stream")},
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
        '{"title":"Doc","language":"' + ("r" * 33) + '"}',
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
@pytest.mark.usefixtures("committed_data_cleanup")
async def test_upload_endpoint_deletes_uploaded_object_when_persistence_fails(
    admin_app,
    mock_storage_service: SimpleNamespace,
) -> None:
    fake_source_service = SimpleNamespace(
        create_source_and_task=AsyncMock(side_effect=SourcePersistenceError("db unavailable"))
    )
    admin_app.dependency_overrides[get_source_service] = lambda: fake_source_service

    try:
        transport = httpx.ASGITransport(app=admin_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/api/admin/sources",
                data={"metadata": '{"title":"Persistence failure"}'},
                files={"file": ("doc.md", b"hello", "text/markdown")},
            )
    finally:
        admin_app.dependency_overrides.pop(get_source_service, None)

    assert response.status_code == 500
    mock_storage_service.upload.assert_awaited_once()
    mock_storage_service.delete.assert_awaited_once()


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

    await process_ingestion(
        {
            "session_factory": session_factory,
            "settings": SimpleNamespace(bm25_language="english"),
            "path_a_text_threshold_pdf": 2000,
            "path_a_text_threshold_media": 500,
            "path_a_max_pdf_pages": 6,
            "path_a_max_audio_duration_sec": 80,
            "path_a_max_video_duration_sec": 120,
            "storage_service": SimpleNamespace(download=AsyncMock(return_value=b"# hello world")),
            "document_processor": SimpleNamespace(
                parse_and_chunk=AsyncMock(
                    return_value=[
                        FakeChunkData(
                            text_content="hello world",
                            token_count=2,
                            chunk_index=0,
                            anchor_page=None,
                            anchor_chapter="hello",
                            anchor_section=None,
                        )
                    ]
                )
            ),
            "embedding_service": SimpleNamespace(
                model="gemini-embedding-2-preview",
                dimensions=3,
                embed_texts=AsyncMock(return_value=[[0.1, 0.2, 0.3]]),
                embed_file=AsyncMock(return_value=[0.1, 0.2, 0.3]),
            ),
            "gemini_content_service": SimpleNamespace(extract_text_content=AsyncMock()),
            "tokenizer": SimpleNamespace(count_tokens=lambda text: len(str(text).split())),
            "qdrant_service": SimpleNamespace(
                upsert_chunks=AsyncMock(),
                delete_chunks=AsyncMock(),
            ),
            "snapshot_service": SnapshotService(),
        },
        task_id,
    )

    task_response = await api_client.get(f"/api/admin/tasks/{task_id}")
    assert task_response.status_code == 200
    task_body = task_response.json()
    assert task_body["status"] == "complete"
    assert task_body["progress"] == 100
    assert task_body["started_at"] is not None
    assert task_body["completed_at"] is not None
