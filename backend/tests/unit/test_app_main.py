from __future__ import annotations

from pathlib import Path
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
        google_genai_use_vertexai=False,
        google_cloud_project=None,
        google_cloud_location="global",
        qdrant_url="http://localhost:6333",
        qdrant_collection="proxymind_chunks",
        bm25_language="english",
        retrieval_top_n=5,
        min_dense_similarity=None,
        llm_model="openai/gpt-4o",
        llm_api_key=None,
        llm_api_base=None,
        llm_temperature=0.7,
        rewrite_enabled=True,
        rewrite_llm_model=None,
        rewrite_llm_api_key=None,
        rewrite_llm_api_base=None,
        rewrite_temperature=0.1,
        rewrite_timeout_ms=3000,
        rewrite_token_budget=2048,
        rewrite_history_messages=10,
        seaweedfs_host="localhost",
        seaweedfs_filer_port=8888,
        seaweedfs_filer_url="http://localhost:8888",
        seaweedfs_sources_path="/sources",
        redis_host="localhost",
        redis_port=6379,
        persona_dir="/persona",
        config_dir="/config",
        promotions_file_path="/config/PROMOTIONS.md",
        conversation_memory_budget=4096,
        conversation_summary_ratio=0.3,
        admin_api_key=None,
        chat_rate_limit=60,
        chat_rate_window_seconds=60,
        trusted_proxy_depth=1,
    )


def test_create_qdrant_service_passes_bm25_language(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    created_client: object = object()
    captured_kwargs: dict[str, object] = {}

    monkeypatch.setattr(
        app_main,
        "AsyncQdrantClient",
        lambda *, url: created_client if url == settings.qdrant_url else None,
    )

    def fake_qdrant_service(**kwargs: object) -> object:
        captured_kwargs.update(kwargs)
        return object()

    monkeypatch.setattr("app.services.qdrant.QdrantService", fake_qdrant_service)

    app_main._create_qdrant_service(settings)

    assert captured_kwargs == {
        "client": created_client,
        "collection_name": settings.qdrant_collection,
        "embedding_dimensions": settings.embedding_dimensions,
        "bm25_language": settings.bm25_language,
    }


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


def _make_resource_bundle() -> tuple[
    SimpleNamespace,
    SimpleNamespace,
    SimpleNamespace,
    SimpleNamespace,
    SimpleNamespace,
    SimpleNamespace,
    AsyncMock,
]:
    db_engine = SimpleNamespace(dispose=AsyncMock())
    redis_client = SimpleNamespace(aclose=AsyncMock())
    http_client = SimpleNamespace(aclose=AsyncMock())
    storage_http_client = SimpleNamespace(aclose=AsyncMock())
    qdrant_service = SimpleNamespace(ensure_collection=AsyncMock(), close=AsyncMock())
    storage_service = SimpleNamespace(ensure_storage_root=AsyncMock())
    create_pool = AsyncMock(return_value=SimpleNamespace(close=AsyncMock()))
    return (
        db_engine,
        redis_client,
        http_client,
        storage_http_client,
        qdrant_service,
        storage_service,
        create_pool,
    )


def _patch_lifespan_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    settings: SimpleNamespace,
    *,
    db_engine: SimpleNamespace,
    redis_client: SimpleNamespace,
    http_client: SimpleNamespace,
    storage_http_client: SimpleNamespace,
    qdrant_service: SimpleNamespace,
    storage_service: SimpleNamespace,
    create_pool: AsyncMock,
) -> None:
    def make_async_client(*, timeout: float, base_url: str | None = None):
        if base_url is not None:
            assert timeout == 30.0
            return storage_http_client
        assert timeout == 5.0
        return http_client

    monkeypatch.setattr(app_main, "get_settings", lambda: settings)
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
        lambda _settings, _client: storage_service,
    )
    monkeypatch.setattr(app_main, "create_pool", create_pool)


@pytest.mark.asyncio
async def test_lifespan_loads_persona_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()
    (persona_dir / "IDENTITY.md").write_text("Test identity", encoding="utf-8")
    (persona_dir / "SOUL.md").write_text("Test soul", encoding="utf-8")
    (persona_dir / "BEHAVIOR.md").write_text("Test behavior", encoding="utf-8")
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "PROMOTIONS.md").write_text("Promo", encoding="utf-8")

    settings = _settings()
    settings.persona_dir = str(persona_dir)
    settings.config_dir = str(config_dir)
    (
        db_engine,
        redis_client,
        http_client,
        storage_http_client,
        qdrant_service,
        storage_service,
        create_pool,
    ) = _make_resource_bundle()
    _patch_lifespan_dependencies(
        monkeypatch,
        settings,
        db_engine=db_engine,
        redis_client=redis_client,
        http_client=http_client,
        storage_http_client=storage_http_client,
        qdrant_service=qdrant_service,
        storage_service=storage_service,
        create_pool=create_pool,
    )

    test_app = FastAPI()
    async with app_main.lifespan(test_app):
        assert test_app.state.persona_context.identity == "Test identity"
        assert test_app.state.persona_context.soul == "Test soul"
        assert test_app.state.persona_context.behavior == "Test behavior"
        assert len(test_app.state.persona_context.config_content_hash) == 64
        assert test_app.state.persona_context.config_commit_hash != ""
        assert test_app.state.promotions_service is not None
        assert test_app.state.conversation_memory_service is not None


def test_rate_limit_middleware_is_mounted() -> None:
    from app.middleware.rate_limit import RateLimitMiddleware

    middleware_classes = [middleware.cls for middleware in app_main.app.user_middleware]

    assert RateLimitMiddleware in middleware_classes


@pytest.mark.asyncio
async def test_lifespan_picks_up_changed_persona_on_restart(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir()
    (persona_dir / "IDENTITY.md").write_text("Original identity", encoding="utf-8")
    (persona_dir / "SOUL.md").write_text("Original soul", encoding="utf-8")
    (persona_dir / "BEHAVIOR.md").write_text("Original behavior", encoding="utf-8")
    config_dir = tmp_path / "config"
    config_dir.mkdir()

    settings = _settings()
    settings.persona_dir = str(persona_dir)
    settings.config_dir = str(config_dir)

    (
        db_engine,
        redis_client,
        http_client,
        storage_http_client,
        qdrant_service,
        storage_service,
        create_pool,
    ) = _make_resource_bundle()
    _patch_lifespan_dependencies(
        monkeypatch,
        settings,
        db_engine=db_engine,
        redis_client=redis_client,
        http_client=http_client,
        storage_http_client=storage_http_client,
        qdrant_service=qdrant_service,
        storage_service=storage_service,
        create_pool=create_pool,
    )

    first_app = FastAPI()
    async with app_main.lifespan(first_app):
        original_hash = first_app.state.persona_context.config_content_hash
        assert first_app.state.persona_context.soul == "Original soul"

    (persona_dir / "SOUL.md").write_text("Updated soul after edit", encoding="utf-8")

    (
        db_engine,
        redis_client,
        http_client,
        storage_http_client,
        qdrant_service,
        storage_service,
        create_pool,
    ) = _make_resource_bundle()
    _patch_lifespan_dependencies(
        monkeypatch,
        settings,
        db_engine=db_engine,
        redis_client=redis_client,
        http_client=http_client,
        storage_http_client=storage_http_client,
        qdrant_service=qdrant_service,
        storage_service=storage_service,
        create_pool=create_pool,
    )

    second_app = FastAPI()
    async with app_main.lifespan(second_app):
        assert second_app.state.persona_context.soul == "Updated soul after edit"
        assert second_app.state.persona_context.config_content_hash != original_hash
