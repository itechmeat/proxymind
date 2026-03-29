from __future__ import annotations

from evals.models import EvalCase, RetrievalResult, ScorerOutput
from evals.scorers import chunk_matches_expected


class RecallAtK:
    @property
    def name(self) -> str:
        return "recall_at_k"

    def score(self, case: EvalCase, result: RetrievalResult) -> ScorerOutput:
        total = len(case.expected)
        if total == 0:
            return ScorerOutput(score=1.0, details={"found": 0, "total": 0})
        if not result.chunks:
            return ScorerOutput(score=0.0, details={"found": 0, "total": total})

        found = 0
        for expected in case.expected:
            for chunk in result.chunks:
                if chunk_matches_expected(
                    chunk.text,
                    chunk.source_id,
                    expected.source_id,
                    expected.contains,
                ):
                    found += 1
                    break

        return ScorerOutput(score=found / total, details={"found": found, "total": total})
