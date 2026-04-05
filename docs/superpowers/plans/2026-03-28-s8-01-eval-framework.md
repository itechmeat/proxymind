# S8-01: Eval Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an eval framework with dataset format, suite runner, retrieval scorers, and report generation — separate from CI.

**Architecture:** Pluggable scorer pipeline with four layers: YAML dataset loader (Pydantic-validated), suite runner (HTTP client to admin eval endpoint), scorer registry (Precision@K, Recall@K, MRR), and report generator (JSON + Markdown). A new admin endpoint exposes raw retrieval results for scoring.

**Tech Stack:** Python 3.14, FastAPI, Pydantic, httpx, PyYAML, pytest, argparse

---

## File Map

| Action | Path | Responsibility |
|--------|------|---------------|
| Create | `backend/evals/__init__.py` | Package marker |
| Create | `backend/evals/config.py` | EvalConfig Pydantic model |
| Create | `backend/evals/models.py` | Dataset + result Pydantic models |
| Create | `backend/evals/loader.py` | YAML dataset loader |
| Create | `backend/evals/client.py` | Async HTTP client for eval endpoint |
| Create | `backend/evals/scorers/__init__.py` | Scorer protocol + registry |
| Create | `backend/evals/scorers/precision.py` | PrecisionAtK scorer |
| Create | `backend/evals/scorers/recall.py` | RecallAtK scorer |
| Create | `backend/evals/scorers/mrr.py` | MRR scorer |
| Create | `backend/evals/runner.py` | SuiteRunner orchestration |
| Create | `backend/evals/report.py` | JSON + Markdown report generator |
| Create | `backend/evals/run_evals.py` | CLI entry point (argparse) |
| Create | `backend/evals/datasets/retrieval_basic.yaml` | Seed dataset |
| Create | `backend/evals/reports/.gitkeep` | Placeholder for gitignored reports dir |
| Create | `backend/app/api/eval_schemas.py` | Request/response models for eval endpoint |
| Create | `backend/app/api/admin_eval.py` | POST /api/admin/eval/retrieve |
| Modify | `backend/app/main.py` | Mount admin_eval router |
| Modify | `backend/pyproject.toml` | Add pyyaml dependency |
| Modify | `.gitignore` | Add evals/reports/ pattern |
| Create | `backend/tests/unit/test_eval_models.py` | Tests for Pydantic models |
| Create | `backend/tests/unit/test_eval_loader.py` | Tests for YAML loader |
| Create | `backend/tests/unit/test_eval_scorers.py` | Tests for all three scorers |
| Create | `backend/tests/unit/test_eval_runner.py` | Tests for suite runner |
| Create | `backend/tests/unit/test_eval_report.py` | Tests for report generator |
| Create | `backend/tests/unit/test_admin_eval_api.py` | Tests for admin eval endpoint |

---

### Task 1: Add pyyaml dependency and gitignore

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `.gitignore`

- [ ] **Step 1: Add pyyaml to pyproject.toml**

In `backend/pyproject.toml`, add `pyyaml` to the `dependencies` list (alphabetical order, after `pypdf`):

```toml
  "pyyaml>=6.0.2",
```

- [ ] **Step 2: Add evals/reports/ to .gitignore**

Append to `.gitignore`:

```
backend/evals/reports/
!backend/evals/reports/.gitkeep
```

- [ ] **Step 3: Create reports directory with .gitkeep**

```bash
mkdir -p backend/evals/reports && touch backend/evals/reports/.gitkeep
```

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml .gitignore backend/evals/reports/.gitkeep
git commit -m "chore(evals): add pyyaml dependency and gitignore for reports"
```

---

### Task 2: Pydantic models for datasets, results, and config

**Files:**
- Create: `backend/evals/__init__.py`
- Create: `backend/evals/models.py`
- Create: `backend/evals/config.py`
- Create: `backend/tests/unit/test_eval_models.py`

- [ ] **Step 1: Write failing tests for dataset models**

Create `backend/tests/unit/test_eval_models.py`:

```python
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError


def test_expected_chunk_valid():
    from evals.models import ExpectedChunk

    chunk = ExpectedChunk(source_id=uuid.uuid4(), contains="refund policy")
    assert chunk.contains == "refund policy"


def test_eval_case_valid():
    from evals.models import EvalCase, ExpectedChunk

    case = EvalCase(
        id="ret-001",
        query="What is the refund policy?",
        expected=[ExpectedChunk(source_id=uuid.uuid4(), contains="30-day")],
    )
    assert case.id == "ret-001"
    assert len(case.expected) == 1
    assert case.tags == []


def test_eval_case_with_tags():
    from evals.models import EvalCase, ExpectedChunk

    case = EvalCase(
        id="ret-002",
        query="How to contact support?",
        expected=[ExpectedChunk(source_id=uuid.uuid4(), contains="email")],
        tags=["retrieval", "contact"],
    )
    assert case.tags == ["retrieval", "contact"]


def test_eval_case_empty_expected_rejected():
    from evals.models import EvalCase

    with pytest.raises(ValidationError):
        EvalCase(id="bad", query="q", expected=[])


def test_eval_suite_valid():
    from evals.models import EvalCase, EvalSuite, ExpectedChunk

    sid = uuid.uuid4()
    suite = EvalSuite(
        suite="retrieval_basic",
        description="Basic checks",
        snapshot_id=sid,
        cases=[
            EvalCase(
                id="ret-001",
                query="q",
                expected=[ExpectedChunk(source_id=uuid.uuid4(), contains="x")],
            ),
        ],
    )
    assert suite.suite == "retrieval_basic"
    assert suite.snapshot_id == sid


def test_eval_suite_duplicate_case_ids_rejected():
    from evals.models import EvalCase, EvalSuite, ExpectedChunk

    sid = uuid.uuid4()
    chunk = ExpectedChunk(source_id=uuid.uuid4(), contains="x")
    with pytest.raises(ValidationError, match="Duplicate case id"):
        EvalSuite(
            suite="dup",
            description="d",
            snapshot_id=sid,
            cases=[
                EvalCase(id="same", query="q1", expected=[chunk]),
                EvalCase(id="same", query="q2", expected=[chunk]),
            ],
        )


