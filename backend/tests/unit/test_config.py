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


def test_rewrite_settings_defaults() -> None:
    settings = Settings(**_base_settings())

    assert settings.rewrite_enabled is True
    assert settings.rewrite_llm_model is None
    assert settings.rewrite_llm_api_key is None
    assert settings.rewrite_llm_api_base is None
    assert settings.rewrite_temperature == 0.1
    assert settings.rewrite_timeout_ms == 3000
    assert settings.rewrite_token_budget == 2048
    assert settings.rewrite_history_messages == 10


def test_rewrite_settings_custom() -> None:
    settings = Settings(
        **_base_settings(),
        rewrite_enabled=False,
        rewrite_llm_model="gemini/gemini-2.0-flash",
        rewrite_temperature=0.0,
        rewrite_timeout_ms=5000,
        rewrite_token_budget=1024,
        rewrite_history_messages=5,
    )

    assert settings.rewrite_enabled is False
    assert settings.rewrite_llm_model == "gemini/gemini-2.0-flash"
    assert settings.rewrite_temperature == 0.0
    assert settings.rewrite_timeout_ms == 5000
    assert settings.rewrite_token_budget == 1024
    assert settings.rewrite_history_messages == 5


def test_rewrite_timeout_rejects_non_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(**_base_settings(), rewrite_timeout_ms=0)


def test_rewrite_token_budget_rejects_non_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(**_base_settings(), rewrite_token_budget=0)


def test_rewrite_history_messages_rejects_non_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(**_base_settings(), rewrite_history_messages=0)


def test_empty_optional_provider_strings_are_normalized_to_none() -> None:
    settings = Settings(
        **_base_settings(),
        llm_api_key="",
        llm_api_base="",
        rewrite_llm_model="",
        rewrite_llm_api_key="",
        rewrite_llm_api_base="",
    )

    assert settings.llm_api_key is None
    assert settings.llm_api_base is None
    assert settings.rewrite_llm_model is None
    assert settings.rewrite_llm_api_key is None
    assert settings.rewrite_llm_api_base is None


def test_document_ai_partial_configuration_is_rejected() -> None:
    with pytest.raises(
        ValidationError,
        match="DOCUMENT_AI_PROCESSOR_ID is required when DOCUMENT_AI_PROJECT_ID is set",
    ):
        Settings(**_base_settings(), document_ai_project_id="project")


def test_document_ai_enabled_when_project_and_processor_are_set() -> None:
    settings = Settings(
        **_base_settings(),
        document_ai_project_id="project",
        document_ai_processor_id="processor",
    )

    assert settings.document_ai_enabled is True


def test_max_citations_per_response_default() -> None:
    settings = Settings(**_base_settings())

    assert settings.max_citations_per_response == 5


def test_max_citations_per_response_custom() -> None:
    settings = Settings(**_base_settings(), max_citations_per_response=10)

    assert settings.max_citations_per_response == 10


def test_max_citations_per_response_rejects_non_positive_value() -> None:
    with pytest.raises(ValidationError):
        Settings(**_base_settings(), max_citations_per_response=0)
