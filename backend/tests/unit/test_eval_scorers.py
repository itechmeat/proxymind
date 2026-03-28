from __future__ import annotations

import uuid

import pytest

from evals.models import EvalCase, ExpectedChunk, RetrievalResult, ReturnedChunk

SRC_A = uuid.uuid4()
SRC_B = uuid.uuid4()
SRC_C = uuid.uuid4()


def _make_chunk(
    source_id: uuid.UUID,
    text: str,
    rank: int,
    score: float = 0.8,
) -> ReturnedChunk:
    return ReturnedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id,
        score=score,
        text=text,
        rank=rank,
    )


def _make_result(chunks: list[ReturnedChunk]) -> RetrievalResult:
    return RetrievalResult(chunks=chunks, timing_ms=100.0)


@pytest.fixture
def case_two_expected() -> EvalCase:
    return EvalCase(
        id="t-001",
        query="What is X?",
        expected=[
            ExpectedChunk(source_id=SRC_A, contains="answer about X"),
            ExpectedChunk(source_id=SRC_B, contains="more about X"),
        ],
    )


def test_default_scorers_returns_expected_names() -> None:
    from evals.scorers import default_scorers

    assert [scorer.name for scorer in default_scorers()] == [
        "precision_at_k",
        "recall_at_k",
        "mrr",
    ]


class TestPrecisionAtK:
    def test_all_relevant(self, case_two_expected: EvalCase) -> None:
        from evals.scorers.precision import PrecisionAtK

        scorer = PrecisionAtK()
        result = _make_result([
            _make_chunk(SRC_A, "This is the answer about X here", 1),
            _make_chunk(SRC_B, "And more about X too", 2),
        ])

        output = scorer.score(case_two_expected, result)

        assert output.score == 1.0

    def test_half_relevant(self, case_two_expected: EvalCase) -> None:
        from evals.scorers.precision import PrecisionAtK

        scorer = PrecisionAtK()
        result = _make_result([
            _make_chunk(SRC_A, "This is the answer about X here", 1),
            _make_chunk(SRC_C, "Irrelevant content", 2),
        ])

        output = scorer.score(case_two_expected, result)

        assert output.score == 0.5

    def test_none_relevant(self, case_two_expected: EvalCase) -> None:
        from evals.scorers.precision import PrecisionAtK

        output = PrecisionAtK().score(
            case_two_expected,
            _make_result([_make_chunk(SRC_C, "Irrelevant", 1)]),
        )

        assert output.score == 0.0

    def test_empty_result(self, case_two_expected: EvalCase) -> None:
        from evals.scorers.precision import PrecisionAtK

        output = PrecisionAtK().score(case_two_expected, _make_result([]))

        assert output.score == 0.0

    def test_case_insensitive_match(self) -> None:
        from evals.scorers.precision import PrecisionAtK

        case = EvalCase(
            id="ci",
            query="q",
            expected=[ExpectedChunk(source_id=SRC_A, contains="Hello World")],
        )
        output = PrecisionAtK().score(
            case,
            _make_result([_make_chunk(SRC_A, "this contains hello world inside", 1)]),
        )

        assert output.score == 1.0


class TestRecallAtK:
    def test_empty_expected_returns_vacuous_success(self) -> None:
        from evals.scorers.recall import RecallAtK

        case = EvalCase.model_construct(
            id="empty",
            query="q",
            expected=[],
            tags=[],
        )

        output = RecallAtK().score(case, _make_result([]))

        assert output.score == 1.0
        assert output.details == {"found": 0, "total": 0}

    def test_all_found(self, case_two_expected: EvalCase) -> None:
        from evals.scorers.recall import RecallAtK

        result = _make_result([
            _make_chunk(SRC_A, "This is the answer about X here", 1),
            _make_chunk(SRC_B, "And more about X too", 2),
            _make_chunk(SRC_C, "Extra irrelevant", 3),
        ])

        output = RecallAtK().score(case_two_expected, result)

        assert output.score == 1.0

    def test_partial_found(self, case_two_expected: EvalCase) -> None:
        from evals.scorers.recall import RecallAtK

        output = RecallAtK().score(
            case_two_expected,
            _make_result([
                _make_chunk(SRC_A, "This is the answer about X here", 1),
                _make_chunk(SRC_C, "Irrelevant", 2),
            ]),
        )

        assert output.score == 0.5

    def test_none_found(self, case_two_expected: EvalCase) -> None:
        from evals.scorers.recall import RecallAtK

        output = RecallAtK().score(
            case_two_expected,
            _make_result([_make_chunk(SRC_C, "Irrelevant", 1)]),
        )

        assert output.score == 0.0

    def test_empty_result(self, case_two_expected: EvalCase) -> None:
        from evals.scorers.recall import RecallAtK

        output = RecallAtK().score(case_two_expected, _make_result([]))

        assert output.score == 0.0


class TestMRR:
    def test_first_is_relevant(self, case_two_expected: EvalCase) -> None:
        from evals.scorers.mrr import MRRScorer

        output = MRRScorer().score(
            case_two_expected,
            _make_result([
                _make_chunk(SRC_A, "This is the answer about X here", 1),
                _make_chunk(SRC_C, "Irrelevant", 2),
            ]),
        )

        assert output.score == 1.0

    def test_second_is_relevant(self, case_two_expected: EvalCase) -> None:
        from evals.scorers.mrr import MRRScorer

        output = MRRScorer().score(
            case_two_expected,
            _make_result([
                _make_chunk(SRC_C, "Irrelevant", 1),
                _make_chunk(SRC_A, "This is the answer about X here", 2),
            ]),
        )

        assert output.score == 0.5

    def test_third_is_relevant(self) -> None:
        from evals.scorers.mrr import MRRScorer

        case = EvalCase(
            id="m3",
            query="q",
            expected=[ExpectedChunk(source_id=SRC_A, contains="target")],
        )
        output = MRRScorer().score(
            case,
            _make_result([
                _make_chunk(SRC_C, "nope", 1),
                _make_chunk(SRC_C, "nope", 2),
                _make_chunk(SRC_A, "has target here", 3),
            ]),
        )

        assert abs(output.score - (1 / 3)) < 1e-9

    def test_none_relevant(self, case_two_expected: EvalCase) -> None:
        from evals.scorers.mrr import MRRScorer

        output = MRRScorer().score(
            case_two_expected,
            _make_result([_make_chunk(SRC_C, "Irrelevant", 1)]),
        )

        assert output.score == 0.0

    def test_empty_result(self, case_two_expected: EvalCase) -> None:
        from evals.scorers.mrr import MRRScorer

        output = MRRScorer().score(case_two_expected, _make_result([]))

        assert output.score == 0.0
