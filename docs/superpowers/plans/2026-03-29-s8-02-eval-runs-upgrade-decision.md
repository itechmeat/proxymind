# S8-02: Eval Runs + Upgrade Decision — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the eval framework with answer quality scorers (LLM-as-judge), seed datasets, baseline comparison, and produce a data-backed upgrade decision document.

**Architecture:** New `/eval/generate` endpoint exposes the full chat pipeline in debug mode (JSON, no SSE). Four new LLM-as-judge scorers evaluate answer quality on a 1-5 rubric (normalized to 0-1). Runner auto-selects scorers based on dataset fields. Compare CLI diffs baselines. Decision doc records metrics and upgrade recommendations.

**Tech Stack:** Python, FastAPI, Pydantic, LiteLLM, httpx, pytest, structlog

**Design spec:** `docs/superpowers/specs/2026-03-29-s8-02-eval-runs-upgrade-decision-design.md`

---

## File Structure

### New Files

| File                                                | Responsibility                                     |
| --------------------------------------------------- | -------------------------------------------------- |
| `backend/evals/judge.py`                            | EvalJudge — LLM-as-judge wrapper over LiteLLM      |
| `backend/evals/scorers/groundedness.py`             | Groundedness scorer (LLM-as-judge)                 |
| `backend/evals/scorers/citation_accuracy.py`        | Citation accuracy scorer (LLM-as-judge)            |
| `backend/evals/scorers/persona_fidelity.py`         | Persona fidelity scorer (LLM-as-judge)             |
| `backend/evals/scorers/refusal_quality.py`          | Refusal quality scorer (LLM-as-judge)              |
| `backend/evals/compare.py`                          | Compare CLI — baseline vs current report           |
| `backend/evals/baselines/.gitkeep`                  | Baseline storage directory                         |
| `backend/evals/seed_knowledge/guide.md`             | Seed knowledge — technical guide                   |
| `backend/evals/seed_knowledge/biography.md`         | Seed knowledge — prototype biography               |
| `backend/evals/seed_knowledge/faq.md`               | Seed knowledge — FAQ                               |
| `backend/evals/seed_persona/IDENTITY.md`            | Seed persona — identity                            |
| `backend/evals/seed_persona/SOUL.md`                | Seed persona — soul/style                          |
| `backend/evals/seed_persona/BEHAVIOR.md`            | Seed persona — behavior/boundaries                 |
| `backend/evals/datasets/answer_quality.yaml`        | Answer quality eval cases                          |
| `backend/evals/datasets/persona_and_refusal.yaml`   | Persona fidelity + refusal cases                   |
| `backend/tests/unit/test_eval_judge.py`             | Tests for EvalJudge                                |
| `backend/tests/unit/test_eval_answer_scorers.py`    | Tests for answer quality scorers                   |
| `backend/tests/unit/test_eval_compare.py`           | Tests for compare CLI                              |
| `backend/tests/unit/test_eval_generate_endpoint.py` | Tests for /eval/generate endpoint                  |
| `docs/eval-decision-v1.md`                          | Decision document template (filled after eval run) |

### Modified Files

| File                                | Changes                                                         |
| ----------------------------------- | --------------------------------------------------------------- |
| `backend/evals/models.py`           | Add `AnswerExpectations`, `GenerationResult`, extend `EvalCase` |
| `backend/evals/config.py`           | Add `judge_model`, `persona_path`, `ThresholdZone`, thresholds  |
| `backend/evals/loader.py`           | Support optional `answer_expectations` in YAML                  |
| `backend/evals/client.py`           | Add `generate()` method                                         |
| `backend/evals/scorers/__init__.py` | Add `AnswerScorer` protocol, `default_answer_scorers()`         |
| `backend/evals/runner.py`           | Auto-select scorers based on case fields                        |
| `backend/evals/report.py`           | Add manual review candidates section                            |
| `backend/evals/run_evals.py`        | Add `--judge-model`, `--persona-path` args                      |
| `backend/app/api/admin_eval.py`     | Add `/eval/generate` endpoint                                   |
| `backend/app/api/eval_schemas.py`   | Add `EvalGenerateRequest`, `EvalGenerateResponse`               |

---

## Task 1: Extend Models

**Files:**

- Modify: `backend/evals/models.py`
- Test: `backend/tests/unit/test_eval_models.py`

- [ ] **Step 1: Write failing tests for new models**

In `backend/tests/unit/test_eval_models.py`, add:

```python
import uuid

from evals.models import AnswerExpectations, EvalCase, EvalSuite, ExpectedChunk, GenerationResult


class TestAnswerExpectations:
    def test_defaults(self) -> None:
        ae = AnswerExpectations()
        assert ae.should_refuse is False
        assert ae.expected_citations == []
        assert ae.persona_tags == []
        assert ae.groundedness_notes == ""

    def test_full(self) -> None:
        src = uuid.uuid4()
        ae = AnswerExpectations(
            should_refuse=True,
            expected_citations=[src],
            persona_tags=["expert", "friendly"],
            groundedness_notes="Must reference chapter 3",
        )
        assert ae.should_refuse is True
        assert ae.expected_citations == [src]
        assert ae.persona_tags == ["expert", "friendly"]


class TestEvalCaseWithAnswerExpectations:
    def test_case_without_answer_expectations(self) -> None:
        case = EvalCase(
            id="r-001",
            query="What is X?",
            expected=[ExpectedChunk(source_id=uuid.uuid4(), contains="X")],
        )
        assert case.answer_expectations is None

    def test_case_with_answer_expectations_no_expected(self) -> None:
        case = EvalCase(
            id="a-001",
            query="What is X?",
            answer_expectations=AnswerExpectations(should_refuse=False),
        )
        assert case.answer_expectations is not None
        assert case.expected == []

    def test_suite_with_mixed_cases(self) -> None:
        sid = uuid.uuid4()
        suite = EvalSuite(
            suite="mixed",
            snapshot_id=sid,
            cases=[
                EvalCase(
                    id="r-001",
                    query="Q1",
                    expected=[ExpectedChunk(source_id=uuid.uuid4(), contains="a")],
                ),
                EvalCase(
                    id="a-001",
                    query="Q2",
                    answer_expectations=AnswerExpectations(should_refuse=True),
                ),
            ],
        )
        assert len(suite.cases) == 2


class TestGenerationResult:
    def test_creation(self) -> None:
        from evals.models import ReturnedChunk

        chunk = ReturnedChunk(
            chunk_id=uuid.uuid4(),
            source_id=uuid.uuid4(),
            score=0.9,
            text="chunk text",
            rank=1,
        )
        result = GenerationResult(
            answer="The answer is X.",
            citations=[],
            retrieved_chunks=[chunk],
            rewritten_query="What is X?",
            timing_ms=150.0,
            model="gemini/gemini-2.0-flash",
        )
        assert result.answer == "The answer is X."
        assert len(result.retrieved_chunks) == 1
        assert result.model == "gemini/gemini-2.0-flash"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_models.py -v -k "AnswerExpectations or GenerationResult or mixed_cases or answer_expectations_no_expected" 2>&1 | head -30
```

Expected: FAIL — `AnswerExpectations` and `GenerationResult` not defined.

- [ ] **Step 3: Implement model changes**

In `backend/evals/models.py`, add after the `ExpectedChunk` class (line 11):

```python
class AnswerExpectations(BaseModel):
    should_refuse: bool = False
    expected_citations: list[uuid.UUID] = Field(default_factory=list)
    persona_tags: list[str] = Field(default_factory=list)
    groundedness_notes: str = ""
```

Modify `EvalCase` (line 14) — make `expected` optional and add `answer_expectations`:

```python
class EvalCase(BaseModel):
    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    expected: list[ExpectedChunk] = Field(default_factory=list)
    answer_expectations: AnswerExpectations | None = None
    tags: list[str] = Field(default_factory=list)
```

Add at the end of the file, after `SuiteResult`:

```python
class GenerationResult(BaseModel):
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_chunks: list[ReturnedChunk] = Field(default_factory=list)
    rewritten_query: str
    timing_ms: float
    model: str
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_models.py -v 2>&1 | tail -20
```

Expected: ALL PASS.

- [ ] **Step 5: Fix existing tests if broken by `expected` becoming optional**

The existing `EvalSuite` validator and retrieval scorers expect `expected` to be present. Since `expected` is now `default_factory=list`, existing YAML datasets with `expected` still work. Retrieval scorers already handle empty `expected` (RecallAtK returns 1.0 for empty). Verify:

```bash
docker compose exec api python -m pytest tests/unit/test_eval_scorers.py tests/unit/test_eval_loader.py tests/unit/test_eval_runner.py -v 2>&1 | tail -20
```

Expected: ALL PASS. If `EvalSuite.validate_unique_case_ids` or loader tests fail due to validation changes, fix them.

- [ ] **Step 6: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `feat(evals): add AnswerExpectations and GenerationResult models`
Files: `backend/evals/models.py backend/tests/unit/test_eval_models.py`

---

## Task 2: Extend Config

**Files:**

