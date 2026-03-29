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

    assert settings.gemini_content_model == "gemini-3-flash-preview"
    assert settings.google_genai_use_vertexai is False
    assert settings.google_cloud_project is None
    assert settings.google_cloud_location == "global"
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


def test_enrichment_settings_defaults() -> None:
    settings = Settings(**_base_settings())

    assert settings.enrichment_enabled is False
    assert settings.enrichment_model == "gemini-2.5-flash"
    assert settings.enrichment_max_concurrency == 10
    assert settings.enrichment_temperature == 0.1
    assert settings.enrichment_max_output_tokens == 512
    assert settings.enrichment_min_chunk_tokens == 10


def test_enrichment_settings_allow_overrides() -> None:
    settings = Settings(
        **_base_settings(),
        enrichment_enabled=True,
        enrichment_model="gemini-2.5-pro",
        enrichment_max_concurrency=4,
        enrichment_temperature=0.2,
        enrichment_max_output_tokens=256,
        enrichment_min_chunk_tokens=20,
    )

    assert settings.enrichment_enabled is True
    assert settings.enrichment_model == "gemini-2.5-pro"
    assert settings.enrichment_max_concurrency == 4
    assert settings.enrichment_temperature == 0.2
    assert settings.enrichment_max_output_tokens == 256
    assert settings.enrichment_min_chunk_tokens == 20


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


def test_conversation_memory_settings_defaults() -> None:
    settings = Settings(**_base_settings())

    assert settings.conversation_memory_budget == 4096
    assert settings.conversation_summary_ratio == 0.3
    assert settings.conversation_summary_model is None
    assert settings.conversation_summary_temperature == 0.1
    assert settings.conversation_summary_timeout_ms == 10000


def test_conversation_memory_settings_custom_values() -> None:
    settings = Settings(
        **_base_settings(),
        conversation_memory_budget=8192,
        conversation_summary_ratio=0.5,
        conversation_summary_model="gemini/gemini-2.0-flash",
        conversation_summary_temperature=0.2,
        conversation_summary_timeout_ms=5000,
    )

    assert settings.conversation_memory_budget == 8192
    assert settings.conversation_summary_ratio == 0.5
    assert settings.conversation_summary_model == "gemini/gemini-2.0-flash"
    assert settings.conversation_summary_temperature == 0.2
    assert settings.conversation_summary_timeout_ms == 5000


def test_conversation_memory_budget_rejects_non_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(**_base_settings(), conversation_memory_budget=0)


def test_conversation_summary_ratio_rejects_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        Settings(**_base_settings(), conversation_summary_ratio=-0.1)

    with pytest.raises(ValidationError):
        Settings(**_base_settings(), conversation_summary_ratio=1.1)


def test_conversation_summary_temperature_rejects_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        Settings(**_base_settings(), conversation_summary_temperature=-0.1)

    with pytest.raises(ValidationError):
        Settings(**_base_settings(), conversation_summary_temperature=2.1)


def test_conversation_summary_timeout_rejects_non_positive() -> None:
    with pytest.raises(ValidationError):
        Settings(**_base_settings(), conversation_summary_timeout_ms=0)


def test_empty_optional_provider_strings_are_normalized_to_none() -> None:
    settings = Settings(
        **_base_settings(),
        admin_api_key="",
        llm_api_key="",
        llm_api_base="",
        google_cloud_project="",
        rewrite_llm_model="",
        rewrite_llm_api_key="",
        rewrite_llm_api_base="",
        conversation_summary_model="",
    )

    assert settings.admin_api_key is None
    assert settings.llm_api_key is None
    assert settings.llm_api_base is None
    assert settings.google_cloud_project is None
    assert settings.rewrite_llm_model is None
    assert settings.rewrite_llm_api_key is None
    assert settings.rewrite_llm_api_base is None
    assert settings.conversation_summary_model is None


def test_vertex_ai_requires_project_or_api_key() -> None:
    with pytest.raises(
        ValidationError,
        match=(
            "GOOGLE_CLOUD_PROJECT or GEMINI_API_KEY is required when "
            "GOOGLE_GENAI_USE_VERTEXAI is enabled"
        ),
    ):
        Settings(**_base_settings(), google_genai_use_vertexai=True)


def test_vertex_ai_accepts_project_without_api_key() -> None:
    settings = Settings(
        **_base_settings(),
        google_genai_use_vertexai=True,
        google_cloud_project="test-project",
    )

    assert settings.google_genai_use_vertexai is True
    assert settings.google_cloud_project == "test-project"


def test_document_ai_partial_configuration_is_rejected() -> None:
    message = (
        "DOCUMENT_AI_PROJECT_ID and DOCUMENT_AI_PROCESSOR_ID must either both "
        "be set or both be empty"
    )
    with pytest.raises(
        ValidationError,
        match=message,
    ):
        Settings(**_base_settings(), document_ai_project_id="project")


def test_document_ai_processor_without_project_is_rejected() -> None:
    message = (
        "DOCUMENT_AI_PROJECT_ID and DOCUMENT_AI_PROCESSOR_ID must either both "
        "be set or both be empty"
    )
    with pytest.raises(
        ValidationError,
        match=message,
    ):
        Settings(**_base_settings(), document_ai_processor_id="processor")


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


def test_security_settings_defaults() -> None:
    settings = Settings(**_base_settings())

    assert settings.admin_api_key is None
    assert settings.chat_rate_limit == 60
    assert settings.chat_rate_window_seconds == 60
    assert settings.trusted_proxy_depth == 1


def test_security_settings_custom_values() -> None:
    settings = Settings(
        **_base_settings(),
        admin_api_key="test-secret-key-123",
        chat_rate_limit=120,
        chat_rate_window_seconds=30,
        trusted_proxy_depth=2,
    )

    assert settings.admin_api_key is not None
    assert settings.admin_api_key.get_secret_value() == "test-secret-key-123"
    assert settings.chat_rate_limit == 120
    assert settings.chat_rate_window_seconds == 30
    assert settings.trusted_proxy_depth == 2
