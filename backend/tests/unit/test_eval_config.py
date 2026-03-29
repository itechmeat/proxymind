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
        expected = {
            "precision_at_k": (0.70, 0.50),
            "recall_at_k": (0.70, 0.50),
            "mrr": (0.60, 0.40),
            "groundedness": (0.75, 0.50),
            "citation_accuracy": (0.70, 0.50),
            "persona_fidelity": (0.70, 0.50),
            "refusal_quality": (0.80, 0.60),
        }

        for metric_name, (green_above, red_below) in expected.items():
            assert metric_name in DEFAULT_THRESHOLDS
            threshold = DEFAULT_THRESHOLDS[metric_name]
            assert threshold.green_above == green_above
            assert threshold.red_below == red_below
