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
        payload = result.model_dump(mode="json")
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
