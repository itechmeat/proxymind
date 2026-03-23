from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    postgres_host: str = Field(min_length=1)
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_user: str = Field(min_length=1)
    postgres_password: str = Field(min_length=1)
    postgres_db: str = Field(min_length=1)

    redis_host: str = Field(min_length=1)
    redis_port: int = Field(default=6379, ge=1, le=65535)

    qdrant_host: str = Field(min_length=1)
    qdrant_port: int = Field(default=6333, ge=1, le=65535)

    seaweedfs_host: str = Field(min_length=1)
    seaweedfs_filer_port: int = Field(default=8888, ge=1, le=65535)
    seaweedfs_sources_path: str = Field(default="/sources", min_length=1)

    gemini_api_key: str | None = Field(default=None)
    embedding_model: str = Field(default="gemini-embedding-2-preview", min_length=1)
    embedding_dimensions: int = Field(default=3072, ge=128, le=3072)
    embedding_task_type: str = Field(default="RETRIEVAL_DOCUMENT", min_length=1)
    embedding_batch_size: int = Field(default=100, ge=1)
    batch_embed_chunk_threshold: int = Field(default=50, ge=1)
    batch_poll_interval_seconds: int = Field(default=30, ge=1, le=60)
    batch_max_items_per_request: int = Field(default=1000, ge=1)
    gemini_content_model: str = Field(default="gemini-2.5-flash", min_length=1)
    gemini_file_upload_threshold_bytes: int = Field(default=10 * 1024 * 1024, ge=1)
    chunk_max_tokens: int = Field(default=1024, ge=1, le=8192)
    path_a_text_threshold_pdf: int = Field(default=2000, ge=1)
    path_a_text_threshold_media: int = Field(default=500, ge=1)
    path_a_max_pdf_pages: int = Field(default=6, ge=1)
    path_a_max_audio_duration_sec: int = Field(default=80, ge=1)
    path_a_max_video_duration_sec: int = Field(default=120, ge=1)
    qdrant_collection: str = Field(default="proxymind_chunks", min_length=1)
    bm25_language: str = Field(default="english", min_length=1)
    llm_model: str = Field(default="openai/gpt-4o", min_length=1)
    llm_api_key: str | None = Field(default=None)
    llm_api_base: str | None = Field(default=None)
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    retrieval_top_n: int = Field(default=5, ge=1)
    min_retrieved_chunks: int = Field(default=1, ge=0)
    min_dense_similarity: float | None = Field(default=None, ge=0.0, le=1.0)

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "info"
    upload_max_file_size_mb: int = Field(default=100, ge=1)

    model_config = SettingsConfigDict(
        env_file=(
            str(REPO_ROOT / ".env"),
            str(REPO_ROOT / "backend" / ".env"),
        ),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def validate_retrieval_settings(self) -> Settings:
        if self.min_retrieved_chunks > self.retrieval_top_n:
            raise ValueError(
                "MIN_RETRIEVED_CHUNKS must be less than or equal to RETRIEVAL_TOP_N"
            )
        if 60 % self.batch_poll_interval_seconds != 0:
            raise ValueError(
                "BATCH_POLL_INTERVAL_SECONDS must evenly divide 60 for the current arq cron schedule"
            )
        return self

    @computed_field
    @property
    def database_url(self) -> str:
        quoted_user = quote_plus(self.postgres_user)
        quoted_password = quote_plus(self.postgres_password)
        return (
            f"postgresql+asyncpg://{quoted_user}:{quoted_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field
    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/0"

    @computed_field
    @property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    @computed_field
    @property
    def seaweedfs_filer_url(self) -> str:
        return f"http://{self.seaweedfs_host}:{self.seaweedfs_filer_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
