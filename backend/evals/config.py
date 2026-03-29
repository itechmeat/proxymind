from __future__ import annotations

import os
import uuid
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ThresholdZone(BaseModel):
    green_above: float = Field(ge=0.0, le=1.0)
    red_below: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> ThresholdZone:
        if self.red_below > self.green_above:
            raise ValueError("red_below must be less than or equal to green_above")
        return self

    def classify(self, score: float) -> str:
        if score > self.green_above:
            return "GREEN"
        if score < self.red_below:
            return "RED"
        return "YELLOW"


DEFAULT_THRESHOLDS: dict[str, ThresholdZone] = {
    "precision_at_k": ThresholdZone(green_above=0.70, red_below=0.50),
    "recall_at_k": ThresholdZone(green_above=0.70, red_below=0.50),
    "mrr": ThresholdZone(green_above=0.60, red_below=0.40),
    "groundedness": ThresholdZone(green_above=0.75, red_below=0.50),
    "citation_accuracy": ThresholdZone(green_above=0.70, red_below=0.50),
    "persona_fidelity": ThresholdZone(green_above=0.70, red_below=0.50),
    "refusal_quality": ThresholdZone(green_above=0.80, red_below=0.60),
}


class EvalConfig(BaseModel):
    base_url: str = Field(default="http://localhost:8000")
    admin_key: str = Field(default="")
    top_n: int = Field(default=5, ge=1, le=50)
    output_dir: str = Field(default="evals/reports")
    snapshot_id: uuid.UUID | None = Field(default=None)
    dataset_path: str | None = Field(default=None)
    tags: list[str] = Field(default_factory=list)
    judge_model: str | None = Field(default=None)
    persona_path: str = Field(default="persona/")
    seed_persona_path: str = Field(default="evals/seed_persona/")
    thresholds: dict[str, ThresholdZone] = Field(
        default_factory=lambda: dict(DEFAULT_THRESHOLDS)
    )

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
        judge_model: str | None = None,
        persona_path: str | None = None,
        seed_persona_path: str | None = None,
    ) -> EvalConfig:
        defaults: dict[str, Any] = {}
        env_key = os.environ.get("PROXYMIND_ADMIN_API_KEY", "")
        if env_key:
            defaults["admin_key"] = env_key
        env_url = os.environ.get("PROXYMIND_EVAL_BASE_URL", "")
        if env_url:
            defaults["base_url"] = env_url
        env_judge_model = os.environ.get("EVAL_JUDGE_MODEL", "")
        if env_judge_model:
            defaults["judge_model"] = env_judge_model

        overrides = {
            "base_url": base_url,
            "admin_key": admin_key,
            "top_n": top_n,
            "output_dir": output_dir,
            "snapshot_id": snapshot_id,
            "dataset_path": dataset_path,
            "tags": tags,
            "judge_model": judge_model,
            "persona_path": persona_path,
            "seed_persona_path": seed_persona_path,
        }
        defaults.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**defaults)