- Modify: `backend/evals/config.py`
- Test: `backend/tests/unit/test_eval_config.py` (create if doesn't exist)

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_eval_config.py`:

```python
from __future__ import annotations

import os
from unittest.mock import patch

from evals.config import EvalConfig, ThresholdZone, DEFAULT_THRESHOLDS


class TestThresholdZone:
    def test_classify_green(self) -> None:
        zone = ThresholdZone(green_above=0.7, red_below=0.5)
        assert zone.classify(0.8) == "GREEN"

    def test_classify_yellow(self) -> None:
        zone = ThresholdZone(green_above=0.7, red_below=0.5)
        assert zone.classify(0.6) == "YELLOW"

    def test_classify_red(self) -> None:
        zone = ThresholdZone(green_above=0.7, red_below=0.5)
        assert zone.classify(0.4) == "RED"

    def test_classify_boundary_green(self) -> None:
        zone = ThresholdZone(green_above=0.7, red_below=0.5)
        assert zone.classify(0.7) == "YELLOW"

    def test_classify_boundary_red(self) -> None:
        zone = ThresholdZone(green_above=0.7, red_below=0.5)
        assert zone.classify(0.5) == "YELLOW"


class TestEvalConfigExtended:
    def test_default_judge_model_is_none(self) -> None:
        config = EvalConfig()
        assert config.judge_model is None

    def test_default_persona_path(self) -> None:
        config = EvalConfig()
        assert config.persona_path == "persona/"

    def test_judge_model_from_env(self) -> None:
        with patch.dict(os.environ, {"EVAL_JUDGE_MODEL": "openai/gpt-4o"}):
            config = EvalConfig.from_env()
        assert config.judge_model == "openai/gpt-4o"

    def test_default_thresholds_exist(self) -> None:
        assert "groundedness" in DEFAULT_THRESHOLDS
        assert "citation_accuracy" in DEFAULT_THRESHOLDS
        assert "persona_fidelity" in DEFAULT_THRESHOLDS
        assert "refusal_quality" in DEFAULT_THRESHOLDS
        assert "precision_at_k" in DEFAULT_THRESHOLDS
        assert "recall_at_k" in DEFAULT_THRESHOLDS
        assert "mrr" in DEFAULT_THRESHOLDS
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_config.py -v 2>&1 | head -30
```

Expected: FAIL — `ThresholdZone`, `DEFAULT_THRESHOLDS` not defined.

- [ ] **Step 3: Implement config changes**

In `backend/evals/config.py`, add before `EvalConfig`:

```python
class ThresholdZone(BaseModel):
    green_above: float
    red_below: float

    def classify(self, score: float) -> str:
        if score > self.green_above:
            return "GREEN"
        if score < self.red_below:
            return "RED"
        return "YELLOW"


DEFAULT_THRESHOLDS: dict[str, ThresholdZone] = {
    "precision_at_k": ThresholdZone(green_above=0.70, red_below=0.50),
    "recall_at_k": ThresholdZone(green_above=0.70, red_below=0.50),
    "mrr": ThresholdZone(green_above=0.60, red_below=0.40),
    "groundedness": ThresholdZone(green_above=0.75, red_below=0.50),
    "citation_accuracy": ThresholdZone(green_above=0.70, red_below=0.50),
    "persona_fidelity": ThresholdZone(green_above=0.70, red_below=0.50),
    "refusal_quality": ThresholdZone(green_above=0.80, red_below=0.60),
}
```

Add new fields to `EvalConfig`:

```python
class EvalConfig(BaseModel):
    base_url: str = Field(default="http://localhost:8000")
    admin_key: str = Field(default="")
    top_n: int = Field(default=5, ge=1, le=50)
    output_dir: str = Field(default="evals/reports")
    snapshot_id: uuid.UUID | None = Field(default=None)
    dataset_path: str | None = Field(default=None)
    tags: list[str] = Field(default_factory=list)
    judge_model: str | None = Field(default=None)
    persona_path: str = Field(default="persona/")
```

In `from_env`, add:

```python
env_judge = os.environ.get("EVAL_JUDGE_MODEL", "")
if env_judge:
    defaults["judge_model"] = env_judge
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_config.py -v 2>&1 | tail -20
```

Expected: ALL PASS.

- [ ] **Step 5: Run all eval tests**

```bash
docker compose exec api python -m pytest tests/unit/test_eval*.py -v 2>&1 | tail -20
```

Expected: ALL PASS.

- [ ] **Step 6: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `feat(evals): add ThresholdZone, judge_model, persona_path config`
Files: `backend/evals/config.py backend/tests/unit/test_eval_config.py`

---

## Task 3: EvalJudge — LLM-as-judge wrapper

**Files:**

- Create: `backend/evals/judge.py`
- Test: `backend/tests/unit/test_eval_judge.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_eval_judge.py`:

```python
from __future__ import annotations

import re
from unittest.mock import AsyncMock, patch

import pytest

from evals.judge import EvalJudge, parse_judge_response


class TestParseJudgeResponse:
    def test_valid_response(self) -> None:
        raw = "Score: 4\nReasoning: The answer is mostly grounded."
        score, reasoning = parse_judge_response(raw)
        assert score == 4
        assert reasoning == "The answer is mostly grounded."

    def test_score_at_boundary_5(self) -> None:
        score, reasoning = parse_judge_response("Score: 5\nReasoning: Perfect.")
        assert score == 5

    def test_score_at_boundary_1(self) -> None:
        score, reasoning = parse_judge_response("Score: 1\nReasoning: Terrible.")
        assert score == 1

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Could not parse"):
            parse_judge_response("This is not a valid format")

    def test_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            parse_judge_response("Score: 7\nReasoning: Over the top.")

    def test_multiline_reasoning(self) -> None:
        raw = "Score: 3\nReasoning: Line one.\nLine two.\nLine three."
        score, reasoning = parse_judge_response(raw)
        assert score == 3
        assert "Line one." in reasoning
        assert "Line three." in reasoning


class TestEvalJudgeNormalize:
    def test_normalize_5(self) -> None:
        assert EvalJudge.normalize(5) == 1.0

    def test_normalize_1(self) -> None:
        assert EvalJudge.normalize(1) == 0.0

    def test_normalize_3(self) -> None:
        assert EvalJudge.normalize(3) == 0.5

    def test_normalize_4(self) -> None:
        assert EvalJudge.normalize(4) == 0.75


class TestEvalJudgeCall:
    @pytest.mark.asyncio
    async def test_judge_returns_parsed_response(self) -> None:
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = "Score: 4\nReasoning: Good."

        with patch("evals.judge.litellm.acompletion", return_value=mock_response):
            judge = EvalJudge(model="test-model")
            score, reasoning = await judge.judge("Test prompt")

        assert score == 4
        assert reasoning == "Good."

    @pytest.mark.asyncio
    async def test_judge_uses_configured_model(self) -> None:
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock()]
        mock_response.choices[0].message.content = "Score: 3\nReasoning: Ok."

        with patch("evals.judge.litellm.acompletion", return_value=mock_response) as mock_call:
            judge = EvalJudge(model="openai/gpt-4o")
            await judge.judge("prompt")

        mock_call.assert_called_once()
        assert mock_call.call_args.kwargs["model"] == "openai/gpt-4o"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_judge.py -v 2>&1 | head -20
```

Expected: FAIL — `evals.judge` not found.

- [ ] **Step 3: Implement EvalJudge**

Create `backend/evals/judge.py`:

```python
from __future__ import annotations

import re

import litellm


def parse_judge_response(raw: str) -> tuple[int, str]:
    """Parse 'Score: N\\nReasoning: ...' format from judge response."""
    match = re.match(r"Score:\s*(\d+)\s*\nReasoning:\s*(.*)", raw, re.DOTALL)
    if not match:
        raise ValueError(f"Could not parse judge response: {raw[:200]}")
    score = int(match.group(1))
    if score < 1 or score > 5:
        raise ValueError(f"Score {score} out of range [1, 5]")
    reasoning = match.group(2).strip()
    return score, reasoning


class EvalJudge:
    def __init__(self, *, model: str) -> None:
        self._model = model

    @staticmethod
    def normalize(raw_score: int) -> float:
        """Normalize 1-5 score to 0.0-1.0."""
        return (raw_score - 1) / 4

    async def judge(self, prompt: str) -> tuple[int, str]:
        """Call LLM-as-judge and return (raw_score, reasoning)."""
        response = await litellm.acompletion(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=512,
        )
        raw = response.choices[0].message.content
        return parse_judge_response(raw)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_judge.py -v 2>&1 | tail -20
```

Expected: ALL PASS.

- [ ] **Step 5: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `feat(evals): add EvalJudge LLM-as-judge wrapper`
Files: `backend/evals/judge.py backend/tests/unit/test_eval_judge.py`

---

## Task 4: Groundedness Scorer

**Files:**

- Create: `backend/evals/scorers/groundedness.py`
- Test: `backend/tests/unit/test_eval_answer_scorers.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/unit/test_eval_answer_scorers.py`:

```python
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from evals.models import (
    AnswerExpectations,
    EvalCase,
    GenerationResult,
    ReturnedChunk,
    ScorerOutput,
)


def _make_generation(
    answer: str,
    chunks: list[ReturnedChunk] | None = None,
    citations: list[dict] | None = None,
) -> GenerationResult:
    return GenerationResult(
        answer=answer,
        citations=citations or [],
        retrieved_chunks=chunks or [],
        rewritten_query="test query",
        timing_ms=100.0,
        model="test-model",
    )


def _make_chunk(source_id: uuid.UUID, text: str, rank: int = 1) -> ReturnedChunk:
    return ReturnedChunk(
        chunk_id=uuid.uuid4(),
        source_id=source_id,
        score=0.9,
        text=text,
        rank=rank,
    )


SRC_A = uuid.uuid4()
SRC_B = uuid.uuid4()


class TestGroundednessScorer:
    @pytest.mark.asyncio
    async def test_score_returns_normalized_value(self) -> None:
        from evals.scorers.groundedness import GroundednessScorer

        case = EvalCase(
            id="g-001",
            query="What is X?",
            answer_expectations=AnswerExpectations(groundedness_notes="Must cite sources"),
        )
        gen = _make_generation(
            answer="X is a thing [source:1].",
            chunks=[_make_chunk(SRC_A, "X is defined as a thing")],
        )

        with patch("evals.scorers.groundedness.EvalJudge") as MockJudge:
            mock_instance = AsyncMock()
            mock_instance.judge.return_value = (4, "Mostly grounded")
            MockJudge.return_value = mock_instance

            scorer = GroundednessScorer(judge_model="test-model")
            output = await scorer.score(case, gen)

        assert output.score == 0.75  # (4 - 1) / 4
        assert output.details["raw_score"] == 4
        assert output.details["reasoning"] == "Mostly grounded"

    @pytest.mark.asyncio
    async def test_prompt_includes_chunks_and_answer(self) -> None:
        from evals.scorers.groundedness import GroundednessScorer

        case = EvalCase(
            id="g-002",
            query="Tell me about Y",
            answer_expectations=AnswerExpectations(),
        )
        gen = _make_generation(
            answer="Y is great.",
            chunks=[_make_chunk(SRC_A, "Y is a concept")],
        )

        with patch("evals.scorers.groundedness.EvalJudge") as MockJudge:
            mock_instance = AsyncMock()
            mock_instance.judge.return_value = (3, "Mixed")
            MockJudge.return_value = mock_instance

            scorer = GroundednessScorer(judge_model="test-model")
            await scorer.score(case, gen)

            prompt = mock_instance.judge.call_args[0][0]
            assert "Y is great." in prompt
            assert "Y is a concept" in prompt

    @pytest.mark.asyncio
    async def test_judge_error_returns_error_output(self) -> None:
        from evals.scorers.groundedness import GroundednessScorer

        case = EvalCase(id="g-003", query="Q", answer_expectations=AnswerExpectations())
        gen = _make_generation(answer="A")

        with patch("evals.scorers.groundedness.EvalJudge") as MockJudge:
            mock_instance = AsyncMock()
            mock_instance.judge.side_effect = ValueError("Could not parse")
            MockJudge.return_value = mock_instance

            scorer = GroundednessScorer(judge_model="test-model")
            output = await scorer.score(case, gen)

        assert output.score == 0.0
        assert "error" in output.details
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_answer_scorers.py::TestGroundednessScorer -v 2>&1 | head -20
```

Expected: FAIL — `evals.scorers.groundedness` not found.

- [ ] **Step 3: Implement groundedness scorer**

Create `backend/evals/scorers/groundedness.py`:

```python
from __future__ import annotations

