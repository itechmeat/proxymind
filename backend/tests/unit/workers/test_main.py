from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.workers import main


@pytest.mark.asyncio
async def test_on_startup_passes_bm25_language_to_qdrant_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokenizer = object()
    gemini_content_service = object()
    summary_llm_service = object()
    settings = SimpleNamespace(
        seaweedfs_filer_url="http://localhost:8888",
        seaweedfs_sources_path="/sources",
        redis_url="redis://localhost:6379/0",
        qdrant_url="http://localhost:6333",
        qdrant_collection="proxymind_chunks",
        embedding_dimensions=3,
        bm25_language="english",
        embedding_model="gemini-embedding-2-preview",
        embedding_batch_size=16,
        gemini_content_model="gemini-3-flash-preview",
        gemini_file_upload_threshold_bytes=10 * 1024 * 1024,
        gemini_api_key=None,
        google_genai_use_vertexai=False,
        google_cloud_project=None,
        google_cloud_location="global",
        llm_model="openai/gpt-4o",
        llm_api_key=None,
        llm_api_base=None,
        log_level="info",
        conversation_summary_model=None,
        conversation_summary_temperature=0.1,
        document_ai_project_id=None,
        document_ai_location="us",
        document_ai_processor_id=None,
        document_ai_enabled=False,
        chunk_max_tokens=1024,
        otel_enabled=False,
        otel_service_name="proxymind-api",
        otel_environment="test",
        otel_exporter_otlp_endpoint="http://tempo:4317",
        path_c_min_chars_per_page=50,
        path_a_text_threshold_pdf=2000,
        path_a_text_threshold_media=500,
        path_a_max_pdf_pages=6,
        path_a_max_audio_duration_sec=80,
        path_a_max_video_duration_sec=120,
    )
    storage_http_client = SimpleNamespace(aclose=AsyncMock())
    worker_redis_client = SimpleNamespace(aclose=AsyncMock())
    qdrant_client = object()
    qdrant_service = SimpleNamespace(ensure_collection=AsyncMock())
    storage_service = SimpleNamespace(ensure_storage_root=AsyncMock())
    captured_qdrant_kwargs: dict[str, object] = {}
    ctx: dict[str, object] = {}

    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "configure_logging", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "init_telemetry", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "instrument_sqlalchemy", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main, "update_queue_depth", AsyncMock())
    monkeypatch.setattr(main, "create_database_engine", lambda _settings: object())
    monkeypatch.setattr(main, "create_session_factory", lambda _engine: object())
    monkeypatch.setattr(
        main,
        "Redis",
        SimpleNamespace(from_url=lambda _url: worker_redis_client),
    )
    monkeypatch.setattr(
        main.httpx,
        "AsyncClient",
        lambda *, base_url, timeout: (
            storage_http_client
            if base_url == settings.seaweedfs_filer_url and timeout == 30.0
            else None
        ),
    )
    monkeypatch.setattr(
        main,
        "AsyncQdrantClient",
        lambda *, url: qdrant_client if url == settings.qdrant_url else None,
    )

    def fake_storage_service(http_client: httpx.AsyncClient, sources_path: str) -> object:
        assert http_client is storage_http_client
        assert sources_path == settings.seaweedfs_sources_path
        return storage_service

    def fake_qdrant_service(**kwargs: object) -> object:
        captured_qdrant_kwargs.update(kwargs)
        return qdrant_service

    def install_stub(module_name: str, **attributes: object) -> None:
        module = ModuleType(module_name)
        for attribute_name, value in attributes.items():
            setattr(module, attribute_name, value)
        monkeypatch.setitem(sys.modules, module_name, module)

    install_stub("app.services.storage", StorageService=fake_storage_service)
    install_stub("app.services.qdrant", QdrantService=fake_qdrant_service)
    install_stub(
        "app.services.lightweight_parser",
        LightweightParser=lambda **_kwargs: object(),
    )
    install_stub("app.services.embedding", EmbeddingService=lambda **_kwargs: object())
    install_stub("app.services.llm", LLMService=lambda **_kwargs: summary_llm_service)
    install_stub("app.services.document_ai_parser", DocumentAIParser=lambda **_kwargs: object())
    install_stub(
        "app.services.gemini_content",
        GeminiContentService=lambda **_kwargs: gemini_content_service,
    )
    install_stub("app.services.snapshot", SnapshotService=lambda: object())
    install_stub("app.services.token_counter", ApproximateTokenizer=lambda: tokenizer)
    install_stub("app.services.batch_embedding", BatchEmbeddingClient=lambda **_kwargs: object())
    install_stub("app.services.batch_orchestrator", BatchOrchestrator=lambda **_kwargs: object())

    await main.on_startup(ctx)

    assert captured_qdrant_kwargs == {
        "client": qdrant_client,
        "collection_name": settings.qdrant_collection,
        "embedding_dimensions": settings.embedding_dimensions,
        "bm25_language": settings.bm25_language,
    }
    qdrant_service.ensure_collection.assert_awaited_once()
    storage_service.ensure_storage_root.assert_awaited_once()
    assert ctx["gemini_content_service"] is gemini_content_service
    assert ctx["summary_llm_service"] is summary_llm_service
    assert ctx["tokenizer"] is tokenizer
    assert ctx["worker_redis_client"] is worker_redis_client
    assert ctx["path_a_text_threshold_pdf"] == 2000
    assert ctx["path_a_text_threshold_media"] == 500
    assert ctx["path_a_max_pdf_pages"] == 6
    assert ctx["path_a_max_audio_duration_sec"] == 80
    assert ctx["path_a_max_video_duration_sec"] == 120


@pytest.mark.asyncio
async def test_on_shutdown_disposes_engine_even_if_qdrant_close_fails() -> None:
    engine = SimpleNamespace(dispose=AsyncMock())
    qdrant_service = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("boom")))
    storage_http_client = SimpleNamespace(aclose=AsyncMock())
    worker_redis_client = SimpleNamespace(aclose=AsyncMock())

    original_shutdown = main.shutdown_telemetry
    shutdown_telemetry = MagicMock()
    main.shutdown_telemetry = shutdown_telemetry  # type: ignore[assignment]
    try:
        await main.on_shutdown(
            {
                "db_engine": engine,
                "qdrant_service": qdrant_service,
                "storage_http_client": storage_http_client,
                "worker_redis_client": worker_redis_client,
            }
        )
    finally:
        main.shutdown_telemetry = original_shutdown  # type: ignore[assignment]

    qdrant_service.close.assert_awaited_once()
    storage_http_client.aclose.assert_awaited_once()
    worker_redis_client.aclose.assert_awaited_once()
    engine.dispose.assert_awaited_once()
    shutdown_telemetry.assert_called_once_with()


@pytest.mark.asyncio
async def test_on_shutdown_stops_telemetry_before_engine_dispose() -> None:
    call_order: list[str] = []

    async def dispose() -> None:
        call_order.append("dispose")

    engine = SimpleNamespace(dispose=AsyncMock(side_effect=dispose))
    original_shutdown = main.shutdown_telemetry

    def shutdown() -> None:
        call_order.append("telemetry")

    main.shutdown_telemetry = shutdown  # type: ignore[assignment]
    try:
        await main.on_shutdown({"db_engine": engine})
    finally:
        main.shutdown_telemetry = original_shutdown  # type: ignore[assignment]

    assert call_order == ["telemetry", "dispose"]


def test_worker_settings_register_queue_probe() -> None:
    assert main.probe_queue_depth in main.WorkerSettings.functions
