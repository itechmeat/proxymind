from __future__ import annotations

import json
from pathlib import Path

from evals.models import CaseResult, SuiteResult


class ReportGenerator:
    def __init__(self, *, output_dir: Path | str, worst_n: int = 3) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        self._worst_n = worst_n

    def generate(self, result: SuiteResult) -> tuple[Path, Path]:
        json_path = self.write_json(result)
        markdown_path = self.write_markdown(result)
        return json_path, markdown_path

    def write_json(self, result: SuiteResult) -> Path:
        path = self._output_dir / f"{self._stem(result)}.json"
        payload = result.model_dump(mode="json", exclude_none=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def write_markdown(self, result: SuiteResult) -> Path:
        path = self._output_dir / f"{self._stem(result)}.md"
        metric_names = sorted(result.summary.keys())
        lines = [
            f"# Eval Report: {result.suite}",
            "",
            f"**Timestamp:** {result.timestamp}",
            f"**Config:** {json.dumps(result.config, ensure_ascii=False, sort_keys=True)}",
            f"**Total cases:** {result.total_cases} | **Errors:** {result.errors}",
            "",
        ]

        if metric_names:
            lines.extend([
                "## Summary",
                "",
                "| Metric | Mean | Min | Max |",
                "|--------|------|-----|-----|",
            ])
            for metric_name in metric_names:
                metric = result.summary[metric_name]
                lines.append(
                    f"| {metric_name} | {metric.mean:.4f} | {metric.min:.4f} | {metric.max:.4f} |"
                )
            lines.append("")

        header = ["ID", "Query", "Status", *metric_names]
        separator = ["---"] * len(header)
        lines.extend([
            "## Cases",
            "",
            "| " + " | ".join(header) + " |",
            "| " + " | ".join(separator) + " |",
        ])
        for case in result.cases:
            row = [
                self._escape_pipes(case.id),
                self._escape_pipes(self._truncate(case.query)),
                self._escape_pipes(self._case_status(case)),
            ]
            for metric_name in metric_names:
                value = case.scores.get(metric_name)
                row.append(f"{value:.4f}" if value is not None else "—")
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

        successful_cases = [case for case in result.cases if case.status == "ok"]
        if successful_cases and metric_names:
            lines.extend(["## Worst Performers", ""])
            for metric_name in metric_names:
                lines.extend([f"### {metric_name}", ""])
                ranked_cases = sorted(
                    ((case.id, case.scores.get(metric_name, 0.0)) for case in successful_cases),
                    key=lambda item: item[1],
                )
                for case_id, value in ranked_cases[: self._worst_n]:
                    lines.append(f"- **{case_id}**: {value:.4f}")
                lines.append("")

            self._append_manual_review_candidates(lines, metric_names, successful_cases)

        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def _stem(self, result: SuiteResult) -> str:
        return f"{result.suite}_{result.timestamp.replace(':', '-').replace('+', 'p')}"

    def _truncate(self, query: str, limit: int = 50) -> str:
        if len(query) <= limit:
            return query
        return f"{query[:limit]}..."

    def _escape_pipes(self, value: str) -> str:
        return value.replace("|", r"\|")

    def _case_status(self, case: CaseResult) -> str:
        if case.status == "ok":
            return case.status
        return f"error: {case.error}"

    def _append_manual_review_candidates(
        self,
        lines: list[str],
        metric_names: list[str],
        successful_cases: list[CaseResult],
    ) -> None:
        answer_metrics = [
            metric_name
            for metric_name in metric_names
            if metric_name in {
                "groundedness",
                "citation_accuracy",
                "persona_fidelity",
                "refusal_quality",
            }
        ]
        cases_with_answers = [case for case in successful_cases if case.answer]
        if not answer_metrics or not cases_with_answers:
            return

        lines.extend(["## Manual Review Candidates", ""])
        for metric_name in answer_metrics:
            ranked_cases = sorted(
                [case for case in cases_with_answers if metric_name in case.scores],
                key=lambda case: case.scores[metric_name],
            )
            if not ranked_cases:
                continue
            lines.extend([f"### {metric_name}", ""])
            for case in ranked_cases[: self._worst_n]:
                lines.append(f"**{case.id}**")
                lines.append("")
                lines.append(f"- **Query:** {case.query}")
                if case.judge_scores and metric_name in case.judge_scores:
                    judge_score = case.judge_scores[metric_name]
                    if isinstance(judge_score, dict):
                        raw_score = judge_score.get("raw")
                        normalized_score = judge_score.get("normalized")
                        normalized_text = (
                            f"{normalized_score:.2f}"
                            if isinstance(normalized_score, int | float)
                            else "N/A"
                        )
                        lines.append(
                            "- **Judge score:** "
                            f"raw={raw_score if raw_score is not None else 'N/A'} "
                            f"normalized={normalized_text}"
                        )
                reasoning = None
                if case.judge_reasoning:
                    reasoning = case.judge_reasoning.get(metric_name)
                if reasoning:
                    lines.append(f"- **Judge reasoning:** {reasoning}")
                lines.append(f"- **Answer:** {case.answer}")
                details = case.details if isinstance(case.details, dict) else {}
                chunks_summary = details.get("retrieved_chunks_summary", [])
                if chunks_summary:
                    lines.append("- **Chunks summary:**")
                    for summary in chunks_summary:
                        lines.append(f"  - {summary}")
                lines.append("")