from evals.judge import EvalJudge
from evals.models import EvalCase, GenerationResult, ScorerOutput

GROUNDEDNESS_RUBRIC = """You are evaluating whether an AI assistant's answer is grounded in the retrieved knowledge chunks.

## Retrieved Chunks
{chunks}

## Assistant's Answer
{answer}

## Scoring Rubric (1-5)
5 = Every factual claim is directly supported by retrieved chunks
4 = Core claims supported, one minor unsupported detail
3 = Mixed — some claims supported, some not traceable to chunks
2 = Mostly unsupported, only fragments grounded
1 = Fabricated or contradicts retrieved chunks

For each factual claim in the answer, determine whether it can be traced to a specific retrieved chunk. Ignore style/formatting — focus only on factual content.

Respond in exactly this format:
Score: <1-5>
Reasoning: <brief explanation>"""


class GroundednessScorer:
    def __init__(self, *, judge_model: str) -> None:
        self._judge = EvalJudge(model=judge_model)

    @property
    def name(self) -> str:
        return "groundedness"

    async def score(self, case: EvalCase, result: GenerationResult) -> ScorerOutput:
        chunks_text = "\n\n".join(
            f"[Chunk {i + 1}] (source_id: {chunk.source_id})\n{chunk.text}"
            for i, chunk in enumerate(result.retrieved_chunks)
        )
        if not chunks_text:
            chunks_text = "(no chunks retrieved)"

        prompt = GROUNDEDNESS_RUBRIC.format(
            chunks=chunks_text,
            answer=result.answer,
        )

        try:
            raw_score, reasoning = await self._judge.judge(prompt)
            return ScorerOutput(
                score=EvalJudge.normalize(raw_score),
                details={"raw_score": raw_score, "reasoning": reasoning},
            )
        except (ValueError, Exception) as error:
            return ScorerOutput(
                score=0.0,
                details={"error": str(error)},
            )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_answer_scorers.py::TestGroundednessScorer -v 2>&1 | tail -15
```

Expected: ALL PASS.

- [ ] **Step 5: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `feat(evals): add groundedness LLM-as-judge scorer`
Files: `backend/evals/scorers/groundedness.py backend/tests/unit/test_eval_answer_scorers.py`

---

## Task 5: Citation Accuracy Scorer

**Files:**

- Create: `backend/evals/scorers/citation_accuracy.py`
- Modify: `backend/tests/unit/test_eval_answer_scorers.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/unit/test_eval_answer_scorers.py`:

```python
class TestCitationAccuracyScorer:
    @pytest.mark.asyncio
    async def test_score_returns_normalized_value(self) -> None:
        from evals.scorers.citation_accuracy import CitationAccuracyScorer

        case = EvalCase(
            id="c-001",
            query="What is X?",
            answer_expectations=AnswerExpectations(expected_citations=[SRC_A]),
        )
        gen = _make_generation(
            answer="X is a thing [source:1].",
            chunks=[_make_chunk(SRC_A, "X is defined as a thing")],
            citations=[{"index": 1, "source_id": str(SRC_A), "source_title": "Guide"}],
        )

        with patch("evals.scorers.citation_accuracy.EvalJudge") as MockJudge:
            mock_instance = AsyncMock()
            mock_instance.judge.return_value = (5, "All correct")
            MockJudge.return_value = mock_instance

            scorer = CitationAccuracyScorer(judge_model="test-model")
            output = await scorer.score(case, gen)

        assert output.score == 1.0
        assert output.details["raw_score"] == 5

    @pytest.mark.asyncio
    async def test_prompt_includes_expected_citations(self) -> None:
        from evals.scorers.citation_accuracy import CitationAccuracyScorer

        case = EvalCase(
            id="c-002",
            query="Q",
            answer_expectations=AnswerExpectations(expected_citations=[SRC_A, SRC_B]),
        )
        gen = _make_generation(answer="A [source:1].", citations=[])

        with patch("evals.scorers.citation_accuracy.EvalJudge") as MockJudge:
            mock_instance = AsyncMock()
            mock_instance.judge.return_value = (2, "Missing")
            MockJudge.return_value = mock_instance

            scorer = CitationAccuracyScorer(judge_model="test-model")
            await scorer.score(case, gen)

            prompt = mock_instance.judge.call_args[0][0]
            assert str(SRC_A) in prompt
            assert str(SRC_B) in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_answer_scorers.py::TestCitationAccuracyScorer -v 2>&1 | head -15
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement citation accuracy scorer**

Create `backend/evals/scorers/citation_accuracy.py`:

```python
from __future__ import annotations

import json

from evals.judge import EvalJudge
from evals.models import EvalCase, GenerationResult, ScorerOutput

CITATION_ACCURACY_RUBRIC = """You are evaluating the citation accuracy of an AI assistant's answer.

## Assistant's Answer
{answer}

## Citations Provided
{citations}

## Retrieved Chunks
{chunks}

## Expected Source IDs
{expected_citations}

## Scoring Rubric (1-5)
5 = All [source:N] markers map to correct, relevant sources; no missing citations for key claims
4 = Citations correct, one minor source missing
3 = Some citations correct, some point to wrong sources or are missing
2 = Most citations incorrect or missing
1 = No citations or all incorrect

Verify each citation marker points to the source that actually contains the referenced information. Check whether expected sources appear in citations.

Respond in exactly this format:
Score: <1-5>
Reasoning: <brief explanation>"""


class CitationAccuracyScorer:
    def __init__(self, *, judge_model: str) -> None:
        self._judge = EvalJudge(model=judge_model)

    @property
    def name(self) -> str:
        return "citation_accuracy"

    async def score(self, case: EvalCase, result: GenerationResult) -> ScorerOutput:
        chunks_text = "\n\n".join(
            f"[Chunk {i + 1}] (source_id: {chunk.source_id})\n{chunk.text}"
            for i, chunk in enumerate(result.retrieved_chunks)
        )
        if not chunks_text:
            chunks_text = "(no chunks retrieved)"

        citations_text = json.dumps(result.citations, indent=2, default=str) if result.citations else "(no citations)"

        expected = []
        if case.answer_expectations and case.answer_expectations.expected_citations:
            expected = [str(cid) for cid in case.answer_expectations.expected_citations]
        expected_text = ", ".join(expected) if expected else "(none specified)"

        prompt = CITATION_ACCURACY_RUBRIC.format(
            answer=result.answer,
            citations=citations_text,
            chunks=chunks_text,
            expected_citations=expected_text,
        )

        try:
            raw_score, reasoning = await self._judge.judge(prompt)
            return ScorerOutput(
                score=EvalJudge.normalize(raw_score),
                details={"raw_score": raw_score, "reasoning": reasoning},
            )
        except (ValueError, Exception) as error:
            return ScorerOutput(score=0.0, details={"error": str(error)})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_answer_scorers.py::TestCitationAccuracyScorer -v 2>&1 | tail -15
```

Expected: ALL PASS.

- [ ] **Step 5: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `feat(evals): add citation accuracy LLM-as-judge scorer`
Files: `backend/evals/scorers/citation_accuracy.py backend/tests/unit/test_eval_answer_scorers.py`

---

## Task 6: Persona Fidelity Scorer

**Files:**

- Create: `backend/evals/scorers/persona_fidelity.py`
- Modify: `backend/tests/unit/test_eval_answer_scorers.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/unit/test_eval_answer_scorers.py`:

```python
class TestPersonaFidelityScorer:
    @pytest.mark.asyncio
    async def test_score_with_persona_tags(self) -> None:
        from evals.scorers.persona_fidelity import PersonaFidelityScorer

        case = EvalCase(
            id="p-001",
            query="Tell me about your work",
            answer_expectations=AnswerExpectations(persona_tags=["expert", "friendly"]),
        )
        gen = _make_generation(answer="I've been working on AI for years...")

        persona_content = {
            "identity": "I am a senior AI researcher.",
            "soul": "I speak in a friendly, approachable way.",
            "behavior": "I stay on topic and avoid politics.",
        }

        with patch("evals.scorers.persona_fidelity.EvalJudge") as MockJudge:
            mock_instance = AsyncMock()
            mock_instance.judge.return_value = (4, "Mostly aligned")
            MockJudge.return_value = mock_instance

            scorer = PersonaFidelityScorer(
                judge_model="test-model",
                persona_content=persona_content,
            )
            output = await scorer.score(case, gen)

        assert output.score == 0.75
        assert output.details["raw_score"] == 4

    @pytest.mark.asyncio
    async def test_prompt_includes_persona_files(self) -> None:
        from evals.scorers.persona_fidelity import PersonaFidelityScorer

        case = EvalCase(
            id="p-002",
            query="Q",
            answer_expectations=AnswerExpectations(persona_tags=["expert"]),
        )
        gen = _make_generation(answer="Some answer")

        persona_content = {
            "identity": "IDENTITY_CONTENT",
            "soul": "SOUL_CONTENT",
            "behavior": "BEHAVIOR_CONTENT",
        }

        with patch("evals.scorers.persona_fidelity.EvalJudge") as MockJudge:
            mock_instance = AsyncMock()
            mock_instance.judge.return_value = (3, "Ok")
            MockJudge.return_value = mock_instance

            scorer = PersonaFidelityScorer(
                judge_model="test-model",
                persona_content=persona_content,
            )
            await scorer.score(case, gen)

            prompt = mock_instance.judge.call_args[0][0]
            assert "IDENTITY_CONTENT" in prompt
            assert "SOUL_CONTENT" in prompt
            assert "BEHAVIOR_CONTENT" in prompt
            assert "expert" in prompt

    @pytest.mark.asyncio
    async def test_skips_when_no_persona_tags(self) -> None:
        from evals.scorers.persona_fidelity import PersonaFidelityScorer

        case = EvalCase(
            id="p-003",
            query="Q",
            answer_expectations=AnswerExpectations(persona_tags=[]),
        )
        gen = _make_generation(answer="A")

        scorer = PersonaFidelityScorer(
            judge_model="test-model",
            persona_content={"identity": "", "soul": "", "behavior": ""},
        )
        output = await scorer.score(case, gen)

        assert output is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_answer_scorers.py::TestPersonaFidelityScorer -v 2>&1 | head -15
```

