from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from tests.integration._migration_db import make_async_database_url, migration_test_env

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _make_alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return config


@pytest.mark.asyncio
async def test_batch_embedding_migration_adds_enum_value_and_columns() -> None:
    async with migration_test_env(base_revision="005") as env:
        previous_values = {key: os.environ.get(key) for key in env}
        engine = None
        try:
            os.environ.update(env)
            get_settings.cache_clear()
            engine = create_async_engine(make_async_database_url(env))
            config = _make_alembic_config()
            await asyncio.to_thread(command.upgrade, config, "006")

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
