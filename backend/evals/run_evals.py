from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid
from pathlib import Path

import httpx

from evals.client import EvalClient
from evals.config import EvalConfig
from evals.judge import EvalJudge
from evals.loader import load_datasets
from evals.models import EvalSuite
from evals.report import ReportGenerator
from evals.runner import SuiteRunner
from evals.scorers import default_answer_scorers, default_scorers

EVALS_DIR = Path(__file__).parent
DEFAULT_DATASETS = EVALS_DIR / "datasets"
DEFAULT_REPORTS = EVALS_DIR / "reports"
_PERSONA_FILES = ("IDENTITY.md", "SOUL.md", "BEHAVIOR.md")


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


def _requires_answer_scoring(suites: list[EvalSuite]) -> bool:
    return any(case.answer_expectations is not None for suite in suites for case in suite.cases)


def _has_persona_files(path: Path) -> bool:
    return all((path / name).exists() for name in _PERSONA_FILES)


def _resolve_persona_path(
    config: EvalConfig,
    *,
    persona_path_explicit: bool,
) -> Path:
    configured_path = Path(config.persona_path)
    if persona_path_explicit or _has_persona_files(configured_path):
        return configured_path

    seed_path = Path(config.seed_persona_path)
    if _has_persona_files(seed_path):
        return seed_path

    return configured_path


def _resolve_judge_model(config: EvalConfig) -> str | None:
    return config.judge_model or os.environ.get("LLM_MODEL")


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
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--persona-path", default=None)
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = EvalConfig.from_env(
        base_url=args.base_url,
        admin_key=args.admin_key,
        top_n=args.top_n,
        output_dir=args.output_dir,
        snapshot_id=args.snapshot_id,
        judge_model=args.judge_model,
        persona_path=args.persona_path,
    )

    dataset_path = Path(args.dataset) if args.dataset else DEFAULT_DATASETS
    output_dir = Path(config.output_dir)

    print(f"Loading datasets from: {dataset_path}")
    try:
        suites = load_datasets(
            dataset_path,
            tags=args.tags,
            snapshot_id_override=config.snapshot_id,
        )
    except (FileNotFoundError, ValueError) as error:
        print(f"Dataset loading failed: {error}", file=sys.stderr)
        return 1

    if not suites:
        print("No datasets found.")
        return 1

    total_cases = sum(len(suite.cases) for suite in suites)
    print(f"Loaded {len(suites)} suite(s) with {total_cases} case(s)")

    reporter = ReportGenerator(output_dir=output_dir)
    scorers = default_scorers()
    requires_answer_scoring = _requires_answer_scoring(suites)
    judge_model = _resolve_judge_model(config)
    persona_path = _resolve_persona_path(
        config,
        persona_path_explicit=args.persona_path is not None,
    )

    if requires_answer_scoring and judge_model is None:
        print(
            "Answer-quality evals require EVAL_JUDGE_MODEL or LLM_MODEL to be set.",
            file=sys.stderr,
        )
        return 1

    answer_scorers = []
    if requires_answer_scoring and judge_model is not None:
        answer_scorers = default_answer_scorers(
            judge=EvalJudge(
                model=judge_model,
                api_key=os.environ.get("LLM_API_KEY") or None,
                base_url=os.environ.get("LLM_API_BASE") or None,
            ),
            persona_path=persona_path,
        )

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        client = EvalClient(config=config, http_client=http_client)
        runner = SuiteRunner(
            client=client,
            scorers=scorers,
            answer_scorers=answer_scorers,
            top_n=config.top_n,
            config_summary={
                "base_url": config.base_url,
                "judge_model": judge_model,
                "persona_path": str(persona_path),
            },
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
