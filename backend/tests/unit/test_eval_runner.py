from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from evals.models import (
    AnswerExpectations,
    EvalCase,
    EvalSuite,
    GenerationResult,
    ExpectedChunk,
    RetrievalResult,
    ReturnedChunk,
    ScorerOutput,
)

SRC_A = uuid.uuid4()
SNAPSHOT_ID = uuid.uuid4()


def _make_suite() -> EvalSuite:
    return EvalSuite(
        suite="test",
        description="Test suite",
        snapshot_id=SNAPSHOT_ID,
        cases=[
            EvalCase(
                id="c-001",
                query="What is X?",
                expected=[ExpectedChunk(source_id=SRC_A, contains="about X")],
            ),
            EvalCase(
                id="c-002",
                query="What is Y?",
                expected=[ExpectedChunk(source_id=SRC_A, contains="about Y")],
            ),
        ],
    )


def _mock_client(chunks_per_call: list[list[ReturnedChunk]]) -> AsyncMock:
    client = AsyncMock()
    client.retrieve.side_effect = [
        RetrievalResult(chunks=chunks, timing_ms=50.0) for chunks in chunks_per_call
    ]
    return client


@pytest.mark.asyncio
async def test_runner_produces_suite_result() -> None:
    from evals.runner import SuiteRunner
    from evals.scorers import default_scorers

    suite = _make_suite()
    client = _mock_client(
        [
            [
                ReturnedChunk(
                    chunk_id=uuid.uuid4(),
                    source_id=SRC_A,
                    score=0.9,
                    text="about X",
                    rank=1,
                )
            ],
            [
                ReturnedChunk(
                    chunk_id=uuid.uuid4(),
                    source_id=SRC_A,
                    score=0.8,
                    text="about Y",
                    rank=1,
                )
            ],
        ]
    )

    runner = SuiteRunner(client=client, scorers=default_scorers(), top_n=5)
    result = await runner.run(suite)

    assert result.suite == "test"
    assert result.total_cases == 2
    assert result.errors == 0
    assert len(result.cases) == 2
    assert set(result.summary.keys()) == {"mrr", "precision_at_k", "recall_at_k"}
    assert all(case.status == "ok" for case in result.cases)
    assert result.summary["precision_at_k"].mean == 1.0
    assert result.summary["precision_at_k"].min == 1.0
    assert result.summary["precision_at_k"].max == 1.0
    assert result.summary["recall_at_k"].mean == 1.0
    assert result.summary["mrr"].mean == 1.0


@pytest.mark.asyncio
async def test_runner_handles_api_error() -> None:
    from evals.client import EvalClientError
    from evals.runner import SuiteRunner
    from evals.scorers import default_scorers

    suite = _make_suite()
    client = AsyncMock()
    client.retrieve.side_effect = [
        RetrievalResult(
            chunks=[
                ReturnedChunk(
                    chunk_id=uuid.uuid4(),
                    source_id=SRC_A,
                    score=0.9,
                    text="about X",
                    rank=1,
                )
            ],
            timing_ms=50.0,
        ),
        EvalClientError("connection refused"),
    ]

    runner = SuiteRunner(client=client, scorers=default_scorers(), top_n=5)
    result = await runner.run(suite)

    assert result.total_cases == 2
    assert result.errors == 1
    assert result.cases[0].status == "ok"
    assert result.cases[1].status == "error"
    assert "connection refused" in (result.cases[1].error or "")


@pytest.mark.asyncio
async def test_runner_returns_empty_summary_when_all_cases_fail() -> None:
    from evals.client import EvalClientError
    from evals.runner import SuiteRunner
    from evals.scorers import default_scorers

    suite = _make_suite()
    client = AsyncMock()
    client.retrieve.side_effect = [
        EvalClientError("first failed"),
        EvalClientError("second failed"),
    ]

    runner = SuiteRunner(client=client, scorers=default_scorers(), top_n=5)
    result = await runner.run(suite)

    assert result.total_cases == 2
    assert result.errors == 2
    assert result.summary == {}
    assert all(case.status == "error" for case in result.cases)


@pytest.mark.asyncio
async def test_runner_calls_generate_for_answer_expectations() -> None:
    from evals.runner import SuiteRunner

    suite = EvalSuite(
        suite="answer_test",
        snapshot_id=uuid.uuid4(),
        cases=[
            EvalCase(
                id="a-001",
                query="Tell me about X",
                answer_expectations=AnswerExpectations(should_refuse=False),
            ),
        ],
    )
    client = AsyncMock()
    client.generate.return_value = GenerationResult(
        answer="X is a thing.",
        citations=[],
        retrieved_chunks=[],
        rewritten_query="Tell me about X",
        timing_ms=100.0,
        model="test",
    )
    answer_scorer = AsyncMock()
    answer_scorer.name = "groundedness"
    answer_scorer.score.return_value = ScorerOutput(
        score=0.75,
        details={"raw_score": 4, "reasoning": "Mostly grounded"},
    )

    runner = SuiteRunner(client=client, scorers=[], answer_scorers=[answer_scorer], top_n=5)
    result = await runner.run(suite)

    assert result.cases[0].status == "ok"
    assert result.cases[0].answer == "X is a thing."
    assert result.cases[0].judge_scores == {"groundedness": {"raw": 4, "normalized": 0.75}}
    client.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_runner_executes_combined_retrieval_and_answer_scoring() -> None:
    from evals.runner import SuiteRunner

    suite = EvalSuite(
        suite="combined_test",
        snapshot_id=uuid.uuid4(),
        cases=[
            EvalCase(
                id="ca-001",
                query="Tell me about X with sources",
                expected=[ExpectedChunk(source_id=SRC_A, contains="about X")],
                answer_expectations=AnswerExpectations(should_refuse=False),
            ),
        ],
    )
    client = AsyncMock()
    client.retrieve.return_value = RetrievalResult(
        chunks=[
            ReturnedChunk(
                chunk_id=uuid.uuid4(),
                source_id=SRC_A,
                score=0.9,
                text="about X",
                rank=1,
            )
        ],
        timing_ms=50.0,
    )
    client.generate.return_value = GenerationResult(
        answer="X is a thing [source:1].",
        citations=[],
        retrieved_chunks=[],
        rewritten_query="Tell me about X with sources",
        timing_ms=100.0,
        model="test",
    )

    retrieval_scorer = Mock()
    retrieval_scorer.name = "precision_at_k"
    retrieval_scorer.score.return_value = ScorerOutput(score=1.0, details={})

    answer_scorer = AsyncMock()
    answer_scorer.name = "groundedness"
    answer_scorer.score.return_value = ScorerOutput(
        score=0.75,
        details={"raw_score": 4, "reasoning": "Mostly grounded"},
    )

    runner = SuiteRunner(
        client=client,
        scorers=[retrieval_scorer],
        answer_scorers=[answer_scorer],
        top_n=5,
    )
    result = await runner.run(suite)

    assert result.cases[0].scores == {"precision_at_k": 1.0, "groundedness": 0.75}
    client.retrieve.assert_awaited_once()
    client.generate.assert_awaited_once()