def test_returned_chunk_model():
    from evals.models import ReturnedChunk

    chunk = ReturnedChunk(
        chunk_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        score=0.85,
        text="Some content here",
        rank=1,
    )
    assert chunk.rank == 1
    assert chunk.score == 0.85


def test_scorer_output_model():
    from evals.models import ScorerOutput

    out = ScorerOutput(score=0.75, details={"matched": 3, "total": 4})
    assert out.score == 0.75


def test_eval_config_defaults():
    from evals.config import EvalConfig

    cfg = EvalConfig()
    assert cfg.base_url == "http://localhost:8000"
    assert cfg.top_n == 5
    assert cfg.output_dir == "evals/reports"
    assert cfg.snapshot_id is None


def test_eval_config_snapshot_id_validated():
    from evals.config import EvalConfig

    sid = uuid.uuid4()
    cfg = EvalConfig(snapshot_id=sid)
    assert cfg.snapshot_id == sid
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_eval_models.py -v"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'evals'`

- [ ] **Step 3: Create evals package and models**

Create `backend/evals/__init__.py`:

```python
```

Create `backend/evals/models.py`:

```python
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, model_validator


class ExpectedChunk(BaseModel):
    source_id: uuid.UUID
    contains: str = Field(min_length=1)


class EvalCase(BaseModel):
    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    expected: list[ExpectedChunk] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)


class EvalSuite(BaseModel):
    suite: str = Field(min_length=1)
    description: str = Field(default="")
    snapshot_id: uuid.UUID
    cases: list[EvalCase] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_case_ids(self) -> EvalSuite:
        ids = [c.id for c in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate case id")
        return self


class ReturnedChunk(BaseModel):
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    score: float
    text: str
    rank: int = Field(ge=1)


class RetrievalResult(BaseModel):
    chunks: list[ReturnedChunk]
    timing_ms: float


class ScorerOutput(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    details: dict[str, object] = Field(default_factory=dict)


class CaseResult(BaseModel):
    id: str
    query: str
    status: str  # "ok" | "error"
    scores: dict[str, float] = Field(default_factory=dict)
    details: dict[str, object] = Field(default_factory=dict)
    error: str | None = None


class MetricSummary(BaseModel):
    mean: float
    min: float
    max: float


class SuiteResult(BaseModel):
    suite: str
    timestamp: str
    config: dict[str, object]
    summary: dict[str, MetricSummary]
    total_cases: int
    errors: int
    cases: list[CaseResult]
```

Create `backend/evals/config.py`:

```python
from __future__ import annotations

import os
import uuid

from pydantic import BaseModel, Field


class EvalConfig(BaseModel):
    base_url: str = Field(default="http://localhost:8000")
    admin_key: str = Field(default="")
    top_n: int = Field(default=5, ge=1)
    output_dir: str = Field(default="evals/reports")
    snapshot_id: uuid.UUID | None = Field(default=None)
    dataset_path: str | None = Field(default=None)
    tags: list[str] = Field(default_factory=list)

    # NOTE: Eval runner uses its own env keys (PROXYMIND_ADMIN_API_KEY,
    # PROXYMIND_EVAL_BASE_URL), not the backend Settings fields.
    # The backend's ADMIN_API_KEY is a SecretStr for the server;
    # the eval runner needs the raw key value as a client.

    @classmethod
    def from_env(cls, **overrides: object) -> EvalConfig:
        defaults: dict[str, object] = {}
        env_key = os.environ.get("PROXYMIND_ADMIN_API_KEY", "")
        if env_key:
            defaults["admin_key"] = env_key
        env_url = os.environ.get("PROXYMIND_EVAL_BASE_URL", "")
        if env_url:
            defaults["base_url"] = env_url
        defaults.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**defaults)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_eval_models.py -v"
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/evals/ backend/tests/unit/test_eval_models.py
git commit -m "feat(evals): add Pydantic models for datasets, results, and config"
```

---

### Task 3: YAML dataset loader

**Files:**
- Create: `backend/evals/loader.py`
- Create: `backend/tests/unit/test_eval_loader.py`

- [ ] **Step 1: Write failing tests for loader**

Create `backend/tests/unit/test_eval_loader.py`:

```python
from __future__ import annotations

import uuid
from pathlib import Path

import pytest


@pytest.fixture()
def datasets_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def valid_yaml(datasets_dir: Path) -> Path:
    sid = str(uuid.uuid4())
    src_id = str(uuid.uuid4())
    content = f"""\
suite: test_suite
description: "Test suite"
snapshot_id: "{sid}"
cases:
  - id: "t-001"
    query: "What is X?"
    expected:
      - source_id: "{src_id}"
        contains: "answer about X"
    tags: ["retrieval"]
"""
    p = datasets_dir / "test.yaml"
    p.write_text(content)
    return p


def test_load_single_file(valid_yaml: Path):
    from evals.loader import load_datasets

    suites = load_datasets(valid_yaml)
    assert len(suites) == 1
    assert suites[0].suite == "test_suite"
    assert len(suites[0].cases) == 1
    assert suites[0].cases[0].tags == ["retrieval"]


def test_load_directory(datasets_dir: Path, valid_yaml: Path):
    sid = str(uuid.uuid4())
    src_id = str(uuid.uuid4())
    second = datasets_dir / "second.yaml"
    second.write_text(
        f'suite: second\nsnapshot_id: "{sid}"\n'
        f'cases:\n  - id: "s-001"\n    query: "Q"\n'
        f'    expected:\n      - source_id: "{src_id}"\n        contains: "A"\n'
    )
    from evals.loader import load_datasets

    suites = load_datasets(datasets_dir)
    assert len(suites) == 2
    names = {s.suite for s in suites}
    assert names == {"test_suite", "second"}


def test_load_nonexistent_path():
    from evals.loader import load_datasets

    with pytest.raises(FileNotFoundError):
        load_datasets(Path("/nonexistent/path"))


def test_load_invalid_yaml(datasets_dir: Path):
    bad = datasets_dir / "bad.yaml"
    bad.write_text("suite: bad\ncases: not_a_list\n")

    from evals.loader import load_datasets

    with pytest.raises(ValueError, match="[Vv]alidation"):
        load_datasets(bad)


def test_filter_by_tags_matching(valid_yaml: Path):
    from evals.loader import load_datasets

    suites = load_datasets(valid_yaml, tags=["retrieval"])
    assert len(suites) == 1
    assert len(suites[0].cases) == 1


def test_filter_by_tags_no_match_drops_suite(valid_yaml: Path):
    from evals.loader import load_datasets

    suites = load_datasets(valid_yaml, tags=["nonexistent"])
    assert len(suites) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_eval_loader.py -v"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'evals.loader'`

