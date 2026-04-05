from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import urlparse

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.core.container import DockerContainer
from testcontainers.postgres import PostgresContainer

from app.core.config import get_settings
from app.core.constants import DEFAULT_AGENT_ID
from app.db.engine import create_database_engine, create_session_factory
from app.db.models import Agent, User, UserProfile
from app.db.models.enums import UserStatus
from app.services.jwt_tokens import create_access_token
from app.services.conversation_memory import ConversationMemoryService
from app.services.promotions import PromotionsService
from app.services.storage import StorageService

pytest_plugins = ("pytest_asyncio",)
asyncio_mode = "auto"

BACKEND_DIR = Path(__file__).resolve().parents[1]
TRUNCATE_TEST_DATA_SQL = text(
    """
    TRUNCATE TABLE
      background_tasks,
      user_refresh_tokens,
      user_tokens,
      user_profiles,
      users,
            chunk_parents,
      chunks,
      document_versions,
      documents,
      sources,
      messages,
      sessions,
      audit_logs,
      batch_jobs,
      catalog_items,
      embedding_profiles
    RESTART IDENTITY CASCADE
    """
)
DELETE_KNOWLEDGE_SNAPSHOTS_SQL = text("DELETE FROM knowledge_snapshots")
TEST_ADMIN_API_KEY = "conftest-test-key-for-admin"
TEST_JWT_SECRET = SecretStr("test-jwt-secret-key-with-32-plus-chars")


