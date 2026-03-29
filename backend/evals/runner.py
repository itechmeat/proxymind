from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from evals.client import EvalClientError
from evals.models import CaseResult, MetricSummary, SuiteResult

if TYPE_CHECKING:
    from evals.client import EvalClient
    from evals.models import EvalSuite
    from evals.scorers import AnswerScorer, RetrievalScorer


class SuiteRunner:
    def __init__(
        self,
        *,
        client: EvalClient,
        scorers: list[RetrievalScorer],
        answer_scorers: list[AnswerScorer] | None = None,
        top_n: int,
        config_summary: dict[str, Any] | None = None,
    ) -> None:
        self._client = client
        self._scorers = scorers
        self._answer_scorers = answer_scorers or []
        self._top_n = top_n
        self._config_summary = config_summary or {}

    async def run(self, suite: EvalSuite) -> SuiteResult:
        case_results: list[CaseResult] = []
        error_count = 0

        for case in suite.cases:
            scores: dict[str, float] = {}
            details: dict[str, Any] = {}
            answer: str | None = None
            generation_timing_ms: float | None = None
            judge_scores: dict[str, dict[str, float | int]] = {}
            judge_reasoning: dict[str, str] = {}
            error_message: str | None = None

            has_retrieval = bool(case.expected)
            has_answer = case.answer_expectations is not None

            if has_retrieval:
                try:
                    retrieval_result = await self._client.retrieve(
                        case.query,
                        snapshot_id=suite.snapshot_id,
                        top_n=self._top_n,
                    )
                except EvalClientError as error:
                    error_message = str(error)
                else:
                    for scorer in self._scorers:
                        scorer_output = scorer.score(case, retrieval_result)
                        scores[scorer.name] = scorer_output.score
                        details[scorer.name] = scorer_output.details

            if has_answer and error_message is None:
                try:
                    generation_result = await self._client.generate(
                        case.query,
                        snapshot_id=suite.snapshot_id,
                    )
                except EvalClientError as error:
                    error_message = str(error)
                else:
                    answer = generation_result.answer
                    generation_timing_ms = generation_result.timing_ms
                    details["retrieved_chunks_summary"] = [
                        self._chunk_summary(chunk) for chunk in generation_result.retrieved_chunks
                    ]
                    for scorer in self._answer_scorers:
                        try:
                            scorer_output = await scorer.score(case, generation_result)
                        except Exception as error:
                            details[scorer.name] = {"error": str(error)}
                            continue
                        if scorer_output is None:
                            continue
                        scores[scorer.name] = scorer_output.score
                        details[scorer.name] = scorer_output.details
                        raw_score = scorer_output.details.get("raw_score")
                        if isinstance(raw_score, int | float):
                            judge_scores[scorer.name] = {
                                "raw": int(raw_score),
                                "normalized": scorer_output.score,
                            }
                        reasoning = scorer_output.details.get("reasoning")
                        if isinstance(reasoning, str) and reasoning:
                            judge_reasoning[scorer.name] = reasoning

            if error_message is not None:
                error_count += 1
                case_results.append(
                    CaseResult(
                        id=case.id,
                        query=case.query,
                        status="error",
                        scores=scores,
                        details=details,
                        error=error_message,
                        answer=answer,
                        generation_timing_ms=generation_timing_ms,
                        judge_scores=judge_scores or None,
                        judge_reasoning=judge_reasoning or None,
                    )
                )
                continue

            case_results.append(
                CaseResult(
                    id=case.id,
                    query=case.query,
                    status="ok",
                    scores=scores,
                    details=details,
                    answer=answer,
                    generation_timing_ms=generation_timing_ms,
                    judge_scores=judge_scores or None,
                    judge_reasoning=judge_reasoning or None,
                )
            )

        return SuiteResult(
            suite=suite.suite,
            timestamp=datetime.now(tz=UTC).isoformat(),
            config={
                **self._config_summary,
                "snapshot_id": str(suite.snapshot_id),
                "top_n": self._top_n,
            },
            summary=self._aggregate(case_results),
            total_cases=len(suite.cases),
            errors=error_count,
            cases=case_results,
        )

    def _aggregate(self, case_results: list[CaseResult]) -> dict[str, MetricSummary]:
        successful_cases = [case for case in case_results if case.status == "ok"]
        if not successful_cases:
            return {}

        metric_names = {metric_name for case in successful_cases for metric_name in case.scores}
        summary: dict[str, MetricSummary] = {}
        for metric_name in sorted(metric_names):
            values = [
                case.scores[metric_name]
                for case in successful_cases
                if metric_name in case.scores
            ]
            if not values:
                continue
            summary[metric_name] = MetricSummary(
                mean=round(statistics.mean(values), 4),
                min=round(min(values), 4),
                max=round(max(values), 4),
            )
        return summary

    def _chunk_summary(self, chunk: Any) -> str:
        text = chunk.text if isinstance(chunk.text, str) else ""
        snippet = text.strip().replace("\n", " ")
        if len(snippet) > 120:
            snippet = f"{snippet[:117]}..."
        return f"#{chunk.rank} source={chunk.source_id} score={chunk.score:.3f} {snippet}"
