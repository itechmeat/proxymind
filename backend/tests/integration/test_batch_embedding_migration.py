from __future__ import annotations

import asyncio
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _connection_url_to_env(url: str) -> dict[str, str]:
    parsed = urlparse(url)
    return {
        "POSTGRES_HOST": parsed.hostname or "127.0.0.1",
        "POSTGRES_PORT": str(parsed.port or 5432),
        "POSTGRES_USER": parsed.username or "postgres",
        "POSTGRES_PASSWORD": parsed.password or "postgres",
        "POSTGRES_DB": parsed.path.lstrip("/") or "postgres",
    }


def _make_alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


def _make_async_database_url(env: dict[str, str]) -> str:
    return (
        f"postgresql+asyncpg://{env['POSTGRES_USER']}:{env['POSTGRES_PASSWORD']}"
        f"@{env['POSTGRES_HOST']}:{env['POSTGRES_PORT']}/{env['POSTGRES_DB']}"
    )


@pytest.mark.asyncio
async def test_batch_embedding_migration_adds_enum_value_and_columns() -> None:
    with PostgresContainer("postgres:18") as postgres:
        env = _connection_url_to_env(postgres.get_connection_url())
        previous_values = {key: os.environ.get(key) for key in env}
        engine = None
        try:
            os.environ.update(env)
            get_settings.cache_clear()
            engine = create_async_engine(_make_async_database_url(env))
            config = _make_alembic_config()
            await asyncio.to_thread(command.upgrade, config, "head")

            async with engine.connect() as connection:
                task_type_values = [
                    row[0]
                    for row in (
                        await connection.execute(
                            text(
                                """
                                SELECT enumlabel
                                FROM pg_enum
                                JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
                                WHERE pg_type.typname = 'background_task_type_enum'
                                ORDER BY enumsortorder
                                """
                            )
                        )
                    )
                ]
                assert task_type_values == ["INGESTION", "BATCH_EMBEDDING"]

                columns = {
                    row[0]
                    for row in (
                        await connection.execute(
                            text(
                                """
                                SELECT column_name
                                FROM information_schema.columns
                                WHERE table_schema = 'public'
                                  AND table_name = 'batch_jobs'
                                """
                            )
                        )
                    )
                }
                assert {
                    "snapshot_id",
                    "source_ids",
                    "background_task_id",
                    "request_count",
                    "succeeded_count",
                    "failed_count",
                    "result_metadata",
                    "last_polled_at",
                } <= columns
        finally:
            if engine is not None:
                await engine.dispose()
            for key, value in previous_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            get_settings.cache_clear()
