from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from evals.client import EvalClientError
from evals.models import CaseResult, MetricSummary, SuiteResult

if TYPE_CHECKING:
    from evals.client import EvalClient
    from evals.models import EvalSuite
    from evals.scorers import Scorer


class SuiteRunner:
    def __init__(
        self,
        *,
        client: EvalClient,
        scorers: list[Scorer],
        top_n: int,
        config_summary: dict[str, Any] | None = None,
    ) -> None:
        self._client = client
        self._scorers = scorers
        self._top_n = top_n
        self._config_summary = config_summary or {}

    async def run(self, suite: EvalSuite) -> SuiteResult:
        case_results: list[CaseResult] = []
        error_count = 0

        for case in suite.cases:
            try:
                retrieval_result = await self._client.retrieve(
                    case.query,
                    snapshot_id=suite.snapshot_id,
                    top_n=self._top_n,
                )
            except EvalClientError as error:
                error_count += 1
                case_results.append(
                    CaseResult(
                        id=case.id,
                        query=case.query,
                        status="error",
                        error=str(error),
                    )
                )
                continue

            scores: dict[str, float] = {}
            details: dict[str, Any] = {}
            for scorer in self._scorers:
                scorer_output = scorer.score(case, retrieval_result)
                scores[scorer.name] = scorer_output.score
                details[scorer.name] = scorer_output.details

            case_results.append(
                CaseResult(
                    id=case.id,
                    query=case.query,
                    status="ok",
                    scores=scores,
                    details=details,
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
