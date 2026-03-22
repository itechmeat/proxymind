from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _base_settings() -> dict[str, object]:
    return {
        "postgres_host": "localhost",
        "postgres_port": 5432,
        "postgres_user": "proxymind",
        "postgres_password": "proxymind",
        "postgres_db": "proxymind",
        "redis_host": "localhost",
        "redis_port": 6379,
        "qdrant_host": "localhost",
        "qdrant_port": 6333,
        "minio_host": "localhost",
        "minio_port": 9000,
        "minio_root_user": "proxymind",
        "minio_root_password": "proxymind",
    }


def test_settings_reject_impossible_retrieval_thresholds() -> None:
    with pytest.raises(
        ValidationError,
        match="MIN_RETRIEVED_CHUNKS must be less than or equal to RETRIEVAL_TOP_N",
    ):
        Settings(**_base_settings(), retrieval_top_n=2, min_retrieved_chunks=3)


def test_settings_allow_zero_minimum_retrieved_chunks() -> None:
    settings = Settings(**_base_settings(), retrieval_top_n=2, min_retrieved_chunks=0)

    assert settings.min_retrieved_chunks == 0
