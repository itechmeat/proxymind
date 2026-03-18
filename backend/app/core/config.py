from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic import Field, computed_field
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

    minio_host: str = Field(min_length=1)
    minio_port: int = Field(default=9000, ge=1, le=65535)
    minio_root_user: str = Field(min_length=1)
    minio_root_password: str = Field(min_length=1)
    minio_bucket_sources: str = Field(default="sources", min_length=1)

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "info"
    upload_max_file_size_mb: int = Field(default=50, ge=1)

    model_config = SettingsConfigDict(
        env_file=(
            str(REPO_ROOT / ".env"),
            str(REPO_ROOT / "backend" / ".env"),
        ),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

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
    def minio_url(self) -> str:
        return f"http://{self.minio_host}:{self.minio_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