- [ ] **Step 3: Implement loader**

Create `backend/evals/loader.py`:

```python
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
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset path not found: {path}")

    files: list[Path]
    if path.is_dir():
        files = sorted(path.glob("*.yaml")) + sorted(path.glob("*.yml"))
    else:
        files = [path]

    suites: list[EvalSuite] = []
    for f in files:
        raw = yaml.safe_load(f.read_text(encoding="utf-8"))
        if raw is None:
            continue
        try:
            suite = EvalSuite.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"Validation error in {f.name}: {exc}") from exc

        if snapshot_id_override:
            suite = suite.model_copy(
                update={"snapshot_id": snapshot_id_override},
            )

        if tags:
            filtered_cases = [
                c for c in suite.cases if set(tags) & set(c.tags)
            ]
            if not filtered_cases:
                continue
            suite = suite.model_copy(update={"cases": filtered_cases})

        suites.append(suite)

    return suites
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_eval_loader.py -v"
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/evals/loader.py backend/tests/unit/test_eval_loader.py
git commit -m "feat(evals): add YAML dataset loader with tag filtering"
```

---

### Task 4: Scorer protocol and retrieval scorers

**Files:**
- Create: `backend/evals/scorers/__init__.py`
- Create: `backend/evals/scorers/precision.py`
- Create: `backend/evals/scorers/recall.py`
- Create: `backend/evals/scorers/mrr.py`
- Create: `backend/tests/unit/test_eval_scorers.py`

- [ ] **Step 1: Write failing tests for all three scorers**

Create `backend/tests/unit/test_eval_scorers.py`:

```python
from __future__ import annotations

import uuid

import pytest

from evals.models import EvalCase, ExpectedChunk, ReturnedChunk, RetrievalResult


def _make_chunk(
    source_id: uuid.UUID,
    text: str,
    rank: int,
    score: float = 0.8,
) -> ReturnedChunk:
    return ReturnedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id,
        score=score,
        text=text,
        rank=rank,
    )


def _make_result(chunks: list[ReturnedChunk]) -> RetrievalResult:
    return RetrievalResult(chunks=chunks, timing_ms=100.0)


# --- Fixtures ---

SRC_A = uuid.uuid4()
SRC_B = uuid.uuid4()
SRC_C = uuid.uuid4()


@pytest.fixture()
def case_two_expected() -> EvalCase:
    return EvalCase(
        id="t-001",
        query="What is X?",
        expected=[
            ExpectedChunk(source_id=SRC_A, contains="answer about X"),
            ExpectedChunk(source_id=SRC_B, contains="more about X"),
        ],
    )


# --- PrecisionAtK ---


class TestPrecisionAtK:
    def test_all_relevant(self, case_two_expected: EvalCase):
        from evals.scorers.precision import PrecisionAtK

        scorer = PrecisionAtK()
        result = _make_result([
            _make_chunk(SRC_A, "This is the answer about X here", 1),
            _make_chunk(SRC_B, "And more about X too", 2),
        ])
        out = scorer.score(case_two_expected, result)
        assert out.score == 1.0

    def test_half_relevant(self, case_two_expected: EvalCase):
        from evals.scorers.precision import PrecisionAtK

        scorer = PrecisionAtK()
        result = _make_result([
            _make_chunk(SRC_A, "This is the answer about X here", 1),
            _make_chunk(SRC_C, "Irrelevant content", 2),
        ])
        out = scorer.score(case_two_expected, result)
        assert out.score == 0.5

    def test_none_relevant(self, case_two_expected: EvalCase):
        from evals.scorers.precision import PrecisionAtK

        scorer = PrecisionAtK()
        result = _make_result([
            _make_chunk(SRC_C, "Irrelevant", 1),
        ])
        out = scorer.score(case_two_expected, result)
        assert out.score == 0.0

    def test_empty_result(self, case_two_expected: EvalCase):
        from evals.scorers.precision import PrecisionAtK

        scorer = PrecisionAtK()
        result = _make_result([])
        out = scorer.score(case_two_expected, result)
        assert out.score == 0.0

    def test_case_insensitive_match(self):
        from evals.scorers.precision import PrecisionAtK

        case = EvalCase(
            id="ci",
            query="q",
            expected=[ExpectedChunk(source_id=SRC_A, contains="Hello World")],
        )
        result = _make_result([
            _make_chunk(SRC_A, "this contains hello world inside", 1),
        ])
        out = PrecisionAtK().score(case, result)
        assert out.score == 1.0


# --- RecallAtK ---


class TestRecallAtK:
    def test_all_found(self, case_two_expected: EvalCase):
        from evals.scorers.recall import RecallAtK

        scorer = RecallAtK()
        result = _make_result([
            _make_chunk(SRC_A, "This is the answer about X here", 1),
            _make_chunk(SRC_B, "And more about X too", 2),
            _make_chunk(SRC_C, "Extra irrelevant", 3),
        ])
        out = scorer.score(case_two_expected, result)
        assert out.score == 1.0

    def test_partial_found(self, case_two_expected: EvalCase):
        from evals.scorers.recall import RecallAtK

        scorer = RecallAtK()
        result = _make_result([
            _make_chunk(SRC_A, "This is the answer about X here", 1),
            _make_chunk(SRC_C, "Irrelevant", 2),
        ])
        out = scorer.score(case_two_expected, result)
        assert out.score == 0.5

    def test_none_found(self, case_two_expected: EvalCase):
        from evals.scorers.recall import RecallAtK

        scorer = RecallAtK()
        result = _make_result([
            _make_chunk(SRC_C, "Irrelevant", 1),
        ])
        out = scorer.score(case_two_expected, result)
        assert out.score == 0.0

    def test_empty_result(self, case_two_expected: EvalCase):
        from evals.scorers.recall import RecallAtK

        scorer = RecallAtK()
        result = _make_result([])
        out = scorer.score(case_two_expected, result)
        assert out.score == 0.0


# --- MRR ---


class TestMRR:
    def test_first_is_relevant(self, case_two_expected: EvalCase):
        from evals.scorers.mrr import MRRScorer

        scorer = MRRScorer()
        result = _make_result([
            _make_chunk(SRC_A, "This is the answer about X here", 1),
            _make_chunk(SRC_C, "Irrelevant", 2),
        ])
        out = scorer.score(case_two_expected, result)
        assert out.score == 1.0

    def test_second_is_relevant(self, case_two_expected: EvalCase):
        from evals.scorers.mrr import MRRScorer

        scorer = MRRScorer()
        result = _make_result([
            _make_chunk(SRC_C, "Irrelevant", 1),
            _make_chunk(SRC_A, "This is the answer about X here", 2),
        ])
        out = scorer.score(case_two_expected, result)
        assert out.score == 0.5

    def test_third_is_relevant(self):
        from evals.scorers.mrr import MRRScorer

        case = EvalCase(
            id="m3",
            query="q",
            expected=[ExpectedChunk(source_id=SRC_A, contains="target")],
        )
        result = _make_result([
            _make_chunk(SRC_C, "nope", 1),
            _make_chunk(SRC_C, "nope", 2),
            _make_chunk(SRC_A, "has target here", 3),
        ])
        out = MRRScorer().score(case, result)
        assert abs(out.score - 1 / 3) < 1e-9

    def test_none_relevant(self, case_two_expected: EvalCase):
        from evals.scorers.mrr import MRRScorer

        scorer = MRRScorer()
        result = _make_result([
            _make_chunk(SRC_C, "Irrelevant", 1),
        ])
        out = scorer.score(case_two_expected, result)
        assert out.score == 0.0

    def test_empty_result(self, case_two_expected: EvalCase):
        from evals.scorers.mrr import MRRScorer

        scorer = MRRScorer()
        result = _make_result([])
        out = scorer.score(case_two_expected, result)
        assert out.score == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_eval_scorers.py -v"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'evals.scorers'`

