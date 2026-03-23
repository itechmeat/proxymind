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
        "seaweedfs_host": "localhost",
        "seaweedfs_filer_port": 8888,
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


def test_settings_include_path_a_defaults() -> None:
    settings = Settings(**_base_settings())

    assert settings.gemini_content_model == "gemini-2.5-flash"
    assert settings.gemini_file_upload_threshold_bytes == 10 * 1024 * 1024
    assert settings.path_a_text_threshold_pdf == 2000
    assert settings.path_a_text_threshold_media == 500
    assert settings.path_a_max_pdf_pages == 6
    assert settings.path_a_max_audio_duration_sec == 80
    assert settings.path_a_max_video_duration_sec == 120


def test_batch_config_defaults() -> None:
    settings = Settings(**_base_settings())

    assert settings.batch_embed_chunk_threshold == 50
    assert settings.batch_poll_interval_seconds == 30
    assert settings.batch_max_items_per_request == 1000


def test_batch_poll_interval_must_divide_minute() -> None:
    with pytest.raises(
        ValidationError,
        match="BATCH_POLL_INTERVAL_SECONDS must evenly divide 60",
    ):
        Settings(**_base_settings(), batch_poll_interval_seconds=45)


def test_sse_settings_have_defaults() -> None:
    settings = Settings(**_base_settings())

    assert settings.sse_heartbeat_interval_seconds == 15
    assert settings.sse_inter_token_timeout_seconds == 30


def test_sse_settings_reject_non_positive_values() -> None:
    with pytest.raises(ValidationError):
        Settings(**_base_settings(), sse_heartbeat_interval_seconds=0)

    with pytest.raises(ValidationError):
        Settings(**_base_settings(), sse_inter_token_timeout_seconds=0)
