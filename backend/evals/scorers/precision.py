from __future__ import annotations

from evals.models import EvalCase, RetrievalResult, ScorerOutput
from evals.scorers import chunk_matches_expected


class PrecisionAtK:
    @property
    def name(self) -> str:
        return "precision_at_k"

    def score(self, case: EvalCase, result: RetrievalResult) -> ScorerOutput:
        if not result.chunks:
            return ScorerOutput(score=0.0, details={"matched": 0, "total": 0})

        matched = 0
        for chunk in result.chunks:
            for expected in case.expected:
                if chunk_matches_expected(
                    chunk.text,
                    chunk.source_id,
                    expected.source_id,
                    expected.contains,
                ):
                    matched += 1
                    break

        total = len(result.chunks)
        return ScorerOutput(score=matched / total, details={"matched": matched, "total": total})
