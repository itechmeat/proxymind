from __future__ import annotations

import asyncio
import hashlib
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = BACKEND_DIR / "migrations"
_VALID_DB_NAME = re.compile(r"^[A-Za-z0-9_]+$")
_PREPARED_TEMPLATES: set[str] = set()


def _connection_url_to_env(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    return {
        "POSTGRES_HOST": parsed.hostname or "127.0.0.1",
        "POSTGRES_PORT": str(parsed.port or 5432),
        "POSTGRES_USER": parsed.username or "postgres",
        "POSTGRES_PASSWORD": parsed.password or "postgres",
        "POSTGRES_DB": parsed.path.lstrip("/") or "postgres",
    }


def make_async_database_url(env: dict[str, str]) -> str:
    return (
        f"postgresql+asyncpg://{env['POSTGRES_USER']}:{env['POSTGRES_PASSWORD']}"
        f"@{env['POSTGRES_HOST']}:{env['POSTGRES_PORT']}/{env['POSTGRES_DB']}"
    )


def _quote_identifier(name: str) -> str:
    if _VALID_DB_NAME.fullmatch(name) is None:
        raise ValueError(f"Unsupported database identifier: {name}")
    return f'"{name}"'


def _make_alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    return config


def _migration_template_name(base_revision: str) -> str:
    digest = hashlib.sha1()
    for path in sorted((MIGRATIONS_DIR / "versions").glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return f"test_template_{base_revision}_{digest.hexdigest()[:10]}"


async def _database_exists(connection, database_name: str) -> bool:
    result = await connection.execute(
        text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
        {"database_name": database_name},
    )
    return result.scalar() == 1


async def _terminate_database_connections(connection, database_name: str) -> None:
    await connection.execute(
        text(
            """
            SELECT pg_terminate_backend(pid)
            FROM pg_stat_activity
            WHERE datname = :database_name
              AND pid <> pg_backend_pid()
            """
        ),
        {"database_name": database_name},
    )


async def _prepare_template_database(base_env: dict[str, str], base_revision: str) -> str:
    template_db_name = _migration_template_name(base_revision)
    if template_db_name in _PREPARED_TEMPLATES:
        return template_db_name

    admin_engine = create_async_engine(
        make_async_database_url(base_env),
        isolation_level="AUTOCOMMIT",
    )
    created = False

    try:
        async with admin_engine.connect() as connection:
            if not await _database_exists(connection, template_db_name):
                await connection.execute(
                    text(f"CREATE DATABASE {_quote_identifier(template_db_name)}")
                )
                created = True

        if created:
            template_env = {**base_env, "POSTGRES_DB": template_db_name}
            previous_values = {key: os.environ.get(key) for key in template_env}
            try:
                os.environ.update(template_env)
                get_settings.cache_clear()
                config = _make_alembic_config()
                await asyncio.to_thread(command.upgrade, config, base_revision)
            finally:
                for key, value in previous_values.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                get_settings.cache_clear()
    finally:
        await admin_engine.dispose()

    _PREPARED_TEMPLATES.add(template_db_name)
    return template_db_name


@asynccontextmanager
async def migration_test_env(*, base_revision: str | None = None):
    if os.environ.get("PYTEST_USE_EXISTING_POSTGRES") != "1":
        with PostgresContainer("postgres:18") as postgres:
            yield _connection_url_to_env(postgres.get_connection_url())
        return

    base_env = {
        "POSTGRES_HOST": os.environ["POSTGRES_HOST"],
        "POSTGRES_PORT": os.environ["POSTGRES_PORT"],
        "POSTGRES_USER": os.environ["POSTGRES_USER"],
        "POSTGRES_PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "POSTGRES_DB": os.environ["POSTGRES_DB"],
    }
    template_db_name = None
    if base_revision is not None:
        template_db_name = await _prepare_template_database(base_env, base_revision)

    temp_db_name = f"test_migration_{uuid.uuid4().hex}"
    temp_env = {**base_env, "POSTGRES_DB": temp_db_name}
    admin_engine = create_async_engine(
        make_async_database_url(base_env),
        isolation_level="AUTOCOMMIT",
    )

    try:
        async with admin_engine.connect() as connection:
            if template_db_name is None:
                await connection.execute(text(f"CREATE DATABASE {_quote_identifier(temp_db_name)}"))
            else:
                await connection.execute(
                    text(
                        f"CREATE DATABASE {_quote_identifier(temp_db_name)} TEMPLATE {_quote_identifier(template_db_name)}"
                    )
                )
        yield temp_env
    finally:
        async with admin_engine.connect() as connection:
            await _terminate_database_connections(connection, temp_db_name)
            await connection.execute(text(f"DROP DATABASE IF EXISTS {_quote_identifier(temp_db_name)}"))
        await admin_engine.dispose()
