# eval-framework (S8-02 delta)

Extensions to the eval framework for answer quality scoring support: new models, config additions, runner scorer auto-selection, report manual review section, client generate method, and CLI argument extensions.

## MODIFIED Requirements

### Requirement: Dataset format

The eval dataset format SHALL use YAML files. Each file SHALL describe one `EvalSuite` containing a `suite` name (string, min_length=1), an optional `description` (string), a `snapshot_id` (UUID), and a `cases` list (min_length=1). Each `EvalCase` SHALL have an `id` (string, min_length=1), a `query` (string, min_length=1), an `expected` list of `ExpectedChunk` entries (default empty list, no longer required to be non-empty), optional `tags` (list of strings, defaults to empty), and an optional `answer_expectations` field of type `AnswerExpectations | None` (default `None`). Each `ExpectedChunk` SHALL have a `source_id` (UUID) and a `contains` field (string, min_length=1). Case IDs within a suite MUST be unique; duplicate IDs SHALL cause a validation error. All models SHALL be Pydantic `BaseModel` subclasses. The `expected` field is now optional (defaults to empty list) to support cases that only test answer quality without retrieval expectations.

#### Scenario: Valid suite with single case parses successfully

- **WHEN** a YAML file with a valid suite name, snapshot_id, and one case with id, query, and at least one expected chunk is loaded
- **THEN** the resulting `EvalSuite` object contains the correct suite name, snapshot_id, and one `EvalCase` with matching fields

#### Scenario: Case with empty expected list is valid

- **WHEN** a case defines `expected: []` or omits `expected` entirely
- **THEN** Pydantic validation SHALL succeed and `EvalCase.expected` SHALL equal `[]`

#### Scenario: Case with answer_expectations parsed

- **WHEN** a case includes `answer_expectations` with `should_refuse: true` and `persona_tags: ["expert"]`
- **THEN** the parsed `EvalCase.answer_expectations` SHALL be an `AnswerExpectations` instance with `should_refuse=True` and `persona_tags=["expert"]`

#### Scenario: Case without answer_expectations defaults to None

- **WHEN** a case does not specify `answer_expectations`
- **THEN** the parsed `EvalCase.answer_expectations` SHALL be `None`

#### Scenario: Duplicate case IDs rejected

- **WHEN** a suite contains two cases with the same `id`
- **THEN** Pydantic validation SHALL raise a `ValidationError` with a message matching "Duplicate case id"

---

### Requirement: Suite runner

The `SuiteRunner` SHALL orchestrate eval execution. It SHALL accept both retrieval scorers and answer scorers. For each `EvalCase`, the runner SHALL auto-select which scorers and endpoints to use based on the case's fields:

| Case has                                  | Calls endpoint                      | Scorers applied                                                                       |
| ----------------------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------- |
| `expected` only (non-empty)               | `/eval/retrieve`                    | retrieval scorers (precision_at_k, recall_at_k, mrr)                                  |
| `answer_expectations` only                | `/eval/generate`                    | answer scorers (groundedness, citation_accuracy, persona_fidelity*, refusal_quality*) |
| Both `expected` and `answer_expectations` | `/eval/retrieve` + `/eval/generate` | All applicable scorers                                                                |

*persona_fidelity runs only when `persona_tags` is non-empty. *refusal_quality runs only when `should_refuse == True`.

Execution SHALL be sequential (one case at a time). The runner SHALL aggregate per-scorer metrics across all cases, computing mean, min, and max for each scorer. If an API call fails for a case, the runner SHALL mark that case with status `"error"` and continue. Error cases SHALL be counted separately. The runner SHALL produce a `SuiteResult` containing suite name, timestamp, config summary, total_cases count, errors count, per-scorer `MetricSummary`, and a list of per-case `CaseResult` objects. For answer-scored cases, `CaseResult` MAY be extended with top-level fields such as `answer`, `generation_timing_ms`, `judge_scores`, and `judge_reasoning` for simpler report rendering, while `details` SHALL continue to carry supplementary artifacts such as chunk summaries and scorer-specific detail payloads.

#### Scenario: Case with only expected triggers retrieval scorers

- **WHEN** a case has non-empty `expected` and no `answer_expectations`
- **THEN** the runner calls `/eval/retrieve` and applies retrieval scorers only

#### Scenario: Case with only answer_expectations triggers answer scorers

