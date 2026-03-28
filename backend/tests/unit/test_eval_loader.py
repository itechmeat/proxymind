from __future__ import annotations

import uuid
from pathlib import Path

import pytest


@pytest.fixture
def datasets_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def valid_yaml(datasets_dir: Path) -> Path:
    snapshot_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    content = f"""\
suite: test_suite
description: Test suite
snapshot_id: \"{snapshot_id}\"
cases:
  - id: t-001
    query: What is X?
    expected:
      - source_id: \"{source_id}\"
        contains: answer about X
    tags: [retrieval]
"""
    path = datasets_dir / "test.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_load_single_file(valid_yaml: Path) -> None:
    from evals.loader import load_datasets

    suites = load_datasets(valid_yaml)

    assert len(suites) == 1
    assert suites[0].suite == "test_suite"
    assert len(suites[0].cases) == 1
    assert suites[0].cases[0].tags == ["retrieval"]


def test_load_directory(datasets_dir: Path, valid_yaml: Path) -> None:
    snapshot_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    second = datasets_dir / "second.yaml"
    second.write_text(
        f'suite: second\nsnapshot_id: "{snapshot_id}"\n'
        f'cases:\n  - id: "s-001"\n    query: "Q"\n'
        f'    expected:\n      - source_id: "{source_id}"\n        contains: "A"\n',
        encoding="utf-8",
    )

    from evals.loader import load_datasets

    suites = load_datasets(datasets_dir)

    assert len(suites) == 2
    assert {suite.suite for suite in suites} == {"test_suite", "second"}


def test_load_nonexistent_path() -> None:
    from evals.loader import load_datasets

    with pytest.raises(FileNotFoundError):
        load_datasets(Path("/nonexistent/path"))


def test_load_invalid_yaml(datasets_dir: Path) -> None:
    bad = datasets_dir / "bad.yaml"
    bad.write_text("suite: bad\ncases: not_a_list\n", encoding="utf-8")

    from evals.loader import load_datasets

    with pytest.raises(ValueError, match="[Vv]alidation"):
        load_datasets(bad)


def test_load_yaml_syntax_error_uses_parsing_message(datasets_dir: Path) -> None:
    bad = datasets_dir / "broken.yaml"
    bad.write_text("suite: [\n", encoding="utf-8")

    from evals.loader import load_datasets

    with pytest.raises(ValueError, match="YAML parsing error"):
        load_datasets(bad)


def test_filter_by_tags_matching(valid_yaml: Path) -> None:
    from evals.loader import load_datasets

    suites = load_datasets(valid_yaml, tags=["retrieval"])

    assert len(suites) == 1
    assert len(suites[0].cases) == 1


def test_filter_by_tags_no_match_drops_suite(valid_yaml: Path) -> None:
    from evals.loader import load_datasets

    suites = load_datasets(valid_yaml, tags=["nonexistent"])

    assert suites == []


def test_snapshot_id_override_replaces_suite_value(valid_yaml: Path) -> None:
    from evals.loader import load_datasets

    snapshot_id = uuid.uuid4()
    suites = load_datasets(valid_yaml, snapshot_id_override=snapshot_id)

    assert suites[0].snapshot_id == snapshot_id
