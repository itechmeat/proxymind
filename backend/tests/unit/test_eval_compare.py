from __future__ import annotations

import json
from pathlib import Path

import pytest


def _write_report(path: Path, summary: dict[str, dict[str, float]]) -> Path:
    path.write_text(
        json.dumps(
            {
                "suite": "test",
                "timestamp": "2026-03-29T00:00:00+00:00",
                "config": {},
                "summary": summary,
                "total_cases": 1,
                "errors": 0,
                "cases": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_compare_reports_handles_new_metric(tmp_path: Path) -> None:
    from evals.compare import compare_reports

    baseline = _write_report(tmp_path / "baseline.json", {"precision_at_k": {"mean": 0.72}})
    current = _write_report(
        tmp_path / "current.json",
        {"precision_at_k": {"mean": 0.78}, "groundedness": {"mean": 0.85}},
    )

    rows = compare_reports(baseline, current)

    assert [row.metric for row in rows] == ["groundedness", "precision_at_k"]
    assert rows[0].baseline is None
    assert rows[0].delta is None
    assert rows[0].zone == "GREEN"


def test_format_comparison_contains_expected_columns(tmp_path: Path) -> None:
    from evals.compare import compare_reports, format_comparison

    baseline = _write_report(tmp_path / "baseline.json", {"precision_at_k": {"mean": 0.72}})
    current = _write_report(tmp_path / "current.json", {"precision_at_k": {"mean": 0.78}})

    output = format_comparison(compare_reports(baseline, current))

    assert "Metric" in output
    assert "Baseline" in output
    assert "Current" in output
    assert "Delta" in output
    assert "+0.06" in output


def test_compare_reports_marks_removed_metric(tmp_path: Path) -> None:
    from evals.compare import compare_reports

    baseline = _write_report(
        tmp_path / "baseline.json",
        {"precision_at_k": {"mean": 0.72}, "groundedness": {"mean": 0.85}},
    )
    current = _write_report(tmp_path / "current.json", {"precision_at_k": {"mean": 0.78}})

    rows = compare_reports(baseline, current)

    groundedness_row = next(row for row in rows if row.metric == "groundedness")
    assert groundedness_row.baseline == 0.85
    assert groundedness_row.current is None
    assert groundedness_row.zone == "MISSING"


def test_main_returns_one_when_any_red(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from evals.compare import main

    baseline = _write_report(tmp_path / "baseline.json", {"recall_at_k": {"mean": 0.70}})
    current = _write_report(tmp_path / "current.json", {"recall_at_k": {"mean": 0.45}})

    exit_code = main(["--baseline", str(baseline), "--current", str(current)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "RED" in captured.out


def test_main_returns_zero_when_no_red(tmp_path: Path) -> None:
    from evals.compare import main

    baseline = _write_report(tmp_path / "baseline.json", {"precision_at_k": {"mean": 0.72}})
    current = _write_report(tmp_path / "current.json", {"precision_at_k": {"mean": 0.78}})

    exit_code = main(["--baseline", str(baseline), "--current", str(current)])

    assert exit_code == 0


def test_main_returns_one_when_metric_missing_in_current(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from evals.compare import main

    baseline = _write_report(tmp_path / "baseline.json", {"groundedness": {"mean": 0.85}})
    current = _write_report(tmp_path / "current.json", {})

    exit_code = main(["--baseline", str(baseline), "--current", str(current)])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "MISSING" in captured.out
