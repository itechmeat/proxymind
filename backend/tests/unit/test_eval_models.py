from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError


def test_expected_chunk_valid() -> None:
    from evals.models import ExpectedChunk

    chunk = ExpectedChunk(source_id=uuid.uuid4(), contains="refund policy")

    assert chunk.contains == "refund policy"


def test_eval_case_valid() -> None:
    from evals.models import EvalCase, ExpectedChunk

    case = EvalCase(
        id="ret-001",
        query="What is the refund policy?",
        expected=[ExpectedChunk(source_id=uuid.uuid4(), contains="30-day")],
    )

    assert case.id == "ret-001"
    assert len(case.expected) == 1
    assert case.tags == []


def test_eval_case_with_tags() -> None:
    from evals.models import EvalCase, ExpectedChunk

    case = EvalCase(
        id="ret-002",
        query="How to contact support?",
        expected=[ExpectedChunk(source_id=uuid.uuid4(), contains="email")],
        tags=["retrieval", "contact"],
    )

    assert case.tags == ["retrieval", "contact"]


def test_eval_case_empty_expected_allowed() -> None:
    from evals.models import EvalCase

    case = EvalCase(id="ok", query="q", expected=[])

    assert case.expected == []


def test_eval_case_answer_expectations_default_none() -> None:
    from evals.models import EvalCase

    case = EvalCase(id="a-001", query="What is X?")

    assert case.answer_expectations is None


def test_answer_expectations_defaults() -> None:
    from evals.models import AnswerExpectations

    expectations = AnswerExpectations()

    assert expectations.should_refuse is False
    assert expectations.expected_citations == []
    assert expectations.persona_tags == []
    assert expectations.groundedness_notes == ""


def test_generation_result_model() -> None:
    from evals.models import GenerationResult, ReturnedChunk

    result = GenerationResult(
        answer="The answer is X.",
        citations=[],
        retrieved_chunks=[
            ReturnedChunk(
                chunk_id=uuid.uuid4(),
                source_id=uuid.uuid4(),
                score=0.9,
                text="chunk text",
                rank=1,
            )
        ],
        rewritten_query="What is X?",
        timing_ms=150.0,
        model="gemini/gemini-2.0-flash",
    )

    assert result.answer == "The answer is X."
    assert result.model == "gemini/gemini-2.0-flash"
    assert len(result.retrieved_chunks) == 1


def test_eval_suite_valid() -> None:
    from evals.models import EvalCase, EvalSuite, ExpectedChunk

    snapshot_id = uuid.uuid4()
    suite = EvalSuite(
        suite="retrieval_basic",
        description="Basic checks",
        snapshot_id=snapshot_id,
        cases=[
            EvalCase(
                id="ret-001",
                query="q",
                expected=[ExpectedChunk(source_id=uuid.uuid4(), contains="x")],
            )
        ],
    )

    assert suite.suite == "retrieval_basic"
    assert suite.snapshot_id == snapshot_id


def test_eval_suite_duplicate_case_ids_rejected() -> None:
    from evals.models import EvalCase, EvalSuite, ExpectedChunk

    snapshot_id = uuid.uuid4()
    chunk = ExpectedChunk(source_id=uuid.uuid4(), contains="x")

    with pytest.raises(ValidationError, match="Duplicate case id"):
        EvalSuite(
            suite="dup",
            description="d",
            snapshot_id=snapshot_id,
            cases=[
                EvalCase(id="same", query="q1", expected=[chunk]),
                EvalCase(id="same", query="q2", expected=[chunk]),
            ],
        )


def test_eval_suite_empty_cases_rejected() -> None:
    from evals.models import EvalSuite

    with pytest.raises(ValidationError):
        EvalSuite(
            suite="empty",
            description="d",
            snapshot_id=uuid.uuid4(),
            cases=[],
        )


def test_returned_chunk_model() -> None:
    from evals.models import ReturnedChunk

    chunk = ReturnedChunk(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        score=0.85,
        text="Some content here",
        rank=1,
    )

    assert chunk.rank == 1
    assert chunk.score == 0.85


def test_scorer_output_model() -> None:
    from evals.models import ScorerOutput

    output = ScorerOutput(score=0.75, details={"matched": 3, "total": 4})

    assert output.score == 0.75


def test_scorer_output_rejects_score_above_one() -> None:
    from evals.models import ScorerOutput

    with pytest.raises(ValidationError):
        ScorerOutput(score=1.5)


def test_scorer_output_rejects_negative_score() -> None:
    from evals.models import ScorerOutput

    with pytest.raises(ValidationError):
        ScorerOutput(score=-0.1)


def test_eval_config_defaults() -> None:
    from evals.config import EvalConfig

    config = EvalConfig()

    assert config.base_url == "http://localhost:8000"
    assert config.top_n == 5
    assert config.output_dir == "evals/reports"
    assert config.snapshot_id is None
    assert config.judge_model is None
    assert config.persona_path == "persona/"


def test_eval_config_snapshot_id_validated() -> None:
    from evals.config import EvalConfig

    snapshot_id = uuid.uuid4()
    config = EvalConfig(snapshot_id=snapshot_id)

    assert config.snapshot_id == snapshot_id
