from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from app import main as app_main


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        log_level="info",
        redis_url="redis://localhost:6379/0",
        embedding_model="gemini-embedding-2-preview",
        embedding_dimensions=3,
        embedding_batch_size=16,
        gemini_api_key=None,
        qdrant_url="http://localhost:6333",
        qdrant_collection="proxymind_chunks",
        retrieval_top_n=5,
        min_dense_similarity=None,
        llm_model="openai/gpt-4o",
        llm_api_key=None,
        llm_api_base=None,
        llm_temperature=0.7,
        seaweedfs_host="localhost",
        seaweedfs_filer_port=8888,
        seaweedfs_filer_url="http://localhost:8888",
        seaweedfs_sources_path="/sources",
        redis_host="localhost",
        redis_port=6379,
    )


@pytest.mark.asyncio
async def test_lifespan_cleans_up_initialized_resources_on_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_engine = SimpleNamespace(dispose=AsyncMock())
    redis_client = SimpleNamespace(aclose=AsyncMock())
    http_client = SimpleNamespace(aclose=AsyncMock())
    storage_http_client = SimpleNamespace(aclose=AsyncMock())
    qdrant_service = SimpleNamespace(
        ensure_collection=AsyncMock(side_effect=RuntimeError("boom")),
        close=AsyncMock(),
    )
    create_pool = AsyncMock()

    def make_async_client(*, timeout: float, base_url: str | None = None):
        if base_url is not None:
            assert base_url == "http://localhost:8888"
            assert timeout == 30.0
            return storage_http_client
        assert timeout == 5.0
        return http_client

    monkeypatch.setattr(app_main, "get_settings", lambda: _settings())
    monkeypatch.setattr(app_main, "configure_logging", lambda _level: None)
    monkeypatch.setattr(app_main, "create_database_engine", lambda _settings: db_engine)
    monkeypatch.setattr(app_main, "create_session_factory", lambda _engine: object())
    monkeypatch.setattr(app_main, "Redis", SimpleNamespace(from_url=lambda _url: redis_client))
    monkeypatch.setattr(app_main.httpx, "AsyncClient", make_async_client)
    monkeypatch.setattr(app_main, "_create_embedding_service", lambda _settings: object())
    monkeypatch.setattr(app_main, "_create_qdrant_service", lambda _settings: qdrant_service)
    monkeypatch.setattr(
        app_main,
        "_create_retrieval_service",
        lambda _settings, _embedding_service, _qdrant_service: object(),
    )
    monkeypatch.setattr(app_main, "_create_llm_service", lambda _settings: object())
    monkeypatch.setattr(
        app_main,
        "_create_storage_service",
        lambda _settings, _storage_http_client: SimpleNamespace(
            ensure_storage_root=AsyncMock()
        ),
    )
    monkeypatch.setattr(app_main, "create_pool", create_pool)

    with pytest.raises(RuntimeError, match="boom"):
        async with app_main.lifespan(FastAPI()):
            pass

    qdrant_service.close.assert_awaited_once()
    storage_http_client.aclose.assert_awaited_once()
    http_client.aclose.assert_awaited_once()
    redis_client.aclose.assert_awaited_once()
    db_engine.dispose.assert_awaited_once()
    create_pool.assert_not_awaited()