- **WHEN** a case has `answer_expectations` and empty `expected`
- **THEN** the runner calls `/eval/generate` and applies answer quality scorers only

#### Scenario: Case with both triggers all applicable scorers

- **WHEN** a case has both non-empty `expected` and `answer_expectations`
- **THEN** the runner calls both endpoints and applies all applicable scorers

#### Scenario: API error on one case does not stop the run

- **WHEN** the runner processes a suite with 3 cases and the second case's API call raises an exception
- **THEN** the `SuiteResult` has `total_cases=3`, `errors=1`, and the other two cases have `status="ok"`

---

### Requirement: Report generator

The report generator SHALL produce two output formats from a `SuiteResult`:

**JSON report** (`<suite>_<timestamp>.json`): SHALL contain top-level fields `suite`, `timestamp`, `config`, `total_cases`, `errors`, a `summary` dict with `MetricSummary` (mean, min, max) per scorer name, and a `cases` list with per-case `id`, `query`, `status`, `scores`, `details`, and optional `error`. For answer-scored cases, the JSON CaseResult entries SHALL expose answer-review data either via dedicated top-level fields (`answer`, `generation_timing_ms`, `judge_scores`, `judge_reasoning`) or, for supplementary payloads, within `details` (for example `retrieved_chunks_summary` and scorer-specific detail payloads).

**Markdown report** (`<suite>_<timestamp>.md`): SHALL contain a header with suite name, timestamp, and config summary; a summary table with one row per scorer showing mean, min, and max; a per-case results table; a worst performers section; and a **Manual Review Candidates** section. The Manual Review Candidates section SHALL list, for each answer quality metric, the top-3 worst performers with: case ID and query, the system's generated answer, judge score and reasoning, and a summary of retrieved chunks. This section enables the owner to verify judge accuracy and identify systematic issues.

Both files SHALL be written to the configured output directory.

#### Scenario: JSON report contains answer scoring fields

- **WHEN** the report generator processes a `SuiteResult` with answer-scored cases
- **THEN** the JSON output contains `answer`, `generation_timing_ms`, and judge review data for relevant case entries, with chunk summaries and other supplementary scorer payloads preserved in `details`

#### Scenario: Markdown report includes Manual Review Candidates

- **WHEN** the report generator produces a Markdown file for a suite with answer-scored cases
- **THEN** it contains a "Manual Review Candidates" section with worst performers per answer quality metric

#### Scenario: Manual review shows top-3 worst per metric

- **WHEN** a suite has more than 3 answer-scored cases for a metric
- **THEN** the Manual Review Candidates section lists the 3 lowest-scoring cases for that metric

#### Scenario: Manual review includes answer and reasoning

- **WHEN** a case appears in the Manual Review Candidates section
- **THEN** it displays the case ID, query, twin's full answer, judge score, judge reasoning, and a chunks summary

---

### Requirement: CLI entry point

The CLI entry point (`run_evals.py`) SHALL use `argparse` with these flags:

- `--base-url`: string, default `http://localhost:8000`; overrides the eval API base URL.
- `--admin-key`: string, default from `PROXYMIND_ADMIN_API_KEY`; supplies the admin auth token.
- `--dataset`: file or directory path, default `evals/datasets/`; selects dataset source.
- `--tag`: repeatable string flag; filters cases by tag.
- `--top-n`: integer, default `5`, valid range `1..50`; overrides retrieval top_n.
- `--output-dir`: path, default `evals/reports/`; selects report output directory.
- `--snapshot-id`: UUID, optional; overrides dataset snapshot_id.
- `--judge-model`: string, optional; explicit judge model override.
- `--persona-path`: path, optional; explicit persona fixture path for persona fidelity scoring.

Runtime wiring:
The CLI SHALL load datasets, resolve the judge model, construct `EvalJudge`, wire answer scorers alongside retrieval scorers, run the suite runner, and generate reports.

Precedence and fallback rules:

- `--judge-model` SHALL take precedence over `EVAL_JUDGE_MODEL`.
- If neither `--judge-model` nor `EVAL_JUDGE_MODEL` is set, runtime wiring MAY use `LLM_MODEL` as the final fallback when constructing `EvalJudge`.
- If `--persona-path` is not provided and the default runtime `persona/` directory lacks a complete fixture (`IDENTITY.md`, `SOUL.md`, `BEHAVIOR.md`), the CLI SHALL fall back to `evals/seed_persona/` for reproducible seed runs.

Error handling:

- If dataset loading fails, the CLI SHALL print a human-readable error to stderr and exit with code `1`.
- If answer-scoring cases exist but no judge model can be resolved from `--judge-model`, `EVAL_JUDGE_MODEL`, or `LLM_MODEL`, the CLI SHALL fail fast with a human-readable error and exit with code `1`.

#### Scenario: CLI with default arguments

- **WHEN** the CLI is invoked with no arguments
- **THEN** it uses `base_url=http://localhost:8000`, `top_n=5`, `dataset=evals/datasets/`, `output_dir=evals/reports/`, and `persona_path=persona/`

#### Scenario: CLI with judge-model override

- **WHEN** the CLI is invoked with `--judge-model gemini-2.0-flash`
- **THEN** the EvalJudge uses `gemini-2.0-flash` as the model, overriding `EVAL_JUDGE_MODEL` env var

#### Scenario: CLI with persona-path override

- **WHEN** the CLI is invoked with `--persona-path evals/seed_persona/`
- **THEN** the persona fidelity scorer loads persona files from `evals/seed_persona/`

#### Scenario: CLI wires answer scorers

- **WHEN** the CLI runs a suite containing cases with `answer_expectations`
- **THEN** the runner applies answer quality scorers (groundedness, citation_accuracy, persona_fidelity, refusal_quality) as appropriate

---

## ADDED Requirements

### Requirement: AnswerExpectations model

An `AnswerExpectations` Pydantic model SHALL be added with the following fields:

- `should_refuse` (bool, default `False`) -- whether the twin should refuse to answer
- `expected_citations` (list of UUIDs, default empty list) -- source_ids expected in citations
- `persona_tags` (list of strings, default empty list) -- persona aspects to verify
- `groundedness_notes` (string, default `""`) -- notes on expected groundedness

The model SHALL be optional on `EvalCase` (type `AnswerExpectations | None`, default `None`).

#### Scenario: AnswerExpectations with all fields

- **WHEN** an `AnswerExpectations` is created with `should_refuse=True`, `expected_citations=[uuid1]`, `persona_tags=["expert"]`, `groundedness_notes="Should cite chapter 3"`
- **THEN** all fields are populated correctly

#### Scenario: AnswerExpectations with defaults

- **WHEN** an `AnswerExpectations` is created with no arguments
- **THEN** `should_refuse` is `False`, `expected_citations` is `[]`, `persona_tags` is `[]`, and `groundedness_notes` is `""`

---

### Requirement: GenerationResult model

A `GenerationResult` Pydantic model SHALL be added with the following fields:

- `answer` (string) -- the twin's full response text
- `citations` (list of dicts) -- JSON-serialized citation dicts from the HTTP response
- `retrieved_chunks` (list of `ReturnedChunk`) -- chunks fed to the LLM
- `rewritten_query` (string) -- reformulated or original query
- `timing_ms` (float) -- total generation time in milliseconds
- `model` (string) -- model used for generation

The model SHALL be used by `EvalClient.generate()` and by answer quality scorers.

#### Scenario: GenerationResult from endpoint response

- **WHEN** a `GenerationResult` is created from a valid `/eval/generate` response
- **THEN** all fields are populated and `retrieved_chunks` contains `ReturnedChunk` objects

---

### Requirement: EvalConfig extensions

`EvalConfig` SHALL be extended with the following fields:

- `judge_model` (string or None, default `None`) -- stores the explicitly configured judge model from `EVAL_JUDGE_MODEL` and/or `--judge-model`; runtime wiring that constructs `EvalJudge` may fall back to `LLM_MODEL` when this value is `None`
- `persona_path` (string, default `"persona/"`) -- path to persona files for persona fidelity scorer
- `seed_persona_path` (string, default `"evals/seed_persona/"`) -- fallback path for seed evals
- `thresholds` (dict mapping metric name to `ThresholdZone`) -- threshold zones for compare CLI, initialized from `DEFAULT_THRESHOLDS`

#### Scenario: EvalConfig reads judge_model from env

- **WHEN** `EVAL_JUDGE_MODEL=gemini-2.0-flash` is set in the environment
- **THEN** `EvalConfig.judge_model` equals `"gemini-2.0-flash"`

#### Scenario: EvalConfig judge_model defaults to None

- **WHEN** `EVAL_JUDGE_MODEL` is not set
- **THEN** `EvalConfig.judge_model` is `None` and runtime wiring may use `LLM_MODEL` when constructing `EvalJudge`

