from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.workers import main


@pytest.mark.asyncio
async def test_on_startup_passes_bm25_language_to_qdrant_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        seaweedfs_filer_url="http://localhost:8888",
        seaweedfs_sources_path="/sources",
        qdrant_url="http://localhost:6333",
        qdrant_collection="proxymind_chunks",
        embedding_dimensions=3,
        bm25_language="english",
        embedding_model="gemini-embedding-2-preview",
        embedding_batch_size=16,
        gemini_api_key=None,
        chunk_max_tokens=1024,
    )
    storage_http_client = SimpleNamespace(aclose=AsyncMock())
    qdrant_client = object()
    qdrant_service = SimpleNamespace(ensure_collection=AsyncMock())
    storage_service = SimpleNamespace(ensure_storage_root=AsyncMock())
    captured_qdrant_kwargs: dict[str, object] = {}
    ctx: dict[str, object] = {}

    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "create_database_engine", lambda _settings: object())
    monkeypatch.setattr(main, "create_session_factory", lambda _engine: object())
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

    monkeypatch.setattr("app.services.storage.StorageService", fake_storage_service)
    monkeypatch.setattr("app.services.qdrant.QdrantService", fake_qdrant_service)
    monkeypatch.setattr("app.services.docling_parser.DoclingParser", lambda **_kwargs: object())
    monkeypatch.setattr("app.services.embedding.EmbeddingService", lambda **_kwargs: object())
    monkeypatch.setattr("app.services.snapshot.SnapshotService", lambda: object())

    await main.on_startup(ctx)

    assert captured_qdrant_kwargs == {
        "client": qdrant_client,
        "collection_name": settings.qdrant_collection,
        "embedding_dimensions": settings.embedding_dimensions,
        "bm25_language": settings.bm25_language,
    }
    qdrant_service.ensure_collection.assert_awaited_once()
    storage_service.ensure_storage_root.assert_awaited_once()


@pytest.mark.asyncio
async def test_on_shutdown_disposes_engine_even_if_qdrant_close_fails() -> None:
    engine = SimpleNamespace(dispose=AsyncMock())
    qdrant_service = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("boom")))
    storage_http_client = SimpleNamespace(aclose=AsyncMock())

    await main.on_shutdown(
        {
            "db_engine": engine,
            "qdrant_service": qdrant_service,
            "storage_http_client": storage_http_client,
        }
    )

    qdrant_service.close.assert_awaited_once()
    storage_http_client.aclose.assert_awaited_once()
    engine.dispose.assert_awaited_once()