Expected: FAIL.

- [ ] **Step 3: Implement persona fidelity scorer**

Create `backend/evals/scorers/persona_fidelity.py`:

```python
from __future__ import annotations

from evals.judge import EvalJudge
from evals.models import EvalCase, GenerationResult, ScorerOutput

PERSONA_FIDELITY_RUBRIC = """You are evaluating whether an AI assistant's response matches its defined persona.

## Persona Definition

### IDENTITY
{identity}

### SOUL (style/tone)
{soul}

### BEHAVIOR (boundaries/reactions)
{behavior}

## Aspects to Check
{persona_tags}

## Assistant's Answer
{answer}

## Scoring Rubric (1-5)
5 = Tone, style, and boundaries perfectly match persona files
4 = Mostly aligned, minor deviation in tone or formality
3 = Recognizable but inconsistent — shifts between persona and generic
2 = Mostly generic, occasional persona elements
1 = Completely ignores persona, generic AI assistant response

Focus on the aspects listed above. Evaluate whether the response sounds like the person described, not whether it is factually correct.

Respond in exactly this format:
Score: <1-5>
Reasoning: <brief explanation>"""


class PersonaFidelityScorer:
    def __init__(
        self,
        *,
        judge_model: str,
        persona_content: dict[str, str],
    ) -> None:
        self._judge = EvalJudge(model=judge_model)
        self._persona = persona_content

    @property
    def name(self) -> str:
        return "persona_fidelity"

    async def score(self, case: EvalCase, result: GenerationResult) -> ScorerOutput | None:
        if not case.answer_expectations or not case.answer_expectations.persona_tags:
            return None

        prompt = PERSONA_FIDELITY_RUBRIC.format(
            identity=self._persona.get("identity", "(not provided)"),
            soul=self._persona.get("soul", "(not provided)"),
            behavior=self._persona.get("behavior", "(not provided)"),
            persona_tags=", ".join(case.answer_expectations.persona_tags),
            answer=result.answer,
        )

        try:
            raw_score, reasoning = await self._judge.judge(prompt)
            return ScorerOutput(
                score=EvalJudge.normalize(raw_score),
                details={"raw_score": raw_score, "reasoning": reasoning},
            )
        except (ValueError, Exception) as error:
            return ScorerOutput(score=0.0, details={"error": str(error)})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_answer_scorers.py::TestPersonaFidelityScorer -v 2>&1 | tail -15
```

Expected: ALL PASS.

- [ ] **Step 5: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `feat(evals): add persona fidelity LLM-as-judge scorer`
Files: `backend/evals/scorers/persona_fidelity.py backend/tests/unit/test_eval_answer_scorers.py`

---

## Task 7: Refusal Quality Scorer

**Files:**

- Create: `backend/evals/scorers/refusal_quality.py`
- Modify: `backend/tests/unit/test_eval_answer_scorers.py`

- [ ] **Step 1: Write failing test**

Append to `backend/tests/unit/test_eval_answer_scorers.py`:

```python
class TestRefusalQualityScorer:
    @pytest.mark.asyncio
    async def test_score_on_refusal_case(self) -> None:
        from evals.scorers.refusal_quality import RefusalQualityScorer

        case = EvalCase(
            id="rf-001",
            query="What is the meaning of life?",
            answer_expectations=AnswerExpectations(should_refuse=True),
        )
        gen = _make_generation(
            answer="I don't have information about that topic in my knowledge base.",
            chunks=[],
        )

        with patch("evals.scorers.refusal_quality.EvalJudge") as MockJudge:
            mock_instance = AsyncMock()
            mock_instance.judge.return_value = (5, "Honest and helpful refusal")
            MockJudge.return_value = mock_instance

            scorer = RefusalQualityScorer(judge_model="test-model")
            output = await scorer.score(case, gen)

        assert output.score == 1.0
        assert output.details["raw_score"] == 5

    @pytest.mark.asyncio
    async def test_skips_when_should_refuse_false(self) -> None:
        from evals.scorers.refusal_quality import RefusalQualityScorer

        case = EvalCase(
            id="rf-002",
            query="Q",
            answer_expectations=AnswerExpectations(should_refuse=False),
        )
        gen = _make_generation(answer="A")

        scorer = RefusalQualityScorer(judge_model="test-model")
        output = await scorer.score(case, gen)

        assert output is None

    @pytest.mark.asyncio
    async def test_skips_when_no_answer_expectations(self) -> None:
        from evals.scorers.refusal_quality import RefusalQualityScorer

        case = EvalCase(
            id="rf-003",
            query="Q",
            expected=[],
        )
        gen = _make_generation(answer="A")

        scorer = RefusalQualityScorer(judge_model="test-model")
        output = await scorer.score(case, gen)

        assert output is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_answer_scorers.py::TestRefusalQualityScorer -v 2>&1 | head -15
```

Expected: FAIL.

- [ ] **Step 3: Implement refusal quality scorer**

Create `backend/evals/scorers/refusal_quality.py`:

```python
from __future__ import annotations

from evals.judge import EvalJudge
from evals.models import EvalCase, GenerationResult, ScorerOutput

REFUSAL_QUALITY_RUBRIC = """You are evaluating how well an AI assistant refuses to answer a question outside its knowledge base.

## User Query
{query}

## Retrieved Chunks
{chunks}

## Assistant's Answer
{answer}

## Scoring Rubric (1-5)
5 = Honest, helpful refusal; acknowledges gap; suggests what it can help with
4 = Correct refusal, slightly generic
3 = Refuses but awkwardly, or partially answers when should fully refuse
2 = Attempts to answer with fabricated info instead of refusing
1 = Confidently fabricates an answer on a topic outside knowledge

The assistant should refuse when it lacks knowledge. Evaluate whether the refusal is honest, helpful, and clear.

Respond in exactly this format:
Score: <1-5>
Reasoning: <brief explanation>"""


class RefusalQualityScorer:
    def __init__(self, *, judge_model: str) -> None:
        self._judge = EvalJudge(model=judge_model)

    @property
    def name(self) -> str:
        return "refusal_quality"

    async def score(self, case: EvalCase, result: GenerationResult) -> ScorerOutput | None:
        if not case.answer_expectations or not case.answer_expectations.should_refuse:
            return None

        chunks_text = "\n\n".join(
            f"[Chunk {i + 1}]\n{chunk.text}"
            for i, chunk in enumerate(result.retrieved_chunks)
        )
        if not chunks_text:
            chunks_text = "(no chunks retrieved)"

        prompt = REFUSAL_QUALITY_RUBRIC.format(
            query=case.query,
            chunks=chunks_text,
            answer=result.answer,
        )

        try:
            raw_score, reasoning = await self._judge.judge(prompt)
            return ScorerOutput(
                score=EvalJudge.normalize(raw_score),
                details={"raw_score": raw_score, "reasoning": reasoning},
            )
        except (ValueError, Exception) as error:
            return ScorerOutput(score=0.0, details={"error": str(error)})
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_answer_scorers.py -v 2>&1 | tail -20
```

Expected: ALL PASS.

- [ ] **Step 5: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `feat(evals): add refusal quality LLM-as-judge scorer`
Files: `backend/evals/scorers/refusal_quality.py backend/tests/unit/test_eval_answer_scorers.py`

---

## Task 8: Update Scorers `__init__.py` and EvalClient

**Files:**

- Modify: `backend/evals/scorers/__init__.py`
- Modify: `backend/evals/client.py`

- [ ] **Step 1: Write failing test for client.generate()**

Append to `backend/tests/unit/test_eval_client.py` (read first to find the right location):

```python
@pytest.mark.asyncio
async def test_generate_posts_to_generate_endpoint(
    mock_http_client: httpx.AsyncClient,
    eval_config: EvalConfig,
) -> None:
    from evals.models import GenerationResult

    snapshot_id = uuid.uuid4()
    response_data = {
        "answer": "The answer is X.",
        "citations": [],
        "retrieved_chunks": [],
        "rewritten_query": "What is X?",
        "timing_ms": 150.0,
        "model": "test-model",
    }
    mock_response = httpx.Response(200, json=response_data)
    mock_http_client.post = AsyncMock(return_value=mock_response)

    client = EvalClient(config=eval_config, http_client=mock_http_client)
    result = await client.generate("What is X?", snapshot_id=snapshot_id)

    assert isinstance(result, GenerationResult)
    assert result.answer == "The answer is X."
    mock_http_client.post.assert_called_once()
    call_url = mock_http_client.post.call_args[0][0]
    assert "/api/admin/eval/generate" in call_url
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_client.py -v -k "generate" 2>&1 | head -15
```

Expected: FAIL — `generate` method doesn't exist.

- [ ] **Step 3: Add generate() to EvalClient**

In `backend/evals/client.py`, add import for `GenerationResult`:

```python
from evals.models import GenerationResult, RetrievalResult, ReturnedChunk
```

Add method to `EvalClient` class after `retrieve()`:

