from __future__ import annotations

from evals.models import EvalCase, RetrievalResult, ScorerOutput
from evals.scorers import chunk_matches_expected


class MRRScorer:
    @property
    def name(self) -> str:
        return "mrr"

    def score(self, case: EvalCase, result: RetrievalResult) -> ScorerOutput:
        for chunk in sorted(result.chunks, key=lambda item: item.rank):
            for expected in case.expected:
                if chunk_matches_expected(
                    chunk.text,
                    chunk.source_id,
                    expected.source_id,
                    expected.contains,
                ):
                    return ScorerOutput(
                        score=1.0 / chunk.rank,
                        details={"first_relevant_rank": chunk.rank},
                    )

        return ScorerOutput(score=0.0, details={"first_relevant_rank": None})
