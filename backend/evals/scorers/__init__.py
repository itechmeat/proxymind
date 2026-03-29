from __future__ import annotations

from pathlib import Path
from typing import Protocol

from evals.judge import EvalJudge
from evals.models import EvalCase, GenerationResult, RetrievalResult, ScorerOutput


class RetrievalScorer(Protocol):
    @property
    def name(self) -> str: ...

    def score(self, case: EvalCase, result: RetrievalResult) -> ScorerOutput: ...


class Scorer(RetrievalScorer, Protocol):
    # TODO: Remove this compatibility alias after downstream imports migrate to RetrievalScorer.
    pass


class AnswerScorer(Protocol):
    @property
    def name(self) -> str: ...

    async def score(self, case: EvalCase, result: GenerationResult) -> ScorerOutput | None: ...


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


def default_scorers() -> list[RetrievalScorer]:
    from evals.scorers.mrr import MRRScorer
    from evals.scorers.precision import PrecisionAtK
    from evals.scorers.recall import RecallAtK

    return [PrecisionAtK(), RecallAtK(), MRRScorer()]


def default_answer_scorers(
    *,
    judge: EvalJudge,
    persona_path: str | Path = "persona/",
) -> list[AnswerScorer]:
    from evals.scorers.citation_accuracy import CitationAccuracyScorer
    from evals.scorers.groundedness import GroundednessScorer
    from evals.scorers.persona_fidelity import PersonaFidelityScorer
    from evals.scorers.refusal_quality import RefusalQualityScorer

    return [
        GroundednessScorer(judge=judge),
        CitationAccuracyScorer(judge=judge),
        PersonaFidelityScorer(judge=judge, persona_path=persona_path),
        RefusalQualityScorer(judge=judge),
    ]
