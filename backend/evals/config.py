from __future__ import annotations

import os
import uuid
from typing import Any

from pydantic import BaseModel, Field


class EvalConfig(BaseModel):
    base_url: str = Field(default="http://localhost:8000")
    admin_key: str = Field(default="")
    top_n: int = Field(default=5, ge=1, le=50)
    output_dir: str = Field(default="evals/reports")
    snapshot_id: uuid.UUID | None = Field(default=None)
    dataset_path: str | None = Field(default=None)
    tags: list[str] = Field(default_factory=list)

    @classmethod
    def from_env(
        cls,
        *,
        base_url: str | None = None,
        admin_key: str | None = None,
        top_n: int | None = None,
        output_dir: str | None = None,
        snapshot_id: uuid.UUID | None = None,
        dataset_path: str | None = None,
        tags: list[str] | None = None,
    ) -> EvalConfig:
        defaults: dict[str, Any] = {}
        env_key = os.environ.get("PROXYMIND_ADMIN_API_KEY", "")
        if env_key:
            defaults["admin_key"] = env_key
        env_url = os.environ.get("PROXYMIND_EVAL_BASE_URL", "")
        if env_url:
            defaults["base_url"] = env_url

        overrides = {
            "base_url": base_url,
            "admin_key": admin_key,
            "top_n": top_n,
            "output_dir": output_dir,
            "snapshot_id": snapshot_id,
            "dataset_path": dataset_path,
            "tags": tags,
        }
        defaults.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**defaults)
