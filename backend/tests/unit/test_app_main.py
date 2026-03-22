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
        minio_host="localhost",
        minio_port=9000,
        minio_root_user="proxymind",
        minio_root_password="proxymind",
        minio_bucket_sources="sources",
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
    qdrant_service = SimpleNamespace(
        ensure_collection=AsyncMock(side_effect=RuntimeError("boom")),
        close=AsyncMock(),
    )
    create_pool = AsyncMock()

    monkeypatch.setattr(app_main, "get_settings", lambda: _settings())
    monkeypatch.setattr(app_main, "configure_logging", lambda _level: None)
    monkeypatch.setattr(app_main, "create_database_engine", lambda _settings: db_engine)
    monkeypatch.setattr(app_main, "create_session_factory", lambda _engine: object())
    monkeypatch.setattr(app_main, "Redis", SimpleNamespace(from_url=lambda _url: redis_client))
    monkeypatch.setattr(app_main.httpx, "AsyncClient", lambda timeout: http_client)
    monkeypatch.setattr(app_main, "EmbeddingService", lambda **_kwargs: object())
    monkeypatch.setattr(app_main, "AsyncQdrantClient", lambda url: object())
    monkeypatch.setattr(app_main, "QdrantService", lambda **_kwargs: qdrant_service)
    monkeypatch.setattr(app_main, "RetrievalService", lambda **_kwargs: object())
    monkeypatch.setattr(app_main, "LLMService", lambda **_kwargs: object())
    monkeypatch.setattr(app_main, "Minio", lambda **_kwargs: object())
    monkeypatch.setattr(
        app_main,
        "StorageService",
        lambda _client, _bucket_name: SimpleNamespace(ensure_bucket=AsyncMock()),
    )
    monkeypatch.setattr(app_main, "create_pool", create_pool)

    with pytest.raises(RuntimeError, match="boom"):
        async with app_main.lifespan(FastAPI()):
            pass

    qdrant_service.close.assert_awaited_once()
    http_client.aclose.assert_awaited_once()
    redis_client.aclose.assert_awaited_once()
    db_engine.dispose.assert_awaited_once()
    create_pool.assert_not_awaited()
