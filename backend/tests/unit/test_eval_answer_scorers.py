from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from evals.models import AnswerExpectations, EvalCase, GenerationResult, ReturnedChunk


def _make_generation_result() -> GenerationResult:
    return GenerationResult(
        answer="ProxyMind says chapter 3 covers deployment.[source:1]",
        citations=[{"source_id": str(uuid.uuid4())}],
        retrieved_chunks=[
            ReturnedChunk(
                chunk_id=uuid.uuid4(),
                source_id=uuid.uuid4(),
                score=0.9,
                text="Chapter 3 covers deployment.",
                rank=1,
            )
        ],
        rewritten_query="What does chapter 3 cover?",
        timing_ms=120.0,
        model="openai/gpt-4o",
    )


@pytest.mark.asyncio
async def test_groundedness_scorer_parses_response() -> None:
    from evals.judge import EvalJudge
    from evals.scorers.groundedness import GroundednessScorer

    judge = EvalJudge(model="test", completion_func=AsyncMock())
    judge.judge = AsyncMock(return_value="Score: 4\nReasoning: Mostly grounded")
    scorer = GroundednessScorer(judge=judge)
    case = EvalCase(id="aq-001", query="Q", answer_expectations=AnswerExpectations())

    output = await scorer.score(case, _make_generation_result())

    assert output.score == 0.75
    assert output.details["raw_score"] == 4


@pytest.mark.asyncio
async def test_groundedness_scorer_handles_empty_retrieved_chunks() -> None:
    from evals.judge import EvalJudge
    from evals.scorers.groundedness import GroundednessScorer

    judge = EvalJudge(model="test", completion_func=AsyncMock())
    judge.judge = AsyncMock(return_value="Score: 2\nReasoning: Missing support")
    scorer = GroundednessScorer(judge=judge)
    case = EvalCase(id="aq-empty", query="Q", answer_expectations=AnswerExpectations())
    result = GenerationResult(
        answer="Unsupported answer",
        citations=[],
        retrieved_chunks=[],
        rewritten_query="Q",
        timing_ms=10.0,
        model="test",
    )

    output = await scorer.score(case, result)

    assert output.score == 0.25
    prompt = judge.judge.await_args.args[0]
    assert "(no retrieved chunks)" in prompt


@pytest.mark.asyncio
async def test_citation_accuracy_scorer_includes_expected_citations() -> None:
    from evals.judge import EvalJudge
    from evals.scorers.citation_accuracy import CitationAccuracyScorer

    expected_source_id = uuid.uuid4()
    judge = EvalJudge(model="test", completion_func=AsyncMock())
    judge.judge = AsyncMock(return_value="Score: 5\nReasoning: Perfect citations")
    scorer = CitationAccuracyScorer(judge=judge)
    case = EvalCase(
        id="aq-002",
        query="Q",
        answer_expectations=AnswerExpectations(expected_citations=[expected_source_id]),
    )

    output = await scorer.score(case, _make_generation_result())

    assert output.score == 1.0
    prompt = judge.judge.await_args.args[0]
    assert str(expected_source_id) in prompt


@pytest.mark.asyncio
async def test_persona_fidelity_scorer_skips_without_tags(tmp_path: Path) -> None:
    from evals.judge import EvalJudge
    from evals.scorers.persona_fidelity import PersonaFidelityScorer

    judge = EvalJudge(model="test", completion_func=AsyncMock())
    scorer = PersonaFidelityScorer(judge=judge, persona_path=tmp_path)
    case = EvalCase(id="pf-001", query="Q", answer_expectations=AnswerExpectations())

    output = await scorer.score(case, _make_generation_result())

    assert output is None


@pytest.mark.asyncio
async def test_persona_fidelity_scorer_loads_persona_files(tmp_path: Path) -> None:
    from evals.judge import EvalJudge
    from evals.scorers.persona_fidelity import PersonaFidelityScorer

    (tmp_path / "IDENTITY.md").write_text("Identity", encoding="utf-8")
    (tmp_path / "SOUL.md").write_text("Soul", encoding="utf-8")
    (tmp_path / "BEHAVIOR.md").write_text("Behavior", encoding="utf-8")
    judge = EvalJudge(model="test", completion_func=AsyncMock())
    judge.judge = AsyncMock(return_value="Score: 5\nReasoning: Perfect persona match")
    scorer = PersonaFidelityScorer(judge=judge, persona_path=tmp_path)
    case = EvalCase(
        id="pf-002",
        query="Q",
        answer_expectations=AnswerExpectations(persona_tags=["friendly"]),
    )

    output = await scorer.score(case, _make_generation_result())

    assert output is not None
    assert output.score == 1.0
    prompt = judge.judge.await_args.args[0]
    assert "Identity" in prompt
    assert "friendly" in prompt


@pytest.mark.asyncio
async def test_refusal_quality_scorer_skips_when_not_refusal() -> None:
    from evals.judge import EvalJudge
    from evals.scorers.refusal_quality import RefusalQualityScorer

    judge = EvalJudge(model="test", completion_func=AsyncMock())
    scorer = RefusalQualityScorer(judge=judge)
    case = EvalCase(id="rq-001", query="Q", answer_expectations=AnswerExpectations())

    output = await scorer.score(case, _make_generation_result())

    assert output is None


@pytest.mark.asyncio
async def test_refusal_quality_scorer_handles_malformed_response() -> None:
    from evals.judge import EvalJudge
    from evals.scorers.refusal_quality import RefusalQualityScorer

    judge = EvalJudge(model="test", completion_func=AsyncMock())
    judge.judge = AsyncMock(return_value="Not in expected format")
    scorer = RefusalQualityScorer(judge=judge)
    case = EvalCase(
        id="rq-002",
        query="Q",
        answer_expectations=AnswerExpectations(should_refuse=True),
    )

    output = await scorer.score(case, _make_generation_result())

    assert output is not None
    assert output.score == 0.0
    assert "error" in output.details