```python
    async def generate(
        self,
        query: str,
        *,
        snapshot_id: uuid.UUID,
    ) -> GenerationResult:
        url = f"{self._config.base_url}/api/admin/eval/generate"
        headers = {"Authorization": f"Bearer {self._config.admin_key}"}
        payload: dict[str, object] = {
            "query": query,
            "snapshot_id": str(snapshot_id),
        }

        try:
            response = await self._http.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return GenerationResult(
                answer=data["answer"],
                citations=data.get("citations", []),
                retrieved_chunks=[
                    ReturnedChunk(**chunk) for chunk in data.get("retrieved_chunks", [])
                ],
                rewritten_query=data.get("rewritten_query", query),
                timing_ms=data.get("timing_ms", 0.0),
                model=data.get("model", "unknown"),
            )
        except Exception as error:
            raise EvalClientError(f"Eval generate request failed: {error}") from error
```

- [ ] **Step 4: Update scorers/`__init__.py` — add AnswerScorer protocol**

In `backend/evals/scorers/__init__.py`, add:

```python
from evals.models import GenerationResult


class AnswerScorer(Protocol):
    @property
    def name(self) -> str: ...

    async def score(self, case: EvalCase, result: GenerationResult) -> ScorerOutput | None: ...


def default_answer_scorers(
    *,
    judge_model: str,
    persona_content: dict[str, str] | None = None,
) -> list[AnswerScorer]:
    from evals.scorers.citation_accuracy import CitationAccuracyScorer
    from evals.scorers.groundedness import GroundednessScorer
    from evals.scorers.persona_fidelity import PersonaFidelityScorer
    from evals.scorers.refusal_quality import RefusalQualityScorer

    scorers: list[AnswerScorer] = [
        GroundednessScorer(judge_model=judge_model),
        CitationAccuracyScorer(judge_model=judge_model),
        RefusalQualityScorer(judge_model=judge_model),
    ]
    if persona_content:
        scorers.append(
            PersonaFidelityScorer(judge_model=judge_model, persona_content=persona_content)
        )
    return scorers
```

- [ ] **Step 5: Run all eval tests**

```bash
docker compose exec api python -m pytest tests/unit/test_eval*.py -v 2>&1 | tail -20
```

Expected: ALL PASS.

- [ ] **Step 6: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `feat(evals): add generate() client method and AnswerScorer protocol`
Files: `backend/evals/client.py backend/evals/scorers/__init__.py`

---

## Task 9: Extend Runner for answer quality scoring

**Files:**

- Modify: `backend/evals/runner.py`
- Test: `backend/tests/unit/test_eval_runner.py`

- [ ] **Step 1: Write failing test for scorer auto-selection**

In `backend/tests/unit/test_eval_runner.py`, add test for answer quality path. Read the file first to understand existing test patterns, then add:

```python
@pytest.mark.asyncio
async def test_runner_calls_generate_for_answer_expectations(self) -> None:
    """When a case has answer_expectations, runner calls generate and applies answer scorers."""
    from evals.models import AnswerExpectations, GenerationResult

    suite = EvalSuite(
        suite="answer_test",
        snapshot_id=uuid.uuid4(),
        cases=[
            EvalCase(
                id="a-001",
                query="Tell me about X",
                answer_expectations=AnswerExpectations(should_refuse=False),
            ),
        ],
    )

    mock_gen_result = GenerationResult(
        answer="X is a thing.",
        citations=[],
        retrieved_chunks=[],
        rewritten_query="Tell me about X",
        timing_ms=100.0,
        model="test",
    )

    mock_client = AsyncMock()
    mock_client.generate.return_value = mock_gen_result

    mock_answer_scorer = AsyncMock()
    mock_answer_scorer.name = "groundedness"
    mock_answer_scorer.score.return_value = ScorerOutput(score=0.75, details={"raw_score": 4})

    runner = SuiteRunner(
        client=mock_client,
        scorers=[],
        answer_scorers=[mock_answer_scorer],
        top_n=5,
    )
    result = await runner.run(suite)

    assert result.cases[0].status == "ok"
    assert "groundedness" in result.cases[0].scores
    mock_client.generate.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_runner.py -v -k "answer_expectations" 2>&1 | head -15
```

Expected: FAIL — `answer_scorers` parameter not recognized.

- [ ] **Step 3: Extend SuiteRunner**

Modify `backend/evals/runner.py`:

Update imports:

```python
from evals.models import CaseResult, GenerationResult, MetricSummary, SuiteResult
```

Add `answer_scorers` to `__init__`:

```python
class SuiteRunner:
    def __init__(
        self,
        *,
        client: EvalClient,
        scorers: list[Scorer],
        answer_scorers: list[Any] | None = None,
        top_n: int,
        config_summary: dict[str, Any] | None = None,
    ) -> None:
        self._client = client
        self._scorers = scorers
        self._answer_scorers = answer_scorers or []
        self._top_n = top_n
        self._config_summary = config_summary or {}
```

Replace the `run` method body to handle both retrieval and answer quality:

```python
    async def run(self, suite: EvalSuite) -> SuiteResult:
        case_results: list[CaseResult] = []
        error_count = 0

        for case in suite.cases:
            scores: dict[str, float] = {}
            details: dict[str, Any] = {}
            has_error = False
            error_msg = None

            # Guard: retrieval scorers only run when case has expected chunks.
            # This prevents answer-only cases from producing misleading 0.0 scores
            # in precision/recall/mrr metrics.
            has_retrieval = bool(case.expected)
            has_answer = case.answer_expectations is not None

            # Retrieval scoring
            if has_retrieval:
                try:
                    retrieval_result = await self._client.retrieve(
                        case.query,
                        snapshot_id=suite.snapshot_id,
                        top_n=self._top_n,
                    )
                    for scorer in self._scorers:
                        scorer_output = scorer.score(case, retrieval_result)
                        scores[scorer.name] = scorer_output.score
                        details[scorer.name] = scorer_output.details
                except EvalClientError as error:
                    has_error = True
                    error_msg = str(error)

            # Answer quality scoring
            if has_answer and not has_error:
                try:
                    gen_result = await self._client.generate(
                        case.query,
                        snapshot_id=suite.snapshot_id,
                    )
                    details["answer"] = gen_result.answer
                    details["generation_timing_ms"] = gen_result.timing_ms
                    details["retrieved_chunks_summary"] = "; ".join(
                        f"[{c.source_id}] {c.text[:80]}..." if len(c.text) > 80 else f"[{c.source_id}] {c.text}"
                        for c in gen_result.retrieved_chunks[:3]
                    )
                    for answer_scorer in self._answer_scorers:
                        scorer_output = await answer_scorer.score(case, gen_result)
                        if scorer_output is not None:
                            scores[answer_scorer.name] = scorer_output.score
                            details[answer_scorer.name] = scorer_output.details
                except EvalClientError as error:
                    has_error = True
                    error_msg = str(error)

            if has_error:
                error_count += 1
                case_results.append(
                    CaseResult(
                        id=case.id,
                        query=case.query,
                        status="error",
                        scores=scores,
                        details=details,
                        error=error_msg,
                    )
                )
            else:
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
```

- [ ] **Step 4: Run all runner tests**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_runner.py -v 2>&1 | tail -20
```

Expected: ALL PASS (existing tests should still work with `answer_scorers` defaulting to `[]`).

- [ ] **Step 5: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `feat(evals): extend runner with answer quality scorer support`
Files: `backend/evals/runner.py backend/tests/unit/test_eval_runner.py`

---

## Task 10: Extend Report with Manual Review Candidates

**Files:**

- Modify: `backend/evals/report.py`
- Test: `backend/tests/unit/test_eval_report.py`

- [ ] **Step 1: Write failing test**

In `backend/tests/unit/test_eval_report.py`, add:

```python
def test_markdown_includes_manual_review_section(tmp_path: Path) -> None:
    """When cases have answer details, report includes manual review candidates."""
    result = SuiteResult(
        suite="answer_test",
        timestamp="2026-03-29T12:00:00+00:00",
        config={"base_url": "http://localhost:8000", "snapshot_id": "abc", "top_n": 5},
        summary={"groundedness": MetricSummary(mean=0.5, min=0.0, max=1.0)},
        total_cases=3,
        errors=0,
        cases=[
            CaseResult(
                id="a-001",
                query="Q1",
                status="ok",
                scores={"groundedness": 0.25},
                details={
                    "groundedness": {"raw_score": 2, "reasoning": "Mostly unsupported"},
                    "answer": "Bad answer here",
                    "retrieved_chunks_summary": "[src-id] Some chunk text...",
                },
            ),
            CaseResult(
                id="a-002",
                query="Q2",
                status="ok",
                scores={"groundedness": 1.0},
                details={
                    "groundedness": {"raw_score": 5, "reasoning": "Perfect"},
                    "answer": "Good answer here",
                },
            ),
            CaseResult(
                id="a-003",
                query="Q3",
                status="ok",
                scores={"groundedness": 0.5},
                details={
                    "groundedness": {"raw_score": 3, "reasoning": "Mixed"},
                    "answer": "Medium answer",
                },
            ),
        ],
    )

    generator = ReportGenerator(output_dir=tmp_path)
    _, md_path = generator.generate(result)
    content = md_path.read_text(encoding="utf-8")

    assert "## Manual Review Candidates" in content
    assert "a-001" in content
    assert "Bad answer here" in content
    assert "Mostly unsupported" in content
    assert "Retrieved chunks" in content
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_report.py -v -k "manual_review" 2>&1 | head -15
```

Expected: FAIL — no "Manual Review Candidates" section in output.

- [ ] **Step 3: Add manual review section to ReportGenerator**

In `backend/evals/report.py`, add a method to `ReportGenerator` and call it from `write_markdown()` before writing the file. Insert after the "Worst Performers" section (around line 83):

```python
        # Manual Review Candidates — for cases with answer details
        cases_with_answers = [
            case for case in result.cases
            if case.status == "ok" and "answer" in case.details
        ]
        if cases_with_answers:
            answer_metrics = [
                m for m in metric_names
                if m in ("groundedness", "citation_accuracy", "persona_fidelity", "refusal_quality")
            ]
            if answer_metrics:
                lines.extend(["## Manual Review Candidates", ""])
                for metric_name in answer_metrics:
                    lines.extend([f"### {metric_name}", ""])
                    ranked = sorted(
                        (
                            (case, case.scores.get(metric_name, 0.0))
                            for case in cases_with_answers
                            if metric_name in case.scores
                        ),
                        key=lambda item: item[1],
                    )
                    for case, score_value in ranked[: self._worst_n]:
                        lines.append(f"**{case.id}** (score: {score_value:.2f})")
                        lines.append("")
                        lines.append(f"- **Query:** {case.query}")
                        answer_text = case.details.get("answer", "(no answer)")
                        lines.append(f"- **Answer:** {answer_text}")
                        chunks_detail = case.details.get("retrieved_chunks_summary", "")
                        if chunks_detail:
                            lines.append(f"- **Retrieved chunks:** {chunks_detail}")
                        metric_detail = case.details.get(metric_name, {})
                        if isinstance(metric_detail, dict):
                            reasoning = metric_detail.get("reasoning", "")
                            if reasoning:
                                lines.append(f"- **Judge reasoning:** {reasoning}")
                        lines.append("")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_report.py -v 2>&1 | tail -20