def _connection_url_to_env(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    return {
        "POSTGRES_HOST": parsed.hostname or "127.0.0.1",
        "POSTGRES_PORT": str(parsed.port or 5432),
        "POSTGRES_USER": parsed.username or "postgres",
        "POSTGRES_PASSWORD": parsed.password or "postgres",
        "POSTGRES_DB": parsed.path.lstrip("/") or "postgres",
        "DOCUMENT_AI_PROJECT_ID": "",
        "DOCUMENT_AI_PROCESSOR_ID": "",
    }


def _existing_postgres_env() -> dict[str, str]:
    return {
        "POSTGRES_HOST": os.environ["POSTGRES_HOST"],
        "POSTGRES_PORT": os.environ["POSTGRES_PORT"],
        "POSTGRES_USER": os.environ["POSTGRES_USER"],
        "POSTGRES_PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "POSTGRES_DB": os.environ["POSTGRES_DB"],
        "DOCUMENT_AI_PROJECT_ID": "",
        "DOCUMENT_AI_PROCESSOR_ID": "",
    }


def _database_url(env: dict[str, str], database_name: str | None = None) -> str:
    database = database_name or env["POSTGRES_DB"]
    return (
        f"postgresql+asyncpg://{env['POSTGRES_USER']}:{env['POSTGRES_PASSWORD']}"
        f"@{env['POSTGRES_HOST']}:{env['POSTGRES_PORT']}/{database}"
    )


async def _ensure_database_exists(env: dict[str, str]) -> None:
    admin_engine = create_async_engine(
        _database_url(env, "postgres"),
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with admin_engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": env["POSTGRES_DB"]},
            )
            if exists is None:
                await connection.execute(text(f'CREATE DATABASE "{env["POSTGRES_DB"]}"'))
    finally:
        await admin_engine.dispose()


def _wait_for_qdrant(url: str) -> str:
    deadline = time.time() + 30
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            response = httpx.get(f"{url}/collections", timeout=2.0)
            if response.status_code == 200:
                return url
        except Exception as error:  # pragma: no cover - best effort wait loop
            last_error = error
        time.sleep(1)

    raise RuntimeError("Qdrant test service did not become ready") from last_error


@pytest.fixture(scope="session")
def postgres_env() -> dict[str, str]:
    if os.environ.get("PYTEST_USE_EXISTING_POSTGRES") == "1":
        env = _existing_postgres_env()
        db_name = env["POSTGRES_DB"].lower()
        if not (db_name.endswith("_test") or db_name.startswith("test_")):
            raise RuntimeError(
                f"Refusing to run tests against database '{env['POSTGRES_DB']}'. "
                "POSTGRES_DB must start with 'test_' or end with '_test' when "
                "using PYTEST_USE_EXISTING_POSTGRES=1."
            )
        asyncio.run(_ensure_database_exists(env))
        previous_values = {key: os.environ.get(key) for key in env}
        os.environ.update(env)
        get_settings.cache_clear()
        try:
            yield env
        finally:
            for key, value in previous_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            get_settings.cache_clear()
        return

    with PostgresContainer("postgres:18") as postgres:
        env = _connection_url_to_env(postgres.get_connection_url())
        previous_values = {key: os.environ.get(key) for key in env}
        os.environ.update(env)
        get_settings.cache_clear()
        try:
            yield env
        finally:
            for key, value in previous_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            get_settings.cache_clear()


@pytest.fixture(scope="session")
def alembic_config(postgres_env: dict[str, str]) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


@pytest.fixture(scope="session")
def migrated_database(postgres_env: dict[str, str], alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    yield


@pytest_asyncio.fixture
async def db_engine(
    migrated_database: None,
    postgres_env: dict[str, str],
) -> AsyncEngine:
    settings = get_settings()
    engine = create_database_engine(settings)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(db_engine)


@pytest_asyncio.fixture
async def db_session(db_engine: AsyncEngine) -> AsyncSession:
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest_asyncio.fixture
async def seeded_agent(db_session: AsyncSession) -> Agent:
    agent = await db_session.scalar(select(Agent).where(Agent.id == DEFAULT_AGENT_ID))
    assert agent is not None
    return agent


@pytest.fixture
def mock_storage_service() -> SimpleNamespace:
    return SimpleNamespace(
        generate_object_key=StorageService.generate_object_key,
        ensure_storage_root=AsyncMock(),
        download=AsyncMock(return_value=b"avatar-bytes"),
        upload=AsyncMock(),
        delete=AsyncMock(),
    )


@pytest.fixture
def mock_arq_pool() -> SimpleNamespace:
    return SimpleNamespace(
        enqueue_job=AsyncMock(return_value=SimpleNamespace(job_id="job-123")),
        close=AsyncMock(),
    )


@pytest.fixture
def admin_app(
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
    mock_arq_pool: SimpleNamespace,
) -> FastAPI:
    from app.api.admin import router as admin_router

    app = FastAPI()
    app.include_router(admin_router)
    app.state.settings = SimpleNamespace(
        admin_api_key=TEST_ADMIN_API_KEY,
        upload_max_file_size_mb=100,
        seaweedfs_sources_path="/sources",
        bm25_language="english",
        batch_max_items_per_request=1000,
    )
    app.state.session_factory = session_factory
    app.state.storage_service = mock_storage_service
    app.state.arq_pool = mock_arq_pool
    app.state.embedding_service = SimpleNamespace(
        model="gemini-embedding-2-preview",
        dimensions=3,
        embed_texts=AsyncMock(return_value=[[0.1, 0.2, 0.3]]),
        embed_file=AsyncMock(return_value=[0.1, 0.2, 0.3]),
    )
    app.state.qdrant_service = SimpleNamespace(
        hybrid_search=AsyncMock(return_value=[]),
        dense_search=AsyncMock(return_value=[]),
        keyword_search=AsyncMock(return_value=[]),
        delete_chunks=AsyncMock(),
        bm25_language="english",
        sparse_backend="bm25",
        sparse_model="Qdrant/bm25",
    )
    return app


@pytest.fixture
def mock_retrieval_service() -> SimpleNamespace:
    return SimpleNamespace(search=AsyncMock(return_value=[]))


@pytest.fixture
def mock_llm_service() -> SimpleNamespace:
    from app.services.llm_types import LLMResponse, LLMStreamEnd, LLMToken

    async def _fake_stream(*args, **kwargs):
        yield LLMToken(content="Assistant")
        yield LLMToken(content=" answer")
        yield LLMStreamEnd(
            model_name="openai/gpt-4o",
            token_count_prompt=10,
            token_count_completion=5,
        )

    return SimpleNamespace(
        complete=AsyncMock(
            return_value=LLMResponse(
                content="Assistant answer",
                model_name="openai/gpt-4o",
                token_count_prompt=10,
                token_count_completion=5,
            )
        ),
        stream=AsyncMock(side_effect=_fake_stream),
    )


@pytest.fixture
def mock_rewrite_service() -> SimpleNamespace:
    from app.services.query_rewrite import RewriteResult

    async def _no_rewrite(query, history, **kwargs):
        return RewriteResult(query=query, is_rewritten=False, original_query=query)

    return SimpleNamespace(rewrite=AsyncMock(side_effect=_no_rewrite))


@pytest.fixture
def mock_memory_service() -> ConversationMemoryService:
    service = SimpleNamespace()
    service.build_memory_block = MagicMock(side_effect=AssertionError("override in test"))
    return service  # type: ignore[return-value]


@pytest.fixture
def sample_retrieved_chunk() -> object:
    from app.services.qdrant import RetrievedChunk

    return RetrievedChunk(
        chunk_id=uuid.uuid7(),
        source_id=uuid.uuid7(),
        text_content="retrieved chunk",
        score=0.9,
        anchor_metadata={
            "anchor_page": None,
            "anchor_chapter": None,
            "anchor_section": None,
            "anchor_timecode": None,
        },
    )


@pytest.fixture
def chat_app(
    session_factory: async_sessionmaker[AsyncSession],
    mock_retrieval_service: SimpleNamespace,
    mock_llm_service: SimpleNamespace,
    mock_rewrite_service: SimpleNamespace,
    mock_arq_pool: SimpleNamespace,
) -> FastAPI:
    from app.api.chat import router as chat_router
    from app.persona.loader import PersonaContext

    app = FastAPI()
    app.include_router(chat_router)
    app.state.settings = SimpleNamespace(
        min_retrieved_chunks=1,
        max_citations_per_response=5,
        retrieval_context_budget=4096,
        max_promotions_per_response=1,
        sse_heartbeat_interval_seconds=15,
        sse_inter_token_timeout_seconds=30,
        conversation_memory_budget=4096,
        conversation_summary_ratio=0.3,
        jwt_secret_key=TEST_JWT_SECRET,
        jwt_access_token_expire_minutes=15,
    )
    app.state.session_factory = session_factory
    app.state.retrieval_service = mock_retrieval_service
    app.state.llm_service = mock_llm_service
    app.state.query_rewrite_service = mock_rewrite_service
    app.state.arq_pool = mock_arq_pool
    app.state.persona_context = PersonaContext(
        identity="Test twin identity",
        soul="Test twin soul",
        behavior="Test twin behavior",
        config_commit_hash="test-commit-sha",
        config_content_hash="test-content-hash",
    )
    app.state.promotions_service = PromotionsService(promotions_text="")
    app.state.conversation_memory_service = ConversationMemoryService(
        budget=4096,
        summary_ratio=0.3,
    )
    return app


@pytest_asyncio.fixture
async def create_user(
    session_factory: async_sessionmaker[AsyncSession],
):
    async def _create(
        *,
        email: str | None = None,
        status: UserStatus = UserStatus.ACTIVE,
        display_name: str | None = "Test User",
    ) -> User:
        async with session_factory() as session:
            user = User(
                id=uuid.uuid7(),
                email=email or f"user-{uuid.uuid4()}@example.com",
                password_hash="hashed-password",
                status=status,
                email_verified_at=datetime.now(UTC) if status is UserStatus.ACTIVE else None,
            )
            profile = UserProfile(
                id=uuid.uuid7(),
                user=user,
                display_name=display_name,
            )
            session.add_all([user, profile])
            await session.commit()
            await session.refresh(user)
            return user

    return _create


@pytest.fixture
def make_user_auth_headers():
    def _make(user: User) -> dict[str, str]:
        token = create_access_token(
            user_id=user.id,
            secret_key=TEST_JWT_SECRET.get_secret_value(),
            expires_minutes=15,
        )
        return {"Authorization": f"Bearer {token}"}

    return _make


@pytest_asyncio.fixture
async def chat_client(
    chat_app: FastAPI,
    create_user,
    make_user_auth_headers,
) -> httpx.AsyncClient:
    user = await create_user()
    transport = httpx.ASGITransport(app=chat_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=make_user_auth_headers(user),
    ) as client:
        yield client


@pytest_asyncio.fixture
async def guest_chat_client(chat_app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=chat_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest_asyncio.fixture
async def api_client(admin_app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=admin_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {TEST_ADMIN_API_KEY}"},
    ) as client:
        yield client


@pytest.fixture
def profile_app(
    session_factory: async_sessionmaker[AsyncSession],
    mock_storage_service: SimpleNamespace,
) -> FastAPI:
    from app.api.profile import admin_router as profile_admin_router
    from app.api.profile import chat_router as profile_chat_router

    app = FastAPI()
    app.include_router(profile_chat_router)
    app.include_router(profile_admin_router)
    app.state.settings = SimpleNamespace(
        admin_api_key=TEST_ADMIN_API_KEY,
        jwt_secret_key=TEST_JWT_SECRET,
    )
    app.state.session_factory = session_factory
    app.state.storage_service = mock_storage_service
    return app


@pytest_asyncio.fixture
async def profile_client(profile_app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=profile_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {TEST_ADMIN_API_KEY}"},
    ) as client:
        yield client


@pytest_asyncio.fixture
async def user_profile_client(
    profile_app: FastAPI,
    create_user,
    make_user_auth_headers,
) -> httpx.AsyncClient:
    user = await create_user()
    transport = httpx.ASGITransport(app=profile_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers=make_user_auth_headers(user),
    ) as client:
        yield client


@pytest_asyncio.fixture
async def committed_data_cleanup(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await session.execute(TRUNCATE_TEST_DATA_SQL)
        # knowledge_snapshots cannot participate in the shared TRUNCATE ... CASCADE
        # helper because that would also truncate the seeded agents table via
        # agents.active_snapshot_id -> knowledge_snapshots.
        await session.execute(DELETE_KNOWLEDGE_SNAPSHOTS_SQL)
        await session.commit()

    yield

    async with session_factory() as session:
        await session.execute(TRUNCATE_TEST_DATA_SQL)
        await session.execute(DELETE_KNOWLEDGE_SNAPSHOTS_SQL)
        await session.commit()


@pytest.fixture(scope="session")
def qdrant_url() -> str:
    if os.environ.get("PYTEST_USE_EXISTING_QDRANT") == "1":
        yield _wait_for_qdrant(os.environ["QDRANT_URL"])
        return

    with DockerContainer("qdrant/qdrant:v1.17.0").with_exposed_ports(6333) as container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(6333)
        yield _wait_for_qdrant(f"http://{host}:{port}")
