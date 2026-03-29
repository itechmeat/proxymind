from __future__ import annotations

from evals.judge import EvalJudge, normalize, parse_judge_response
from evals.models import EvalCase, GenerationResult, ScorerOutput


class GroundednessScorer:
    def __init__(self, *, judge: EvalJudge) -> None:
        self._judge = judge

    @property
    def name(self) -> str:
        return "groundedness"

    async def score(self, case: EvalCase, result: GenerationResult) -> ScorerOutput:
        chunks_text = "\n\n".join(
            [
                f"Chunk {chunk.rank} (source_id={chunk.source_id}):\n{chunk.text}"
                for chunk in result.retrieved_chunks
            ]
        ) or "(no retrieved chunks)"
        prompt = "\n\n".join(
            [
                "Evaluate groundedness of the answer against the retrieved chunks.",
                "Rubric:",
                "5 = every factual claim directly supported by retrieved chunks",
                "4 = core claims supported with one minor unsupported detail",
                "3 = mixed support",
                "2 = mostly unsupported",
                "1 = fabricated or contradicts chunks",
                f"Query: {case.query}",
                f"Answer:\n{result.answer}",
                f"Retrieved chunks:\n{chunks_text}",
                (
                    "Groundedness notes: "
                    f"{case.answer_expectations.groundedness_notes}"
                    if case.answer_expectations is not None
                    and case.answer_expectations.groundedness_notes
                    else "Groundedness notes: (none)"
                ),
            ]
        )
        response = await self._judge.judge(prompt)
        try:
            raw_score, reasoning = parse_judge_response(response)
        except ValueError:
            return ScorerOutput(score=0.0, details={"error": response})
        return ScorerOutput(
            score=normalize(raw_score),
            details={"raw_score": raw_score, "reasoning": reasoning},
        )