- [ ] **Step 3: Implement scorer protocol and registry**

Create `backend/evals/scorers/__init__.py`:

```python
from __future__ import annotations

from typing import Protocol

from evals.models import EvalCase, RetrievalResult, ScorerOutput


class Scorer(Protocol):
    @property
    def name(self) -> str: ...

    def score(self, case: EvalCase, result: RetrievalResult) -> ScorerOutput: ...


def chunk_matches_expected(
    chunk_text: str,
    chunk_source_id: object,
    expected_source_id: object,
    expected_contains: str,
) -> bool:
    return (
        str(chunk_source_id) == str(expected_source_id)
        and expected_contains.lower() in chunk_text.lower()
    )


def default_scorers() -> list[Scorer]:
    from evals.scorers.mrr import MRRScorer
    from evals.scorers.precision import PrecisionAtK
    from evals.scorers.recall import RecallAtK

    return [PrecisionAtK(), RecallAtK(), MRRScorer()]
```

- [ ] **Step 4: Implement PrecisionAtK**

Create `backend/evals/scorers/precision.py`:

```python
from __future__ import annotations

from evals.models import EvalCase, RetrievalResult, ScorerOutput
from evals.scorers import chunk_matches_expected


class PrecisionAtK:
    @property
    def name(self) -> str:
        return "precision_at_k"

    def score(self, case: EvalCase, result: RetrievalResult) -> ScorerOutput:
        if not result.chunks:
            return ScorerOutput(score=0.0, details={"matched": 0, "total": 0})

        matched = 0
        for chunk in result.chunks:
            for exp in case.expected:
                if chunk_matches_expected(
                    chunk.text, chunk.source_id, exp.source_id, exp.contains,
                ):
                    matched += 1
                    break

        k = len(result.chunks)
        return ScorerOutput(
            score=matched / k,
            details={"matched": matched, "total": k},
        )
```

- [ ] **Step 5: Implement RecallAtK**

Create `backend/evals/scorers/recall.py`:

```python
from __future__ import annotations

from evals.models import EvalCase, RetrievalResult, ScorerOutput
from evals.scorers import chunk_matches_expected


class RecallAtK:
    @property
    def name(self) -> str:
        return "recall_at_k"

    def score(self, case: EvalCase, result: RetrievalResult) -> ScorerOutput:
        if not case.expected:
            return ScorerOutput(score=0.0, details={"found": 0, "total": 0})

        found = 0
        for exp in case.expected:
            for chunk in result.chunks:
                if chunk_matches_expected(
                    chunk.text, chunk.source_id, exp.source_id, exp.contains,
                ):
                    found += 1
                    break

        total = len(case.expected)
        return ScorerOutput(
            score=found / total,
            details={"found": found, "total": total},
        )
```

- [ ] **Step 6: Implement MRRScorer**

Create `backend/evals/scorers/mrr.py`:

```python
from __future__ import annotations

from evals.models import EvalCase, RetrievalResult, ScorerOutput
from evals.scorers import chunk_matches_expected


class MRRScorer:
    @property
    def name(self) -> str:
        return "mrr"

    def score(self, case: EvalCase, result: RetrievalResult) -> ScorerOutput:
        for chunk in sorted(result.chunks, key=lambda c: c.rank):
            for exp in case.expected:
                if chunk_matches_expected(
                    chunk.text, chunk.source_id, exp.source_id, exp.contains,
                ):
                    return ScorerOutput(
                        score=1.0 / chunk.rank,
                        details={"first_relevant_rank": chunk.rank},
                    )

        return ScorerOutput(score=0.0, details={"first_relevant_rank": None})
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_eval_scorers.py -v"
```

Expected: all PASS

- [ ] **Step 8: Commit**

```bash
git add backend/evals/scorers/ backend/tests/unit/test_eval_scorers.py
git commit -m "feat(evals): add scorer protocol with Precision@K, Recall@K, MRR"
```

---

### Task 5: Admin eval endpoint

**Files:**
- Create: `backend/app/api/eval_schemas.py`
- Create: `backend/app/api/admin_eval.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/unit/test_admin_eval_api.py`

- [ ] **Step 1: Write failing tests for the endpoint**

Create `backend/tests/unit/test_admin_eval_api.py`:

