from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.models import CaseResult, MetricSummary, SuiteResult


@pytest.fixture
def suite_result() -> SuiteResult:
    return SuiteResult(
        suite="test_suite",
        timestamp="2026-03-28T14:30:00+00:00",
        config={"snapshot_id": "abc-123", "top_n": 5},
        summary={
            "precision_at_k": MetricSummary(mean=0.72, min=0.4, max=1.0),
            "recall_at_k": MetricSummary(mean=0.85, min=0.5, max=1.0),
            "mrr": MetricSummary(mean=0.91, min=0.33, max=1.0),
        },
        total_cases=3,
        errors=0,
        cases=[
            CaseResult(
                id="c-001",
                query="What is X?",
                status="ok",
                scores={"precision_at_k": 0.8, "recall_at_k": 1.0, "mrr": 1.0},
            ),
            CaseResult(
                id="c-002",
                query="What is Y?",
                status="ok",
                scores={"precision_at_k": 0.4, "recall_at_k": 0.5, "mrr": 0.5},
            ),
            CaseResult(
                id="c-003",
                query="What is Z?",
                status="ok",
                scores={"precision_at_k": 1.0, "recall_at_k": 1.0, "mrr": 1.0},
            ),
        ],
    )


def test_json_report(tmp_path: Path, suite_result: SuiteResult) -> None:
    from evals.report import ReportGenerator

    generator = ReportGenerator(output_dir=tmp_path)
    json_path = generator.write_json(suite_result)

    assert json_path.exists()
    assert json_path.suffix == ".json"
    assert "test_suite" in json_path.name
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert set(data.keys()) == {
        "suite",
        "timestamp",
        "config",
        "total_cases",
        "errors",
        "summary",
        "cases",
    }
    assert data["suite"] == "test_suite"
    assert data["total_cases"] == 3
    assert data["summary"]["precision_at_k"]["mean"] == 0.72
    assert len(data["cases"]) == 3


def test_markdown_report(tmp_path: Path, suite_result: SuiteResult) -> None:
    from evals.report import ReportGenerator

    generator = ReportGenerator(output_dir=tmp_path)
    markdown_path = generator.write_markdown(suite_result)

    assert markdown_path.exists()
    assert markdown_path.suffix == ".md"
    content = markdown_path.read_text(encoding="utf-8")
    assert "test_suite" in content
    assert "precision_at_k" in content
    assert "recall_at_k" in content
    assert "mrr" in content
    assert "c-001" in content
    assert "Worst Performers" in content


def test_markdown_includes_manual_review_section(tmp_path: Path) -> None:
    from evals.report import ReportGenerator

    result = SuiteResult(
        suite="answer_test",
        timestamp="2026-03-29T12:00:00+00:00",
        config={"base_url": "http://localhost:8000", "snapshot_id": "abc", "top_n": 5},
        summary={"groundedness": MetricSummary(mean=0.5, min=0.0, max=1.0)},
        total_cases=3,
        errors=0,
        cases=[
            CaseResult(
                id="a-001",
                query="Q1",
                status="ok",
                scores={"groundedness": 0.25},
                details={"retrieved_chunks_summary": ["#1 source=abc score=0.100 chunk"]},
                answer="Bad answer here",
                judge_scores={"groundedness": {"raw": 2, "normalized": 0.25}},
                judge_reasoning={"groundedness": "Mostly unsupported"},
            ),
            CaseResult(
                id="a-002",
                query="Q2",
                status="ok",
                scores={"groundedness": 1.0},
                details={"retrieved_chunks_summary": ["#1 source=abc score=0.900 chunk"]},
                answer="Good answer here",
                judge_scores={"groundedness": {"raw": 5, "normalized": 1.0}},
                judge_reasoning={"groundedness": "Perfect"},
            ),
            CaseResult(
                id="a-003",
                query="Q3",
                status="ok",
                scores={"groundedness": 0.5},
                details={"retrieved_chunks_summary": ["#1 source=abc score=0.500 chunk"]},
                answer="Medium answer",
                judge_scores={"groundedness": {"raw": 3, "normalized": 0.5}},
                judge_reasoning={"groundedness": "Mixed"},
            ),
        ],
    )

    _, md_path = ReportGenerator(output_dir=tmp_path).generate(result)
    content = md_path.read_text(encoding="utf-8")

    assert "## Manual Review Candidates" in content
    assert content.count("## Manual Review Candidates") == 1
    assert "a-001" in content
    assert "Bad answer here" in content
    assert "Mostly unsupported" in content


def test_markdown_report_escapes_pipe_characters(tmp_path: Path) -> None:
    from evals.report import ReportGenerator

    result = SuiteResult(
        suite="pipes",
        timestamp="2026-03-28T14:30:00+00:00",
        config={},
        summary={"precision_at_k": MetricSummary(mean=1.0, min=1.0, max=1.0)},
        total_cases=1,
        errors=1,
        cases=[
            CaseResult(
                id="c|001",
                query="What | is this?",
                status="error",
                error="bad | data",
            )
        ],
    )

    content = (
        ReportGenerator(output_dir=tmp_path)
        .write_markdown(result)
        .read_text(encoding="utf-8")
    )

    assert r"c\|001" in content
    assert r"What \| is this?" in content
    assert r"error: bad \| data" in content


def test_generate_both(tmp_path: Path, suite_result: SuiteResult) -> None:
    from evals.report import ReportGenerator

    generator = ReportGenerator(output_dir=tmp_path)
    json_path, markdown_path = generator.generate(suite_result)

    assert json_path.exists()
    assert markdown_path.exists()
    assert json_path.stem == markdown_path.stem


def test_report_with_errors(tmp_path: Path) -> None:
    from evals.report import ReportGenerator

    result = SuiteResult(
        suite="err",
        timestamp="2026-03-28T14:30:00+00:00",
        config={},
        summary={},
        total_cases=1,
        errors=1,
        cases=[
            CaseResult(
                id="e-001",
                query="Broken query",
                status="error",
                error="connection refused",
            )
        ],
    )
    generator = ReportGenerator(output_dir=tmp_path)
    json_path, markdown_path = generator.generate(result)

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["errors"] == 1
    assert "error" in markdown_path.read_text(encoding="utf-8").lower()