---

### Requirement: Distinct scorer protocols and factories

The framework SHALL distinguish two scorer contracts:

- `RetrievalScorer`: the retrieval-scoring protocol used for `RetrievalResult` inputs and returned by `default_scorers()`.
- `AnswerScorer`: the answer-quality scoring protocol used for `GenerationResult` inputs and returned by `default_answer_scorers()`.

The runner SHALL use `RetrievalScorer` instances for retrieval cases and `AnswerScorer` instances for generation cases. `default_answer_scorers()` SHALL return the four answer-quality scorer instances: groundedness, citation_accuracy, persona_fidelity, and refusal_quality. `default_scorers()` SHALL remain the retrieval-scorer factory.

#### Scenario: default_answer_scorers returns four scorers

- **WHEN** `default_answer_scorers()` is called
- **THEN** it returns a list containing scorers with names `"groundedness"`, `"citation_accuracy"`, `"persona_fidelity"`, and `"refusal_quality"`

#### Scenario: Answer scorers are compatible with SuiteRunner

- **WHEN** answer scorers are passed to `SuiteRunner`
- **THEN** the runner can invoke them for cases with `answer_expectations`

#### Scenario: Retrieval scorers are used only for retrieval results

- **WHEN** retrieval scorers are passed to `SuiteRunner`
- **THEN** the runner invokes them only on `RetrievalResult` flows and not on `GenerationResult` flows

---

### Requirement: EvalClient generate method

`EvalClient` SHALL provide a new `async generate(query: str, snapshot_id: UUID) -> GenerationResult` method. The method SHALL POST to `/api/admin/eval/generate` with the query and snapshot_id, and return a `GenerationResult` parsed from the JSON response. The method is single-turn only -- no session_id is used.

#### Scenario: Generate returns GenerationResult

- **WHEN** `EvalClient.generate(query="What is chapter 3 about?", snapshot_id=uuid)` is called
- **THEN** it returns a `GenerationResult` with answer, citations, retrieved_chunks, rewritten_query, timing_ms, and model

#### Scenario: Generate raises EvalClientError on HTTP error

- **WHEN** the `/eval/generate` endpoint returns an error status
- **THEN** `EvalClient.generate()` SHALL raise `EvalClientError`

---

### Requirement: Stable behavior requiring tests

The following stable behaviors MUST be covered by unit tests before the change is archived, in addition to the S8-01 test requirements:

1. **Answer quality scorers** -- All four scorers (groundedness, citation_accuracy, persona_fidelity, refusal_quality) MUST have unit tests verifying judge prompt construction, response parsing (valid and malformed), score normalization, and conditional execution (persona_fidelity skipped without persona_tags, refusal_quality skipped when should_refuse=False).
2. **Judge response parsing** -- Unit tests MUST verify regex parsing of `"Score: N\nReasoning: ..."` format, handling of malformed responses (score=0.0, error in details), and out-of-range scores.
3. **Runner scorer auto-selection** -- Unit tests MUST verify that the runner selects retrieval scorers for cases with `expected` only, answer scorers for cases with `answer_expectations` only, and all applicable scorers for cases with both.
4. **Compare CLI** -- Unit tests MUST verify delta computation, zone classification for all three zones, exit code 0 with no RED, exit code 1 with RED, and handling of new metrics not present in baseline.
5. **Dataset loader extension** -- Unit tests MUST verify that `answer_expectations` fields are correctly parsed, that `expected` defaults to an empty list, and that cases with only `answer_expectations` are valid.
6. **Report manual review section** -- Unit tests MUST verify that the Markdown report contains a Manual Review Candidates section with worst performers, including answer text and judge reasoning.

All unit tests MUST mock the LLM judge -- no external provider dependency in CI.

#### Scenario: Answer scorer unit tests exist and pass

- **WHEN** `pytest tests/unit/test_eval_answer_scorers.py` is run
- **THEN** all scorer tests pass covering prompt construction, response parsing, normalization, and conditional execution

#### Scenario: Compare CLI unit tests exist and pass

- **WHEN** `pytest tests/unit/test_eval_compare.py` is run
- **THEN** all compare tests pass covering delta computation, zone classification, and exit codes

#### Scenario: Runner auto-selection unit tests exist and pass

- **WHEN** `pytest tests/unit/test_eval_runner.py` is run
- **THEN** tests verify correct scorer selection based on case fields
