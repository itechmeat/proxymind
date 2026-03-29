from __future__ import annotations

import os
from unittest.mock import patch

from evals.config import DEFAULT_THRESHOLDS, EvalConfig, ThresholdZone


class TestThresholdZone:
    def test_classify_green(self) -> None:
        zone = ThresholdZone(green_above=0.7, red_below=0.5)
        assert zone.classify(0.8) == "GREEN"

    def test_classify_yellow(self) -> None:
        zone = ThresholdZone(green_above=0.7, red_below=0.5)
        assert zone.classify(0.6) == "YELLOW"

    def test_classify_red(self) -> None:
        zone = ThresholdZone(green_above=0.7, red_below=0.5)
        assert zone.classify(0.4) == "RED"

    def test_classify_boundary_green(self) -> None:
        zone = ThresholdZone(green_above=0.7, red_below=0.5)
        assert zone.classify(0.7) == "YELLOW"

    def test_classify_boundary_red(self) -> None:
        zone = ThresholdZone(green_above=0.7, red_below=0.5)
        assert zone.classify(0.5) == "YELLOW"


class TestEvalConfigExtended:
    def test_default_judge_model_is_none(self) -> None:
        config = EvalConfig()
        assert config.judge_model is None

    def test_default_persona_path(self) -> None:
        config = EvalConfig()
        assert config.persona_path == "persona/"

    def test_judge_model_from_env(self) -> None:
        with patch.dict(os.environ, {"EVAL_JUDGE_MODEL": "openai/gpt-4o"}):
            config = EvalConfig.from_env()
        assert config.judge_model == "openai/gpt-4o"

    def test_default_thresholds_exist(self) -> None:
        assert "groundedness" in DEFAULT_THRESHOLDS
        assert "citation_accuracy" in DEFAULT_THRESHOLDS
        assert "persona_fidelity" in DEFAULT_THRESHOLDS
        assert "refusal_quality" in DEFAULT_THRESHOLDS
        assert "precision_at_k" in DEFAULT_THRESHOLDS
        assert "recall_at_k" in DEFAULT_THRESHOLDS
        assert "mrr" in DEFAULT_THRESHOLDS
