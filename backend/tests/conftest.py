from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.postgres import PostgresContainer

from app.core.config import get_settings
from app.db.engine import create_database_engine, create_session_factory
from app.db.models import Agent

pytest_plugins = ("pytest_asyncio",)
asyncio_mode = "auto"

BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_AGENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _connection_url_to_env(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    return {
        "POSTGRES_HOST": parsed.hostname or "127.0.0.1",
        "POSTGRES_PORT": str(parsed.port or 5432),
        "POSTGRES_USER": parsed.username or "postgres",
        "POSTGRES_PASSWORD": parsed.password or "postgres",
        "POSTGRES_DB": parsed.path.lstrip("/") or "postgres",
    }


@pytest.fixture(scope="session")
def postgres_env() -> dict[str, str]:
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
