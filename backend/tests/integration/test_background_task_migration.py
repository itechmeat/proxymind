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
async def test_background_task_migration_creates_and_drops_table() -> None:
    with PostgresContainer("postgres:18") as postgres:
        env = _connection_url_to_env(postgres.get_connection_url())
        previous_values = {key: os.environ.get(key) for key in env}
        engine = None
        try:
            os.environ.update(env)
            get_settings.cache_clear()
            engine = create_async_engine(_make_async_database_url(env))
            config = _make_alembic_config()
            await asyncio.to_thread(command.upgrade, config, "003")

            async with engine.connect() as connection:
                tables = {
                    row[0]
                    for row in (
                        await connection.execute(
                            text(
                                """
                                SELECT table_name
                                FROM information_schema.tables
                                WHERE table_schema = 'public'
                                """
                            )
                        )
                    )
                }
                assert "background_tasks" in tables

                columns = {
                    row[0]
                    for row in (
                        await connection.execute(
                            text(
                                """
                                SELECT column_name
                                FROM information_schema.columns
                                WHERE table_schema = 'public'
                                  AND table_name = 'background_tasks'
                                """
                            )
                        )
                    )
                }
                assert {
                    "id",
                    "task_type",
                    "status",
                    "source_id",
                    "arq_job_id",
                    "error_message",
                    "progress",
                    "result_metadata",
                    "started_at",
                    "completed_at",
                    "owner_id",
                    "agent_id",
                    "created_at",
                    "updated_at",
                } <= columns

                status_values = [
                    row[0]
                    for row in (
                        await connection.execute(
                            text(
                                """
                                SELECT enumlabel
                                FROM pg_enum
                                JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
                                WHERE pg_type.typname = 'background_task_status_enum'
                                ORDER BY enumsortorder
                                """
                            )
                        )
                    )
                ]
                assert status_values == [
                    "PENDING",
                    "PROCESSING",
                    "COMPLETE",
                    "FAILED",
                    "CANCELLED",
                ]

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
                assert task_type_values == ["INGESTION"]

            await asyncio.to_thread(command.downgrade, config, "002")

            async with engine.connect() as connection:
                dropped_tables = {
                    row[0]
                    for row in (
                        await connection.execute(
                            text(
                                """
                                SELECT table_name
                                FROM information_schema.tables
                                WHERE table_schema = 'public'
                                """
                            )
                        )
                    )
                }
                assert "background_tasks" not in dropped_tables

                remaining_types = {
                    row[0]
                    for row in (
                        await connection.execute(
                            text(
                                """
                                SELECT typname
                                FROM pg_type
                                WHERE typname IN (
                                  'background_task_type_enum',
                                  'background_task_status_enum'
                                )
                                """
                            )
                        )
                    )
                }
                assert remaining_types == set()
        finally:
            if engine is not None:
                await engine.dispose()
            for key, value in previous_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            get_settings.cache_clear()