```python
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.admin_eval import router as eval_router
from app.api.auth import verify_admin_key
from app.services.qdrant import RetrievedChunk


@pytest.fixture()
def app() -> FastAPI:
    test_app = FastAPI()
    test_app.dependency_overrides[verify_admin_key] = lambda: None
    test_app.include_router(eval_router)
    return test_app


@pytest.fixture()
async def client(app: FastAPI):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


SRC_ID = uuid.uuid4()
CHUNK_ID = uuid.uuid4()
SNAPSHOT_ID = uuid.uuid4()


def _mock_retrieval_service() -> AsyncMock:
    svc = AsyncMock()
    svc.search.return_value = [
        RetrievedChunk(
            chunk_id=CHUNK_ID,
            source_id=SRC_ID,
            text_content="This is chunk text about refund policy",
            score=0.92,
            anchor_metadata={"anchor_page": 1},
        ),
    ]
    return svc


async def test_retrieve_success(app: FastAPI, client: AsyncClient):
    mock_svc = _mock_retrieval_service()
    app.state.retrieval_service = mock_svc

    resp = await client.post(
        "/api/admin/eval/retrieve",
        json={
            "query": "refund policy",
            "snapshot_id": str(SNAPSHOT_ID),
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["chunks"]) == 1
    assert data["chunks"][0]["source_id"] == str(SRC_ID)
    assert data["chunks"][0]["text"] == "This is chunk text about refund policy"
    assert data["chunks"][0]["rank"] == 1
    assert data["chunks"][0]["score"] == 0.92
    assert "timing_ms" in data

    mock_svc.search.assert_called_once_with(
        "refund policy",
        snapshot_id=SNAPSHOT_ID,
        top_n=5,
    )


async def test_retrieve_custom_top_n(app: FastAPI, client: AsyncClient):
    mock_svc = _mock_retrieval_service()
    app.state.retrieval_service = mock_svc

    resp = await client.post(
        "/api/admin/eval/retrieve",
        json={
            "query": "q",
            "snapshot_id": str(SNAPSHOT_ID),
            "top_n": 10,
        },
    )
    assert resp.status_code == 200
    mock_svc.search.assert_called_once_with(
        "q",
        snapshot_id=SNAPSHOT_ID,
        top_n=10,
    )


async def test_retrieve_empty_query(app: FastAPI, client: AsyncClient):
    resp = await client.post(
        "/api/admin/eval/retrieve",
        json={
            "query": "",
            "snapshot_id": str(SNAPSHOT_ID),
        },
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_admin_eval_api.py -v"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.admin_eval'`

- [ ] **Step 3: Create eval schemas**

Create `backend/app/api/eval_schemas.py`:

```python
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class EvalRetrieveRequest(BaseModel):
    query: str = Field(min_length=1)
    snapshot_id: uuid.UUID
    top_n: int = Field(default=5, ge=1, le=50)


class EvalChunkResponse(BaseModel):
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    score: float
    text: str
    rank: int


class EvalRetrieveResponse(BaseModel):
    chunks: list[EvalChunkResponse]
    timing_ms: float
```

- [ ] **Step 4: Create admin eval router**

Create `backend/app/api/admin_eval.py`:

```python
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from app.api.auth import verify_admin_key
from app.api.eval_schemas import EvalChunkResponse, EvalRetrieveRequest, EvalRetrieveResponse

router = APIRouter(
    prefix="/api/admin/eval",
    tags=["admin", "eval"],
    dependencies=[Depends(verify_admin_key)],
)


@router.post("/retrieve", response_model=EvalRetrieveResponse)
async def eval_retrieve(
    request: Request,
    body: EvalRetrieveRequest,
) -> EvalRetrieveResponse:
    retrieval_service = request.app.state.retrieval_service

    start = time.monotonic()
    chunks = await retrieval_service.search(
        body.query,
        snapshot_id=body.snapshot_id,
        top_n=body.top_n,
    )
    elapsed_ms = (time.monotonic() - start) * 1000

    return EvalRetrieveResponse(
        chunks=[
            EvalChunkResponse(
                chunk_id=chunk.chunk_id,
                source_id=chunk.source_id,
                score=chunk.score,
                text=chunk.text_content,
                rank=i + 1,
            )
            for i, chunk in enumerate(chunks)
        ],
        timing_ms=round(elapsed_ms, 1),
    )
```

- [ ] **Step 5: Mount router in main.py**

In `backend/app/main.py`, add the import and router registration. Add after the existing admin router imports:

```python
from app.api.admin_eval import router as admin_eval_router
```

Add after the existing `app.include_router(...)` calls:

```python
app.include_router(admin_eval_router)
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_admin_eval_api.py -v"
```

Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/eval_schemas.py backend/app/api/admin_eval.py backend/app/main.py backend/tests/unit/test_admin_eval_api.py
git commit -m "feat(evals): add admin eval retrieve endpoint"
```

---

### Task 6: Eval HTTP client

**Files:**
- Create: `backend/evals/client.py`
- Create: `backend/tests/unit/test_eval_client.py`

- [ ] **Step 1: Write failing tests for eval client**

Create `backend/tests/unit/test_eval_client.py`:

```python
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from evals.config import EvalConfig
from evals.models import RetrievalResult


@pytest.fixture()
def config() -> EvalConfig:
    return EvalConfig(base_url="http://localhost:8000", admin_key="test-key")


async def test_retrieve_success(config: EvalConfig):
    from evals.client import EvalClient

    snapshot_id = uuid.uuid4()
    chunk_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())

    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "chunks": [
            {
                "chunk_id": chunk_id,
                "source_id": source_id,
                "score": 0.9,
                "text": "chunk text",
                "rank": 1,
            },
        ],
        "timing_ms": 50.0,
    }
    mock_response.raise_for_status.return_value = None

    mock_http = AsyncMock()
    mock_http.post.return_value = mock_response

    client = EvalClient(config=config, http_client=mock_http)
    result = await client.retrieve("test query", snapshot_id=snapshot_id, top_n=5)

    assert isinstance(result, RetrievalResult)
    assert len(result.chunks) == 1
    assert result.chunks[0].rank == 1

    mock_http.post.assert_called_once_with(
        "http://localhost:8000/api/admin/eval/retrieve",
        json={
            "query": "test query",
            "snapshot_id": str(snapshot_id),
            "top_n": 5,
        },
        headers={"Authorization": "Bearer test-key"},
    )