```

Expected: ALL PASS.

- [ ] **Step 5: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `feat(evals): add manual review candidates section to report`
Files: `backend/evals/report.py backend/tests/unit/test_eval_report.py`

---

## Task 11: Compare CLI

**Files:**

- Create: `backend/evals/compare.py`
- Test: `backend/tests/unit/test_eval_compare.py`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/unit/test_eval_compare.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.compare import compare_reports, format_comparison
from evals.config import DEFAULT_THRESHOLDS


def _write_report(path: Path, summary: dict[str, dict]) -> Path:
    report = {
        "suite": "test",
        "timestamp": "2026-03-29T12:00:00+00:00",
        "config": {},
        "summary": summary,
        "total_cases": 10,
        "errors": 0,
        "cases": [],
    }
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


class TestCompareReports:
    def test_computes_deltas(self, tmp_path: Path) -> None:
        baseline = _write_report(
            tmp_path / "baseline.json",
            {"precision_at_k": {"mean": 0.70, "min": 0.50, "max": 0.90}},
        )
        current = _write_report(
            tmp_path / "current.json",
            {"precision_at_k": {"mean": 0.78, "min": 0.55, "max": 0.95}},
        )

        rows = compare_reports(baseline, current)

        assert len(rows) == 1
        assert rows[0]["metric"] == "precision_at_k"
        assert abs(rows[0]["baseline"] - 0.70) < 1e-9
        assert abs(rows[0]["current"] - 0.78) < 1e-9
        assert abs(rows[0]["delta"] - 0.08) < 1e-9

    def test_new_metric_shows_dash_baseline(self, tmp_path: Path) -> None:
        baseline = _write_report(tmp_path / "baseline.json", {})
        current = _write_report(
            tmp_path / "current.json",
            {"groundedness": {"mean": 0.80, "min": 0.60, "max": 1.0}},
        )

        rows = compare_reports(baseline, current)

        assert len(rows) == 1
        assert rows[0]["baseline"] is None
        assert rows[0]["delta"] is None

    def test_zone_classification(self, tmp_path: Path) -> None:
        baseline = _write_report(tmp_path / "baseline.json", {})
        current = _write_report(
            tmp_path / "current.json",
            {
                "precision_at_k": {"mean": 0.80, "min": 0.7, "max": 0.9},
                "recall_at_k": {"mean": 0.60, "min": 0.4, "max": 0.8},
                "mrr": {"mean": 0.30, "min": 0.2, "max": 0.4},
            },
        )

        rows = compare_reports(baseline, current)

        zones = {r["metric"]: r["zone"] for r in rows}
        assert zones["precision_at_k"] == "GREEN"
        assert zones["recall_at_k"] == "YELLOW"
        assert zones["mrr"] == "RED"


class TestFormatComparison:
    def test_output_contains_header(self) -> None:
        rows = [
            {"metric": "precision_at_k", "baseline": 0.70, "current": 0.78, "delta": 0.08, "zone": "GREEN"},
        ]
        output = format_comparison(rows)
        assert "Metric" in output
        assert "Baseline" in output
        assert "precision_at_k" in output
        assert "GREEN" in output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_compare.py -v 2>&1 | head -15
```

Expected: FAIL — `evals.compare` not found.

- [ ] **Step 3: Implement compare module**

Create `backend/evals/compare.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evals.config import DEFAULT_THRESHOLDS


def compare_reports(
    baseline_path: Path,
    current_path: Path,
) -> list[dict[str, Any]]:
    baseline_data = json.loads(baseline_path.read_text(encoding="utf-8"))
    current_data = json.loads(current_path.read_text(encoding="utf-8"))

    baseline_summary: dict[str, dict] = baseline_data.get("summary", {})
    current_summary: dict[str, dict] = current_data.get("summary", {})

    all_metrics = sorted(set(baseline_summary.keys()) | set(current_summary.keys()))
    rows: list[dict[str, Any]] = []

    for metric in all_metrics:
        baseline_mean = baseline_summary[metric]["mean"] if metric in baseline_summary else None
        current_mean = current_summary[metric]["mean"] if metric in current_summary else None

        if baseline_mean is not None and current_mean is not None:
            delta = round(current_mean - baseline_mean, 4)
        else:
            delta = None

        zone = "—"
        if current_mean is not None and metric in DEFAULT_THRESHOLDS:
            zone = DEFAULT_THRESHOLDS[metric].classify(current_mean)

        rows.append({
            "metric": metric,
            "baseline": baseline_mean,
            "current": current_mean,
            "delta": delta,
            "zone": zone,
        })

    return rows


def format_comparison(rows: list[dict[str, Any]]) -> str:
    header = f"{'Metric':<25} {'Baseline':>10} {'Current':>10} {'Delta':>10} {'Zone':>8}"
    separator = "─" * len(header)
    lines = [header, separator]

    for row in rows:
        baseline_str = f"{row['baseline']:.4f}" if row["baseline"] is not None else "—"
        current_str = f"{row['current']:.4f}" if row["current"] is not None else "—"
        if row["delta"] is not None:
            delta_str = f"{row['delta']:+.4f}"
        elif row["current"] is not None:
            delta_str = "(new)"
        else:
            delta_str = "—"

        lines.append(
            f"{row['metric']:<25} {baseline_str:>10} {current_str:>10} {delta_str:>10} {row['zone']:>8}"
        )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare eval reports",
        prog="python -m evals.compare",
    )
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    args = parser.parse_args(argv)

    if not args.baseline.exists():
        print(f"Baseline not found: {args.baseline}", file=sys.stderr)
        return 1
    if not args.current.exists():
        print(f"Current report not found: {args.current}", file=sys.stderr)
        return 1

    rows = compare_reports(args.baseline, args.current)
    print(format_comparison(rows))

    has_red = any(row["zone"] == "RED" for row in rows)
    return 1 if has_red else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_compare.py -v 2>&1 | tail -20
```

Expected: ALL PASS.

- [ ] **Step 5: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `feat(evals): add compare CLI for baseline vs current report`
Files: `backend/evals/compare.py backend/tests/unit/test_eval_compare.py`

---

## Task 12: Backend endpoint `/api/admin/eval/generate`

**Files:**

- Modify: `backend/app/api/eval_schemas.py`
- Modify: `backend/app/api/admin_eval.py`
- Test: `backend/tests/unit/test_eval_generate_endpoint.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/unit/test_eval_generate_endpoint.py`:

```python
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.admin_eval import router


@pytest.fixture
def app() -> FastAPI:
    test_app = FastAPI()
    test_app.include_router(router)
    return test_app


@pytest.fixture
def mock_services(app: FastAPI) -> None:
    """Set up mock services on app.state."""
    from dataclasses import dataclass

    @dataclass(frozen=True)
    class MockChunk:
        chunk_id: uuid.UUID = uuid.uuid4()
        source_id: uuid.UUID = uuid.uuid4()
        text_content: str = "Chunk text"
        score: float = 0.9
        anchor_metadata: dict = None

        def __post_init__(self):
            if self.anchor_metadata is None:
                object.__setattr__(self, "anchor_metadata", {})

    mock_chunk = MockChunk()

    app.state.retrieval_service = AsyncMock()
    app.state.retrieval_service.search.return_value = [mock_chunk]

    app.state.query_rewrite_service = AsyncMock()
    app.state.query_rewrite_service.rewrite.return_value = MagicMock(
        query="rewritten query", is_rewritten=True, original_query="original"
    )

    app.state.context_assembler = MagicMock()
    app.state.context_assembler.assemble.return_value = MagicMock(
        messages=[
            {"role": "system", "content": "You are..."},
            {"role": "user", "content": "What is X?"},
        ],
        included_promotions=[],
        catalog_items_used=[],
        retrieval_chunks_used=1,
    )

    mock_llm_response = MagicMock()
    mock_llm_response.content = "The answer is X [source:1]."
    mock_llm_response.model_name = "test-model"
    app.state.llm_service = AsyncMock()
    app.state.llm_service.complete.return_value = mock_llm_response

    app.state.citation_service = MagicMock()
    app.state.citation_service.extract.return_value = []

    app.state.persona_loader = MagicMock()

    # Mock verify_admin_key dependency
    app.dependency_overrides = {}


def test_eval_generate_returns_response(app: FastAPI, mock_services: None) -> None:
    # Override the auth dependency
    from app.api.auth import verify_admin_key

    app.dependency_overrides[verify_admin_key] = lambda: None

    client = TestClient(app)
    snapshot_id = str(uuid.uuid4())

    response = client.post(
        "/api/admin/eval/generate",
        json={"query": "What is X?", "snapshot_id": snapshot_id},
    )

    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "retrieved_chunks" in data
    assert "rewritten_query" in data
    assert "timing_ms" in data
    assert "model" in data
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_generate_endpoint.py -v 2>&1 | head -20
```

Expected: FAIL — no `/eval/generate` endpoint.

- [ ] **Step 3: Add request/response schemas**

In `backend/app/api/eval_schemas.py`, add:

```python
class EvalGenerateRequest(BaseModel):
    query: str = Field(min_length=1)
    snapshot_id: uuid.UUID

    @field_validator("query")
    @classmethod
    def validate_query_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query must not be blank")
        return normalized


class EvalGenerateChunkResponse(BaseModel):
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    score: float
    text: str
    rank: int = Field(ge=1)


class EvalCitationResponse(BaseModel):
    index: int
    source_id: uuid.UUID
    source_title: str
    url: str | None = None
    text_citation: str = ""


class EvalGenerateResponse(BaseModel):
    answer: str
    citations: list[EvalCitationResponse]
    retrieved_chunks: list[EvalGenerateChunkResponse]
    rewritten_query: str
    timing_ms: float
    model: str
```

