from __future__ import annotations

import uuid
from pathlib import Path

import yaml
from pydantic import ValidationError

from evals.models import EvalSuite


def load_datasets(
    path: Path,
    *,
    tags: list[str] | None = None,
    snapshot_id_override: uuid.UUID | None = None,
) -> list[EvalSuite]:
    dataset_path = Path(path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset path not found: {dataset_path}")

    if dataset_path.is_dir():
        files = sorted(dataset_path.glob("*.yaml")) + sorted(dataset_path.glob("*.yml"))
    else:
        files = [dataset_path]

    suites: list[EvalSuite] = []
    for file_path in files:
        try:
            raw_data = yaml.safe_load(file_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            raise ValueError(f"YAML parsing error in {file_path.name}: {error}") from error

        if raw_data is None:
            continue

        try:
            suite = EvalSuite.model_validate(raw_data)
        except ValidationError as error:
            raise ValueError(f"Validation error in {file_path.name}: {error}") from error

        if snapshot_id_override is not None:
            suite = suite.model_copy(update={"snapshot_id": snapshot_id_override})

        if tags:
            filtered_cases = [case for case in suite.cases if set(case.tags) & set(tags)]
            if not filtered_cases:
                continue
            suite = suite.model_copy(update={"cases": filtered_cases})

        suites.append(suite)

    return suites