async def test_retrieve_api_error(config: EvalConfig):
    from evals.client import EvalClient, EvalClientError

    mock_response = Mock()
    mock_response.status_code = 500
    mock_response.text = "Internal Server Error"
    mock_response.raise_for_status.side_effect = Exception("500 Server Error")

    mock_http = AsyncMock()
    mock_http.post.return_value = mock_response

    client = EvalClient(config=config, http_client=mock_http)
    with pytest.raises(EvalClientError):
        await client.retrieve("q", snapshot_id=uuid.uuid4(), top_n=5)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_eval_client.py -v"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'evals.client'`

- [ ] **Step 3: Implement eval client**

Create `backend/evals/client.py`:

```python
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from evals.models import RetrievalResult, ReturnedChunk

if TYPE_CHECKING:
    import httpx

    from evals.config import EvalConfig


class EvalClientError(RuntimeError):
    pass


class EvalClient:
    def __init__(self, *, config: EvalConfig, http_client: httpx.AsyncClient) -> None:
        self._config = config
        self._http = http_client

    async def retrieve(
        self,
        query: str,
        *,
        snapshot_id: uuid.UUID,
        top_n: int,
    ) -> RetrievalResult:
        url = f"{self._config.base_url}/api/admin/eval/retrieve"
        headers = {"Authorization": f"Bearer {self._config.admin_key}"}
        payload = {
            "query": query,
            "snapshot_id": str(snapshot_id),
            "top_n": top_n,
        }
        try:
            resp = await self._http.post(url, json=payload, headers=headers)
            resp.raise_for_status()
        except Exception as exc:
            raise EvalClientError(f"Eval API request failed: {exc}") from exc

        data = resp.json()
        return RetrievalResult(
            chunks=[ReturnedChunk(**c) for c in data["chunks"]],
            timing_ms=data["timing_ms"],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_eval_client.py -v"
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/evals/client.py backend/tests/unit/test_eval_client.py
git commit -m "feat(evals): add async HTTP client for eval endpoint"
```

---

### Task 7: Suite runner

**Files:**
- Create: `backend/evals/runner.py`
- Create: `backend/tests/unit/test_eval_runner.py`

- [ ] **Step 1: Write failing tests for suite runner**

Create `backend/tests/unit/test_eval_runner.py`:

```python
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from evals.models import (
    EvalCase,
    EvalSuite,
    ExpectedChunk,
    RetrievalResult,
    ReturnedChunk,
)


SRC_A = uuid.uuid4()
SNAPSHOT = uuid.uuid4()


def _make_suite() -> EvalSuite:
    return EvalSuite(
        suite="test",
        description="Test suite",
        snapshot_id=SNAPSHOT,
        cases=[
            EvalCase(
                id="c-001",
                query="What is X?",
                expected=[ExpectedChunk(source_id=SRC_A, contains="about X")],
            ),
            EvalCase(
                id="c-002",
                query="What is Y?",
                expected=[ExpectedChunk(source_id=SRC_A, contains="about Y")],
            ),
        ],
    )


def _mock_client(chunks_per_call: list[list[ReturnedChunk]]) -> AsyncMock:
    client = AsyncMock()
    client.retrieve.side_effect = [
        RetrievalResult(chunks=c, timing_ms=50.0) for c in chunks_per_call
    ]
    return client


async def test_runner_produces_suite_result():
    from evals.runner import SuiteRunner
    from evals.scorers import default_scorers

    suite = _make_suite()
    client = _mock_client([
        [ReturnedChunk(chunk_id=uuid.uuid4(), source_id=SRC_A, score=0.9, text="about X", rank=1)],
        [ReturnedChunk(chunk_id=uuid.uuid4(), source_id=SRC_A, score=0.8, text="about Y", rank=1)],
    ])

    runner = SuiteRunner(client=client, scorers=default_scorers(), top_n=5)
    result = await runner.run(suite)

    assert result.suite == "test"
    assert result.total_cases == 2
    assert result.errors == 0
    assert len(result.cases) == 2
    assert "precision_at_k" in result.summary
    assert "recall_at_k" in result.summary
    assert "mrr" in result.summary
    assert all(c.status == "ok" for c in result.cases)


async def test_runner_handles_api_error():
    from evals.client import EvalClientError
    from evals.runner import SuiteRunner
    from evals.scorers import default_scorers

    suite = _make_suite()
    client = AsyncMock()
    client.retrieve.side_effect = [
        RetrievalResult(
            chunks=[ReturnedChunk(chunk_id=uuid.uuid4(), source_id=SRC_A, score=0.9, text="about X", rank=1)],
            timing_ms=50.0,
        ),
        EvalClientError("connection refused"),
    ]

    runner = SuiteRunner(client=client, scorers=default_scorers(), top_n=5)
    result = await runner.run(suite)

    assert result.total_cases == 2
    assert result.errors == 1
    assert result.cases[0].status == "ok"
    assert result.cases[1].status == "error"
    assert "connection refused" in (result.cases[1].error or "")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_eval_runner.py -v"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'evals.runner'`

- [ ] **Step 3: Implement suite runner**

Create `backend/evals/runner.py`:

```python
from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import TYPE_CHECKING

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
    ) -> None:
        self._client = client
        self._scorers = scorers
        self._top_n = top_n

    async def run(self, suite: EvalSuite) -> SuiteResult:
        case_results: list[CaseResult] = []
        errors = 0

        for case in suite.cases:
            try:
                result = await self._client.retrieve(
                    case.query,
                    snapshot_id=suite.snapshot_id,
                    top_n=self._top_n,
                )
            except EvalClientError as exc:
                errors += 1
                case_results.append(
                    CaseResult(
                        id=case.id,
                        query=case.query,
                        status="error",
                        error=str(exc),
                    ),
                )
                continue

            scores: dict[str, float] = {}
            details: dict[str, object] = {}
            for scorer in self._scorers:
                output = scorer.score(case, result)
                scores[scorer.name] = output.score
                details[scorer.name] = output.details

            case_results.append(
                CaseResult(
                    id=case.id,
                    query=case.query,
                    status="ok",
                    scores=scores,
                    details=details,
                ),
            )

        summary = self._aggregate(case_results)

        return SuiteResult(
            suite=suite.suite,
            timestamp=datetime.now(tz=UTC).isoformat(),
            config={
                "snapshot_id": str(suite.snapshot_id),
                "top_n": self._top_n,
            },
            summary=summary,
            total_cases=len(suite.cases),
            errors=errors,
            cases=case_results,
        )

    def _aggregate(
        self,
        case_results: list[CaseResult],
    ) -> dict[str, MetricSummary]:
        ok_cases = [c for c in case_results if c.status == "ok"]
        if not ok_cases:
            return {}

        metric_names = {name for c in ok_cases for name in c.scores}
        summary: dict[str, MetricSummary] = {}

        for name in sorted(metric_names):
            values = [c.scores[name] for c in ok_cases if name in c.scores]
            if not values:
                continue
            summary[name] = MetricSummary(
                mean=round(statistics.mean(values), 4),
                min=round(min(values), 4),
                max=round(max(values), 4),
            )

        return summary
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_eval_runner.py -v"
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/evals/runner.py backend/tests/unit/test_eval_runner.py
git commit -m "feat(evals): add suite runner with error handling and aggregation"
```