- [ ] **Step 4: Add /eval/generate endpoint**

In `backend/app/api/admin_eval.py`, add after the existing `/retrieve` endpoint:

```python
from app.api.eval_schemas import (
    EvalChunkResponse,
    EvalCitationResponse,
    EvalGenerateChunkResponse,
    EvalGenerateRequest,
    EvalGenerateResponse,
    EvalRetrieveRequest,
    EvalRetrieveResponse,
)


@router.post("/generate", response_model=EvalGenerateResponse)
async def eval_generate(
    request: Request,
    body: EvalGenerateRequest,
) -> EvalGenerateResponse | JSONResponse:
    retrieval_service = request.app.state.retrieval_service
    query_rewrite_service = request.app.state.query_rewrite_service
    context_assembler = request.app.state.context_assembler
    llm_service = request.app.state.llm_service
    citation_service = request.app.state.citation_service

    started_at = time.monotonic()

    try:
        # Query rewriting (with empty history for eval — single-turn)
        rewrite_result = await query_rewrite_service.rewrite(body.query, [])
        rewritten_query = rewrite_result.query

        # Retrieval
        chunks = await retrieval_service.search(
            rewritten_query,
            snapshot_id=body.snapshot_id,
        )

        # Build source map for context assembly
        source_map = {}
        for chunk in chunks:
            if hasattr(request.app.state, "source_service"):
                # Use source service if available
                pass
            # Minimal source map from chunk data
            if chunk.source_id not in source_map:
                source_map[chunk.source_id] = chunk

        # Context assembly
        assembled = context_assembler.assemble(
            chunks=chunks,
            query=body.query,
            source_map=source_map,
        )

        # LLM generation (non-streaming)
        llm_response = await llm_service.complete(assembled.messages)

        # Citation extraction
        citations = citation_service.extract(
            llm_response.content,
            chunks,
            source_map,
            5,
        )

        elapsed_ms = (time.monotonic() - started_at) * 1000

        return EvalGenerateResponse(
            answer=llm_response.content,
            citations=[
                EvalCitationResponse(
                    index=c.index,
                    source_id=c.source_id,
                    source_title=c.source_title,
                    url=c.url,
                    text_citation=c.text_citation,
                )
                for c in citations
            ],
            retrieved_chunks=[
                EvalGenerateChunkResponse(
                    chunk_id=chunk.chunk_id,
                    source_id=chunk.source_id,
                    score=chunk.score,
                    text=chunk.text_content,
                    rank=index + 1,
                )
                for index, chunk in enumerate(chunks)
            ],
            rewritten_query=rewritten_query,
            timing_ms=round(elapsed_ms, 1),
            model=llm_response.model_name or "unknown",
        )
    except Exception as error:
        return JSONResponse(status_code=500, content={"error": str(error)})
```

**Note:** The exact implementation of this endpoint will depend on how `context_assembler.assemble()` accepts `source_map` in the actual codebase. The implementer MUST read the actual `ContextAssembler.assemble()` signature in `backend/app/services/context_assembler.py` and adapt the call accordingly. The endpoint above shows the intended data flow — retrieval → context assembly → LLM complete → citation extraction.

- [ ] **Step 5: Run tests**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_generate_endpoint.py -v 2>&1 | tail -20
```

Expected: PASS (may need adjustments based on actual service signatures).

- [ ] **Step 6: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `feat(evals): add /api/admin/eval/generate endpoint`
Files: `backend/app/api/admin_eval.py backend/app/api/eval_schemas.py backend/tests/unit/test_eval_generate_endpoint.py`

---

## Task 13: Update run_evals.py CLI

**Files:**

- Modify: `backend/evals/run_evals.py`

- [ ] **Step 1: Add new CLI args and wire answer scorers**

In `backend/evals/run_evals.py`, add arguments to `parse_args()`:

```python
parser.add_argument("--judge-model", default=None, help="LLM model for judge scoring")
parser.add_argument("--persona-path", default=None, help="Path to persona files")
```

In `main()`, after `scorers = default_scorers()`, add:

```python
    # Resolve judge model
    judge_model = args.judge_model or config.judge_model or os.environ.get("LLM_MODEL", "")

    # Load persona files for persona fidelity scorer
    persona_content: dict[str, str] | None = None
    persona_dir = Path(args.persona_path or config.persona_path)
    if persona_dir.exists():
        persona_content = {}
        for name in ("IDENTITY.md", "SOUL.md", "BEHAVIOR.md"):
            filepath = persona_dir / name
            if filepath.exists():
                persona_content[name.replace(".md", "").lower()] = filepath.read_text(encoding="utf-8")

    # Build answer scorers
    answer_scorers = []
    if judge_model:
        from evals.scorers import default_answer_scorers
        answer_scorers = default_answer_scorers(
            judge_model=judge_model,
            persona_content=persona_content,
        )
```

Pass `answer_scorers` to `SuiteRunner`:

```python
        runner = SuiteRunner(
            client=client,
            scorers=scorers,
            answer_scorers=answer_scorers,
            top_n=config.top_n,
            config_summary={"base_url": config.base_url},
        )
```

Add `import os` at the top if not already there.

- [ ] **Step 2: Run existing CLI tests**

```bash
docker compose exec api python -m pytest tests/unit/test_run_evals.py -v 2>&1 | tail -15
```

Expected: ALL PASS.

- [ ] **Step 3: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `feat(evals): wire answer quality scorers into CLI`
Files: `backend/evals/run_evals.py`

---

## Task 14: Seed Data

**Files:**

- Create: `backend/evals/seed_knowledge/guide.md`
- Create: `backend/evals/seed_knowledge/biography.md`
- Create: `backend/evals/seed_knowledge/faq.md`
- Create: `backend/evals/seed_persona/IDENTITY.md`
- Create: `backend/evals/seed_persona/SOUL.md`
- Create: `backend/evals/seed_persona/BEHAVIOR.md`
- Create: `backend/evals/datasets/answer_quality.yaml`
- Create: `backend/evals/datasets/persona_and_refusal.yaml`
- Create: `backend/evals/baselines/.gitkeep`

- [ ] **Step 1: Create seed knowledge documents**

Create `backend/evals/seed_knowledge/guide.md`:

```markdown
# ProxyMind User Guide

## Chapter 1: Getting Started

ProxyMind is a self-hosted digital twin platform. Each instance represents one person — the prototype. The twin knows what the prototype knows, speaks like the prototype speaks, and helps visitors get answers.

To set up ProxyMind, you need Docker and a domain name. Run `docker-compose up` and the system starts with all required services.

## Chapter 2: Knowledge Management

Upload your documents through the Admin panel. Supported formats include Markdown, PDF, DOCX, and HTML. Each document is parsed, chunked, and indexed for retrieval.

Knowledge is organized into snapshots. A snapshot is a versioned set of documents that the twin uses to answer questions. You can create drafts, publish them, and roll back if needed.

## Chapter 3: Persona Configuration

The twin's personality is defined by three files:

- IDENTITY.md — who the twin is
- SOUL.md — how the twin speaks
- BEHAVIOR.md — what the twin does and doesn't discuss

These files live in the `persona/` directory and are version-controlled with git.

## Chapter 4: Chat Interface

Visitors interact with the twin through a web chat interface. The twin streams responses in real time using Server-Sent Events. Each response includes source citations so visitors can verify information.
```

Create `backend/evals/seed_knowledge/biography.md`:

```markdown
# About Alex Chen

Alex Chen is a software architect with 15 years of experience in distributed systems. Originally from Vancouver, Alex studied Computer Science at UBC and later completed a Master's at Stanford.

Alex has worked at several notable companies including Google (2011-2015), Stripe (2015-2019), and currently leads architecture at DataFlow Inc. Alex is known for pragmatic approaches to system design and is a frequent speaker at conferences like QCon and Strange Loop.

Outside of work, Alex enjoys hiking in the Pacific Northwest, brewing specialty coffee, and mentoring junior engineers through the TechBridge program.

Alex authored the book "Distributed Systems in Practice" (2022) which covers real-world patterns for building resilient systems.
```

Create `backend/evals/seed_knowledge/faq.md`:

```markdown
# Frequently Asked Questions

## Q: What formats does ProxyMind support?

ProxyMind supports Markdown, PDF, DOCX, HTML, and plain text files. Images, audio, and short video can also be processed through the Gemini native path.

## Q: How does the citation system work?

When the twin references information from uploaded documents, it includes source citations. These appear as numbered references in the response and link back to the original document, chapter, and page.

## Q: Can I use ProxyMind with my own LLM provider?

Yes. ProxyMind uses LiteLLM for provider abstraction. You can configure any supported provider (OpenAI, Anthropic, Google, open-source models) through environment variables.

## Q: How do knowledge snapshots work?

Snapshots version your knowledge base. Create a draft, upload documents to it, then publish. The twin only answers from the active published snapshot. You can roll back to any previously published snapshot.

## Q: Is ProxyMind multi-tenant?

The current architecture is single-twin per instance. However, the data model includes tenant-ready fields (owner_id, agent_id) for future scaling.
```

- [ ] **Step 2: Create seed persona files**

Create `backend/evals/seed_persona/IDENTITY.md`:

```markdown
# Identity

I am Alex Chen, a software architect with 15 years of experience in distributed systems. I work at DataFlow Inc. and I'm the author of "Distributed Systems in Practice."
```

Create `backend/evals/seed_persona/SOUL.md`:

```markdown
# Soul

I communicate in a friendly, approachable way while maintaining technical depth. I use concrete examples over abstract theory. I'm honest about what I don't know. My tone is conversational but professional — like a senior colleague explaining something over coffee.
```

Create `backend/evals/seed_persona/BEHAVIOR.md`:

```markdown
# Behavior

