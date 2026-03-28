from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

import httpx

from evals.client import EvalClient
from evals.config import EvalConfig
from evals.loader import load_datasets
from evals.report import ReportGenerator
from evals.runner import SuiteRunner
from evals.scorers import default_scorers

EVALS_DIR = Path(__file__).parent
DEFAULT_DATASETS = EVALS_DIR / "datasets"
DEFAULT_REPORTS = EVALS_DIR / "reports"


def _parse_top_n(raw_value: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("top-n must be an integer") from error
    if value < 1 or value > 50:
        raise argparse.ArgumentTypeError("top-n must be between 1 and 50")
    return value


def _parse_uuid(raw_value: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw_value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("snapshot-id must be a valid UUID") from error


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ProxyMind Eval Runner",
        prog="python -m evals.run_evals",
    )
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--admin-key", default=None)
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--tag", action="append", dest="tags", default=None)
    parser.add_argument("--top-n", type=_parse_top_n, default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--snapshot-id", type=_parse_uuid, default=None)
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = EvalConfig.from_env(
        base_url=args.base_url,
        admin_key=args.admin_key,
        top_n=args.top_n,
        output_dir=args.output_dir,
        snapshot_id=args.snapshot_id,
    )

    dataset_path = Path(args.dataset) if args.dataset else DEFAULT_DATASETS
    output_dir = Path(config.output_dir)

    print(f"Loading datasets from: {dataset_path}")
    suites = load_datasets(
        dataset_path,
        tags=args.tags,
        snapshot_id_override=config.snapshot_id,
    )
    if not suites:
        print("No datasets found.")
        return 1

    total_cases = sum(len(suite.cases) for suite in suites)
    print(f"Loaded {len(suites)} suite(s) with {total_cases} case(s)")

    reporter = ReportGenerator(output_dir=output_dir)
    scorers = default_scorers()
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        client = EvalClient(config=config, http_client=http_client)
        runner = SuiteRunner(
            client=client,
            scorers=scorers,
            top_n=config.top_n,
            config_summary={"base_url": config.base_url},
        )
        for suite in suites:
            print(f"\nRunning suite: {suite.suite} ({len(suite.cases)} cases)")
            result = await runner.run(suite)
            json_path, markdown_path = reporter.generate(result)
            print(f"  JSON report: {json_path}")
            print(f"  Markdown report: {markdown_path}")
            if result.summary:
                print("  Summary:")
                for name, metric in sorted(result.summary.items()):
                    print(
                        "    "
                        f"{name}: mean={metric.mean:.4f} "
                        f"min={metric.min:.4f} max={metric.max:.4f}"
                    )
            if result.errors > 0:
                print(f"  Errors: {result.errors}/{result.total_cases}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
