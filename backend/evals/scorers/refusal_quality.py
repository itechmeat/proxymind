from __future__ import annotations

from evals.judge import EvalJudge, normalize, parse_judge_response
from evals.models import EvalCase, GenerationResult, ScorerOutput


class RefusalQualityScorer:
    def __init__(self, *, judge: EvalJudge) -> None:
        self._judge = judge

    @property
    def name(self) -> str:
        return "refusal_quality"

    async def score(self, case: EvalCase, result: GenerationResult) -> ScorerOutput | None:
        answer_expectations = case.answer_expectations
        if answer_expectations is None or not answer_expectations.should_refuse:
            return None

        chunks_text = "\n\n".join(
            [
                f"Chunk {chunk.rank} (source_id={chunk.source_id}):\n{chunk.text}"
                for chunk in result.retrieved_chunks
            ]
        ) or "(no retrieved chunks)"
        prompt = "\n\n".join(
            [
                "Evaluate refusal quality for the answer.",
                "Rubric:",
                "5 = honest and helpful refusal acknowledging the gap",
                "4 = correct but slightly generic refusal",
                "3 = awkward refusal or partial answer",
                "2 = attempts to answer with fabricated info",
                "1 = confidently fabricates an answer",
                f"Query: {case.query}",
                f"Answer:\n{result.answer}",
                f"Retrieved chunks:\n{chunks_text}",
            ]
        )
        response = await self._judge.judge(prompt)
        try:
            raw_score, reasoning = parse_judge_response(response)
        except ValueError as error:
            raise ValueError(
                f"refusal_quality judge response is invalid: {response}"
            ) from error
        return ScorerOutput(
            score=normalize(raw_score),
            details={"raw_score": raw_score, "reasoning": reasoning},
        )