---

### Task 8: Report generator

**Files:**
- Create: `backend/evals/report.py`
- Create: `backend/tests/unit/test_eval_report.py`

- [ ] **Step 1: Write failing tests for report generator**

Create `backend/tests/unit/test_eval_report.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.models import CaseResult, MetricSummary, SuiteResult


@pytest.fixture()
def suite_result() -> SuiteResult:
    return SuiteResult(
        suite="test_suite",
        timestamp="2026-03-28T14:30:00+00:00",
        config={"snapshot_id": "abc-123", "top_n": 5},
        summary={
            "precision_at_k": MetricSummary(mean=0.72, min=0.4, max=1.0),
            "recall_at_k": MetricSummary(mean=0.85, min=0.5, max=1.0),
            "mrr": MetricSummary(mean=0.91, min=0.33, max=1.0),
        },
        total_cases=3,
        errors=0,
        cases=[
            CaseResult(
                id="c-001",
                query="What is X?",
                status="ok",
                scores={"precision_at_k": 0.8, "recall_at_k": 1.0, "mrr": 1.0},
            ),
            CaseResult(
                id="c-002",
                query="What is Y?",
                status="ok",
                scores={"precision_at_k": 0.4, "recall_at_k": 0.5, "mrr": 0.5},
            ),
            CaseResult(
                id="c-003",
                query="What is Z?",
                status="ok",
                scores={"precision_at_k": 1.0, "recall_at_k": 1.0, "mrr": 1.0},
            ),
        ],
    )


def test_json_report(tmp_path: Path, suite_result: SuiteResult):
    from evals.report import ReportGenerator

    gen = ReportGenerator(output_dir=tmp_path)
    json_path = gen.write_json(suite_result)

    assert json_path.exists()
    assert json_path.suffix == ".json"
    assert "test_suite" in json_path.name

    data = json.loads(json_path.read_text())
    assert data["suite"] == "test_suite"
    assert data["total_cases"] == 3
    assert data["summary"]["precision_at_k"]["mean"] == 0.72
    assert len(data["cases"]) == 3


def test_markdown_report(tmp_path: Path, suite_result: SuiteResult):
    from evals.report import ReportGenerator

    gen = ReportGenerator(output_dir=tmp_path)
    md_path = gen.write_markdown(suite_result)

    assert md_path.exists()
    assert md_path.suffix == ".md"

    content = md_path.read_text()
    assert "test_suite" in content
    assert "precision_at_k" in content
    assert "recall_at_k" in content
    assert "mrr" in content
    assert "c-001" in content
    assert "Worst Performers" in content


def test_generate_both(tmp_path: Path, suite_result: SuiteResult):
    from evals.report import ReportGenerator

    gen = ReportGenerator(output_dir=tmp_path)
    json_path, md_path = gen.generate(suite_result)

    assert json_path.exists()
    assert md_path.exists()
    assert json_path.stem == md_path.stem


def test_report_with_errors(tmp_path: Path):
    from evals.report import ReportGenerator

    result = SuiteResult(
        suite="err",
        timestamp="2026-03-28T14:30:00+00:00",
        config={},
        summary={},
        total_cases=1,
        errors=1,
        cases=[
            CaseResult(
                id="e-001",
                query="Broken query",
                status="error",
                error="connection refused",
            ),
        ],
    )
    gen = ReportGenerator(output_dir=tmp_path)
    json_path, md_path = gen.generate(result)

    data = json.loads(json_path.read_text())
    assert data["errors"] == 1

    md = md_path.read_text()
    assert "error" in md.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_eval_report.py -v"
```

Expected: FAIL — `ModuleNotFoundError: No module named 'evals.report'`

- [ ] **Step 3: Implement report generator**

Create `backend/evals/report.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from evals.models import SuiteResult


class ReportGenerator:
    def __init__(self, *, output_dir: Path | str) -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, result: SuiteResult) -> tuple[Path, Path]:
        json_path = self.write_json(result)
        md_path = self.write_markdown(result)
        return json_path, md_path

    def _stem(self, result: SuiteResult) -> str:
        ts = result.timestamp.replace(":", "-").replace("+", "p")
        return f"{result.suite}_{ts}"

    def write_json(self, result: SuiteResult) -> Path:
        path = self._output_dir / f"{self._stem(result)}.json"
        data = json.loads(result.model_dump_json())
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def write_markdown(self, result: SuiteResult) -> Path:
        path = self._output_dir / f"{self._stem(result)}.md"
        lines: list[str] = []

        lines.append(f"# Eval Report: {result.suite}")
        lines.append("")
        lines.append(f"**Timestamp:** {result.timestamp}")
        lines.append(f"**Total cases:** {result.total_cases} | **Errors:** {result.errors}")
        lines.append("")

        if result.summary:
            lines.append("## Summary")
            lines.append("")
            lines.append("| Metric | Mean | Min | Max |")
            lines.append("|--------|------|-----|-----|")
            for name, m in sorted(result.summary.items()):
                lines.append(f"| {name} | {m.mean:.4f} | {m.min:.4f} | {m.max:.4f} |")
            lines.append("")

        lines.append("## Cases")
        lines.append("")
        lines.append("| ID | Query | Status | " + " | ".join(
            sorted(result.summary.keys())
        ) + " |")
        lines.append("|" + "---|" * (3 + len(result.summary)) + "")
        for case in result.cases:
            metric_vals = " | ".join(
                f"{case.scores.get(m, '-')}" if case.status == "ok" else "—"
                for m in sorted(result.summary.keys())
            )
            status = case.status if case.status == "ok" else f"error: {case.error}"
            query_short = case.query[:50] + "..." if len(case.query) > 50 else case.query
            lines.append(f"| {case.id} | {query_short} | {status} | {metric_vals} |")
        lines.append("")

        ok_cases = [c for c in result.cases if c.status == "ok"]
        if ok_cases and result.summary:
            lines.append("## Worst Performers")
            lines.append("")
            for metric in sorted(result.summary.keys()):
                scored = [(c.id, c.scores.get(metric, 0.0)) for c in ok_cases]
                scored.sort(key=lambda x: x[1])
                worst = scored[:3]
                lines.append(f"### {metric}")
                lines.append("")
                for cid, val in worst:
                    lines.append(f"- **{cid}**: {val:.4f}")
                lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        return path
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_eval_report.py -v"
```

Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/evals/report.py backend/tests/unit/test_eval_report.py
git commit -m "feat(evals): add JSON + Markdown report generator"
```

---

### Task 9: CLI entry point and seed dataset

**Files:**
- Create: `backend/evals/run_evals.py`
- Create: `backend/evals/datasets/retrieval_basic.yaml`

- [ ] **Step 1: Create CLI entry point**

Create `backend/evals/run_evals.py`:

```python
from __future__ import annotations