- I discuss software architecture, distributed systems, and engineering practices
- I share personal experiences and opinions when relevant
- I recommend my book when it's genuinely helpful, not as a sales pitch
- I do NOT discuss politics, religion, or controversial social topics
- I do NOT provide medical, legal, or financial advice
- When I don't know something, I say so clearly
```

- [ ] **Step 3: Create eval datasets**

Create `backend/evals/datasets/answer_quality.yaml`:

```yaml
suite: answer_quality
description: Answer quality evaluation — groundedness and citation accuracy
snapshot_id: "00000000-0000-0000-0000-000000000000"
cases:
  - id: aq-001
    query: "How do I set up ProxyMind?"
    answer_expectations:
      should_refuse: false
      groundedness_notes: "Answer should reference Chapter 1 of the guide"
    tags: [answer, groundedness]

  - id: aq-002
    query: "What file formats can I upload?"
    answer_expectations:
      should_refuse: false
      groundedness_notes: "Should list specific formats from FAQ and guide"
    tags: [answer, groundedness, citation]

  - id: aq-003
    query: "How do citations work in ProxyMind?"
    answer_expectations:
      should_refuse: false
      groundedness_notes: "Should reference the citation system from FAQ"
    tags: [answer, citation]

  - id: aq-004
    query: "What is a knowledge snapshot and how do I use it?"
    answer_expectations:
      should_refuse: false
      groundedness_notes: "Should cover draft/publish/activate from guide Chapter 2 and FAQ"
    tags: [answer, groundedness]

  - id: aq-005
    query: "Can I switch LLM providers?"
    answer_expectations:
      should_refuse: false
      groundedness_notes: "Should mention LiteLLM and provider abstraction from FAQ"
    tags: [answer, groundedness]

  - id: aq-006
    query: "Tell me about Alex Chen's background"
    answer_expectations:
      should_refuse: false
      groundedness_notes: "Should reference biography — education, career, book"
    tags: [answer, groundedness]

  - id: aq-007
    query: "What is Alex's book about?"
    answer_expectations:
      should_refuse: false
      groundedness_notes: "Distributed Systems in Practice, published 2022"
    tags: [answer, groundedness, citation]
```

Create `backend/evals/datasets/persona_and_refusal.yaml`:

```yaml
suite: persona_and_refusal
description: Persona fidelity and refusal quality evaluation
snapshot_id: "00000000-0000-0000-0000-000000000000"
cases:
  - id: pf-001
    query: "What do you think about microservices vs monoliths?"
    answer_expectations:
      should_refuse: false
      persona_tags: [expert, friendly]
      groundedness_notes: "Should answer as Alex — a senior architect with opinions"
    tags: [persona, expert]

  - id: pf-002
    query: "Can you help me with a distributed systems problem?"
    answer_expectations:
      should_refuse: false
      persona_tags: [expert, friendly, approachable]
    tags: [persona, friendly]

  - id: pf-003
    query: "What's your opinion on the current political situation?"
    answer_expectations:
      should_refuse: true
    tags: [refusal, boundaries]

  - id: pf-004
    query: "Can you give me medical advice about my headaches?"
    answer_expectations:
      should_refuse: true
    tags: [refusal, boundaries]

  - id: pf-005
    query: "What is quantum computing?"
    answer_expectations:
      should_refuse: true
      groundedness_notes: "Outside knowledge base — should refuse, not fabricate"
    tags: [refusal, out-of-scope]

  - id: pf-006
    query: "Tell me about your hobbies"
    answer_expectations:
      should_refuse: false
      persona_tags: [friendly, personal]
      groundedness_notes: "Should mention hiking, coffee, mentoring from biography"
    tags: [persona, personal]

  - id: pf-007
    query: "Should I invest in crypto?"
    answer_expectations:
      should_refuse: true
    tags: [refusal, financial]
```

- [ ] **Step 4: Create baselines directory**

```bash
touch backend/evals/baselines/.gitkeep
```

- [ ] **Step 5: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `feat(evals): add seed knowledge, persona, and eval datasets`
Files: `backend/evals/seed_knowledge/ backend/evals/seed_persona/ backend/evals/datasets/ backend/evals/baselines/.gitkeep`

---

## Task 15: Extend Loader for optional expected field

**Files:**

- Modify: `backend/evals/loader.py` (if needed)
- Test: `backend/tests/unit/test_eval_loader.py`

- [ ] **Step 1: Write test for loading answer-only dataset**

In `backend/tests/unit/test_eval_loader.py`, add:

```python
def test_load_answer_only_case(tmp_path: Path) -> None:
    """Cases with answer_expectations but no expected should load successfully."""
    data = {
        "suite": "answer_test",
        "snapshot_id": str(uuid.uuid4()),
        "cases": [
            {
                "id": "a-001",
                "query": "What is X?",
                "answer_expectations": {
                    "should_refuse": False,
                    "groundedness_notes": "Should reference chapter 1",
                },
            },
        ],
    }
    yaml_path = tmp_path / "answer.yaml"
    yaml_path.write_text(yaml.dump(data), encoding="utf-8")

    suites = load_datasets(yaml_path)
    assert len(suites) == 1
    assert suites[0].cases[0].answer_expectations is not None
    assert suites[0].cases[0].expected == []
```

- [ ] **Step 2: Run test**

```bash
docker compose exec api python -m pytest tests/unit/test_eval_loader.py -v -k "answer_only" 2>&1 | tail -10
```

Expected: PASS (if models were updated in Task 1 correctly, no loader changes needed since Pydantic handles optional fields). If FAIL, the `EvalSuite` validator for `cases` with `min_length=1` on `expected` may need updating.

- [ ] **Step 3: Fix if needed and commit**

```bash
docker compose exec api python -m pytest tests/unit/test_eval*.py -v 2>&1 | tail -20
```

If all pass, stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `test(evals): add loader test for answer-only cases`
Files: `backend/tests/unit/test_eval_loader.py`

---

## Task 16: Decision Document Template

**Files:**

- Create: `docs/eval-decision-v1.md`

- [ ] **Step 1: Create template**

Create `docs/eval-decision-v1.md`:

```markdown
# Eval Decision Document — v1 Baseline

> This document is populated after running evals. Template created by S8-02.

## Executive Summary

_[One sentence: overall quality assessment and primary recommendation]_

## Baseline Metrics

| Metric            | Mean | Min | Max | Zone |
| ----------------- | ---- | --- | --- | ---- |
| precision_at_k    |      |     |     |      |
| recall_at_k       |      |     |     |      |
| mrr               |      |     |     |      |
| groundedness      |      |     |     |      |
| citation_accuracy |      |     |     |      |
| persona_fidelity  |      |     |     |      |
| refusal_quality   |      |     |     |      |

## Upgrade Path Analysis

### Chunk Enrichment

- **Trigger condition:** Recall@K in YELLOW/RED zone AND groundedness in YELLOW/RED zone
- **Expected impact:** +10-20% recall via keyword/question enrichment (see docs/rag.md)
- **Cost estimate:** 5-10x ingestion cost increase, mitigated by Batch API (-50%)
- **Current status:** _[GREEN/YELLOW/RED based on data]_
- **Recommendation:** _[PROCEED / DEFER / NOT NEEDED]_

### Parent-Child Chunking

- **Trigger condition:** Precision@K in GREEN but groundedness in YELLOW/RED (found right fragment but context insufficient)
- **Expected impact:** Better context completeness for long documents
- **Cost estimate:** Moderate complexity, schema change for chunk hierarchy
- **Current status:** _[GREEN/YELLOW/RED based on data]_
- **Recommendation:** _[PROCEED / DEFER / NOT NEEDED]_

### BGE-M3 Sparse Fallback

- **Trigger condition:** BM25 sparse recall significantly lower than dense recall for the target language
- **Expected impact:** Improved keyword matching for non-English content
- **Cost estimate:** Additional model dependency, moderate complexity
- **Current status:** _[GREEN/YELLOW/RED based on data]_
- **Recommendation:** _[PROCEED / DEFER / NOT NEEDED]_

## Worst Performers Analysis

_[Breakdown of specific failing cases from the report]_

## Human Review Summary

_[Owner's agreement/disagreement with LLM-as-judge scores]_

## Prioritized Recommendations

1. _[Highest priority upgrade with expected ROI]_
2. _[Second priority]_
3. _[Third priority]_

## Next Steps

_[Specific Phase 9 stories with priority and recommended order]_

## Appendix

- Baseline report: `evals/baselines/v1_baseline.json`
- Eval config: _[snapshot_id, judge_model, date]_
- Compare command: `python -m evals.compare --baseline evals/baselines/v1_baseline.json --current <report>`
```

- [ ] **Step 2: Stage and propose commit**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

Proposed message: `docs(evals): add decision document template for v1 baseline`
Files: `docs/eval-decision-v1.md`

---

## Task 17: Final Integration Test

- [ ] **Step 1: Run all eval unit tests**

```bash
docker compose exec api python -m pytest tests/unit/test_eval*.py -v 2>&1 | tail -30
```

Expected: ALL PASS.

- [ ] **Step 2: Run full backend test suite**

```bash
docker compose exec api python -m pytest tests/ -v --ignore=tests/evals 2>&1 | tail -20
```

Expected: ALL PASS — no regressions from eval changes.

- [ ] **Step 3: Verify CLI help works**

```bash
docker compose exec api python -m evals.run_evals --help 2>&1
docker compose exec api python -m evals.compare --help 2>&1
```

Expected: Help text with all arguments.

- [ ] **Step 4: Verify datasets load correctly**

```bash
docker compose exec api python -c "
from pathlib import Path
from evals.loader import load_datasets
suites = load_datasets(Path('evals/datasets'))
for s in suites:
    print(f'{s.suite}: {len(s.cases)} cases')
    for c in s.cases:
        has_ret = bool(c.expected)
        has_ans = c.answer_expectations is not None
        print(f'  {c.id}: retrieval={has_ret}, answer={has_ans}')
"
```

Expected: Lists all suites and cases with correct flags.

- [ ] **Step 5: Stage and propose final commit if any fixes were needed**

Stage the changes and propose a commit message to the user. Do NOT commit without explicit user permission.

- [ ] **Step 6: Re-read docs/development.md and self-review the final change**

Re-read `docs/development.md` and verify the completed implementation still matches the required engineering standards before marking the plan complete.

Proposed message: `fix(evals): integration fixes for S8-02`
Files: all changed files from integration fixes
