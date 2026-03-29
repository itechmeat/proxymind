from __future__ import annotations

from typing import Protocol

from evals.models import EvalCase, RetrievalResult, ScorerOutput


class Scorer(Protocol):
    @property
    def name(self) -> str: ...

    def score(self, case: EvalCase, result: RetrievalResult) -> ScorerOutput: ...


def chunk_matches_expected(
    chunk_text: str,
    chunk_source_id: object,
    expected_source_id: object,
    expected_contains: str,
) -> bool:
    return (
        str(chunk_source_id) == str(expected_source_id)
        and expected_contains.lower() in chunk_text.lower()
    )


def default_scorers() -> list[Scorer]:
    from evals.scorers.mrr import MRRScorer
    from evals.scorers.precision import PrecisionAtK
    from evals.scorers.recall import RecallAtK

    return [PrecisionAtK(), RecallAtK(), MRRScorer()]
