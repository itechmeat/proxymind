from __future__ import annotations

from evals.judge import EvalJudge, normalize, parse_judge_response
from evals.models import EvalCase, GenerationResult, ScorerOutput


class CitationAccuracyScorer:
    def __init__(self, *, judge: EvalJudge) -> None:
        self._judge = judge

    @property
    def name(self) -> str:
        return "citation_accuracy"

    async def score(self, case: EvalCase, result: GenerationResult) -> ScorerOutput:
        expected_citations = []
        if case.answer_expectations is not None:
            expected_source_ids = case.answer_expectations.expected_citations or []
            expected_citations = [str(item) for item in expected_source_ids]
        chunks_text = "\n\n".join(
            [
                f"Chunk {chunk.rank} (source_id={chunk.source_id}):\n{chunk.text}"
                for chunk in result.retrieved_chunks
            ]
        ) or "(no retrieved chunks)"
        prompt = "\n\n".join(
            [
                "Evaluate citation accuracy for the answer.",
                "Rubric:",
                "5 = all markers correct and no key citations missing",
                "4 = mostly correct with one minor source missing",
                "3 = some correct and some wrong or missing",
                "2 = most incorrect or missing",
                "1 = no citations or all incorrect",
                f"Query: {case.query}",
                f"Answer:\n{result.answer}",
                f"Citations: {result.citations}",
                f"Expected citations: {expected_citations}",
                f"Retrieved chunks:\n{chunks_text}",
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
