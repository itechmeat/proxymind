from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from evals.config import DEFAULT_THRESHOLDS, ThresholdZone

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ComparisonRow:
    metric: str
    baseline: float | None
    current: float | None
    delta: float | None
    zone: str


def _load_report(path: str | Path) -> dict[str, object]:
    report_path = Path(path)
    if not report_path.exists():
        raise FileNotFoundError(f"Report file not found: {report_path}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def compare_reports(
    baseline: str | Path,
    current: str | Path,
    *,
    thresholds: dict[str, ThresholdZone] | None = None,
) -> list[ComparisonRow]:
    baseline_data = _load_report(baseline)
    current_data = _load_report(current)
    threshold_map = thresholds or DEFAULT_THRESHOLDS
    baseline_summary = baseline_data.get("summary", {})
    current_summary = current_data.get("summary", {})
    if not isinstance(baseline_summary, dict) or not isinstance(current_summary, dict):
        logger.warning(
            "Eval report summary is malformed",
            extra={
                "baseline_summary_type": type(baseline_summary).__name__,
                "current_summary_type": type(current_summary).__name__,
            },
        )
        return []

    rows: list[ComparisonRow] = []
    for metric_name in sorted(set(baseline_summary.keys()) | set(current_summary.keys())):
        current_metric = current_summary.get(metric_name, {})
        baseline_metric = baseline_summary.get(metric_name)
        baseline_value = None
        if isinstance(baseline_metric, dict) and "mean" in baseline_metric:
            baseline_value = float(baseline_metric["mean"])

        current_value = None
        if isinstance(current_metric, dict) and "mean" in current_metric:
            current_value = float(current_metric["mean"])

        if current_value is None:
            zone = "MISSING"
        else:
            threshold = threshold_map.get(
                metric_name,
                ThresholdZone(green_above=0.7, red_below=0.5),
            )
            zone = threshold.classify(current_value)

        rows.append(
            ComparisonRow(
                metric=metric_name,
                baseline=baseline_value,
                current=current_value,
                delta=(current_value - baseline_value)
                if baseline_value is not None and current_value is not None
                else None,
                zone=zone,
            )
        )
    return rows


def format_comparison(rows: list[ComparisonRow]) -> str:
    header = f"{'Metric':<18} {'Baseline':>8} {'Current':>8} {'Delta':>8} {'Zone':>8}"
    lines = [header, "-" * len(header)]
    for row in rows:
        baseline = f"{row.baseline:.2f}" if row.baseline is not None else "--"
        current = f"{row.current:.2f}" if row.current is not None else "--"
        if row.delta is not None:
            delta = f"{row.delta:+.2f}"
        elif row.current is None and row.baseline is not None:
            delta = "(gone)"
        else:
            delta = "(new)"
        lines.append(
            f"{row.metric:<18} {baseline:>8} {current:>8} {delta:>8} {row.zone:>8}"
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare ProxyMind eval reports",
        prog="python -m evals.compare",
    )
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--current", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        rows = compare_reports(args.baseline, args.current)
    except FileNotFoundError as error:
        print(str(error), file=sys.stderr)
        return 1

    print(format_comparison(rows))
    return 1 if any(row.zone in {"RED", "MISSING"} for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