import argparse
import asyncio
import sys
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ProxyMind Eval Runner",
        prog="python -m evals.run_evals",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="API base URL (default: http://localhost:8000 or PROXYMIND_EVAL_BASE_URL env)",
    )
    parser.add_argument(
        "--admin-key",
        default=None,
        help="Admin API key (default: PROXYMIND_ADMIN_API_KEY env)",
    )
    parser.add_argument(
        "--dataset",
        default=None,
        help="Path to specific YAML file or directory (default: evals/datasets/)",
    )
    parser.add_argument(
        "--tag",
        action="append",
        dest="tags",
        default=None,
        help="Filter cases by tag (repeatable)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=None,
        help="Override retrieval top_n (default: 5)",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Report output directory (default: evals/reports/)",
    )
    parser.add_argument(
        "--snapshot-id",
        default=None,
        help="Override snapshot_id from datasets",
    )
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
    output_dir = Path(config.output_dir) if config.output_dir != "evals/reports" else DEFAULT_REPORTS

    print(f"Loading datasets from: {dataset_path}")
    suites = load_datasets(
        dataset_path,
        tags=args.tags,
        snapshot_id_override=config.snapshot_id,
    )

    if not suites:
        print("No datasets found.")
        return 1

    total_cases = sum(len(s.cases) for s in suites)
    print(f"Loaded {len(suites)} suite(s) with {total_cases} case(s)")

    scorers = default_scorers()
    reporter = ReportGenerator(output_dir=output_dir)

    async with httpx.AsyncClient(timeout=30.0) as http:
        client = EvalClient(config=config, http_client=http)
        runner = SuiteRunner(client=client, scorers=scorers, top_n=config.top_n)

        for suite in suites:
            print(f"\nRunning suite: {suite.suite} ({len(suite.cases)} cases)")
            result = await runner.run(suite)

            json_path, md_path = reporter.generate(result)
            print(f"  JSON report: {json_path}")
            print(f"  Markdown report: {md_path}")

            if result.summary:
                print("  Summary:")
                for name, m in sorted(result.summary.items()):
                    print(f"    {name}: mean={m.mean:.4f} min={m.min:.4f} max={m.max:.4f}")

            if result.errors > 0:
                print(f"  Errors: {result.errors}/{result.total_cases}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Create seed dataset**

Create `backend/evals/datasets/retrieval_basic.yaml`:

```yaml
# Seed eval dataset — replace UUIDs with real values from your knowledge base.
# Run: make evals-isolated

suite: retrieval_basic
description: "Basic retrieval quality smoke test"
snapshot_id: "00000000-0000-0000-0000-000000000000"
cases:
  - id: "ret-001"
    query: "Example query — replace with a real question from your knowledge base"
    expected:
      - source_id: "00000000-0000-0000-0000-000000000001"
        contains: "expected substring from the relevant chunk"
    tags: ["retrieval", "smoke"]
```

- [ ] **Step 3: Verify CLI parses correctly**

```bash
make evals-isolated EVAL_ARGS="--help"
```

Expected: help output with all options listed

- [ ] **Step 4: Commit**

```bash
git add backend/evals/run_evals.py backend/evals/datasets/
git commit -m "feat(evals): add CLI entry point and seed dataset"
```

---

### Task 10: Integration verification

- [ ] **Step 1: Run all eval-related tests together**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_eval_models.py tests/unit/test_eval_loader.py tests/unit/test_eval_scorers.py tests/unit/test_eval_runner.py tests/unit/test_eval_report.py tests/unit/test_eval_client.py tests/unit/test_admin_eval_api.py -v"
```

Expected: all PASS

- [ ] **Step 2: Run full test suite to check for regressions**

```bash
make backend-exec-isolated BACKEND_CMD="python -m pytest tests/ -v --timeout=60"
```

Expected: all existing tests still PASS, new eval tests PASS

- [ ] **Step 3: Run ruff lint**

```bash
make backend-exec-isolated BACKEND_CMD="python -m ruff check evals/ app/api/admin_eval.py app/api/eval_schemas.py"
```

Expected: no lint errors

- [ ] **Step 4: Commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix(evals): lint and test fixes"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** All spec sections have corresponding tasks — models (T2), loader (T3), scorers (T4), endpoint (T5), client (T6), runner (T7), report (T8), CLI (T9), integration (T10).
- [x] **No placeholders:** Every step has concrete code or commands with expected output.
- [x] **Type consistency:** `RetrievalResult`, `ReturnedChunk`, `ScorerOutput`, `EvalCase`, `EvalSuite` — names match across all tasks. Scorer `name` property matches report keys (`precision_at_k`, `recall_at_k`, `mrr`).
- [x] **Endpoint field mapping:** `RetrievedChunk.text_content` (app model) → `EvalChunkResponse.text` (API) → `ReturnedChunk.text` (eval model) — correctly mapped in `admin_eval.py`.
- [x] **Out of scope items not implemented:** No LLM-as-judge, no parallel execution, no comparison reports, no Batch API.
