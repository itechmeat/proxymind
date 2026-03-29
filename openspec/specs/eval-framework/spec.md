# eval-framework

Eval runner infrastructure: YAML dataset format, Pydantic-validated loader, pluggable scorer protocol, suite runner, report generator, and CLI entry point. Runs separately from CI in the `backend-test` container against a live stack via HTTP API.

## ADDED Requirements

### Requirement: Dataset format

The eval dataset format SHALL use YAML files. Each file SHALL describe one `EvalSuite` containing a `suite` name (string, min_length=1), an optional `description` (string), a `snapshot_id` (UUID), and a `cases` list (min_length=1). Each `EvalCase` SHALL have an `id` (string, min_length=1), a `query` (string, min_length=1), an `expected` list of `ExpectedChunk` entries (min_length=1), and optional `tags` (list of strings, defaults to empty). Each `ExpectedChunk` SHALL have a `source_id` (UUID) and a `contains` field (string, min_length=1). Case IDs within a suite MUST be unique; duplicate IDs SHALL cause a validation error. All models SHALL be Pydantic `BaseModel` subclasses.

#### Scenario: Valid suite with single case parses successfully

- **WHEN** a YAML file with a valid suite name, snapshot_id, and one case with id, query, and at least one expected chunk is loaded
- **THEN** the resulting `EvalSuite` object contains the correct suite name, snapshot_id, and one `EvalCase` with matching fields

#### Scenario: Empty cases list rejected

- **WHEN** a YAML file defines a suite with an empty `cases` list
- **THEN** Pydantic validation SHALL raise a `ValidationError`

#### Scenario: Duplicate case IDs rejected

- **WHEN** a suite contains two cases with the same `id`
- **THEN** Pydantic validation SHALL raise a `ValidationError` with a message matching "Duplicate case id"

#### Scenario: Case with tags preserved

- **WHEN** a case includes `tags: ["retrieval", "contact"]`
- **THEN** the parsed `EvalCase.tags` equals `["retrieval", "contact"]`

#### Scenario: Case without tags defaults to empty list

- **WHEN** a case does not specify `tags`
- **THEN** the parsed `EvalCase.tags` equals `[]`

---

### Requirement: Dataset loader

The dataset loader SHALL accept a filesystem path (file or directory). When given a single `.yaml` or `.yml` file, it SHALL parse and validate that file into an `EvalSuite`. When given a directory, it SHALL discover all `.yaml` and `.yml` files in that directory, sort the combined file list deterministically, and return a list of `EvalSuite` objects. Validation SHALL use the Pydantic models; invalid files SHALL raise a `ValueError`. A nonexistent path SHALL raise `FileNotFoundError`. The loader SHALL support optional tag filtering: when tags are provided, only cases matching at least one tag are retained; suites with zero remaining cases after filtering SHALL be dropped from the result. The loader SHALL support an optional `snapshot_id` override (UUID type) that replaces the `snapshot_id` in all loaded suites.

#### Scenario: Load single YAML file

- **WHEN** `load_datasets` is called with a path to a valid YAML file
- **THEN** a list containing exactly one `EvalSuite` is returned with the correct suite name and cases

#### Scenario: Load directory with multiple YAML files

- **WHEN** `load_datasets` is called with a directory containing two valid YAML files
- **THEN** a list of two `EvalSuite` objects is returned

#### Scenario: Directory discovery order is deterministic across extensions

- **WHEN** `load_datasets` is called with a directory containing both `.yaml` and `.yml` files
- **THEN** files are processed in one combined sorted order rather than by extension bucket

#### Scenario: Nonexistent path raises error

- **WHEN** `load_datasets` is called with a path that does not exist
- **THEN** a `FileNotFoundError` is raised

#### Scenario: Invalid YAML raises validation error

- **WHEN** a YAML file fails Pydantic validation (e.g., `cases` is not a list)
- **THEN** a `ValueError` is raised with a message matching "validation" (case-insensitive)

#### Scenario: Tag filtering retains matching cases

- **WHEN** `load_datasets` is called with `tags=["retrieval"]` and the suite has cases tagged "retrieval"
- **THEN** only cases with the "retrieval" tag are included in the returned suite

#### Scenario: Tag filtering drops suites with zero matching cases

- **WHEN** `load_datasets` is called with `tags=["nonexistent"]` and no cases match
- **THEN** the suite is dropped and the returned list is empty

#### Scenario: Snapshot ID override replaces suite snapshot_id

- **WHEN** `load_datasets` is called with a `snapshot_id` override UUID
- **THEN** all returned suites have their `snapshot_id` set to the override value

---

### Requirement: Scorer protocol

A `Scorer` protocol SHALL define a `name` property (returning `str`) and a `score` method accepting an `EvalCase` and a `RetrievalResult`, returning a `ScorerOutput`. `ScorerOutput` SHALL be a Pydantic model with a `score` field (float, 0.0 to 1.0) and a `details` dict. Chunk matching logic across all retrieval scorers SHALL be case-insensitive: a returned chunk matches an expected entry when `returned.source_id == expected.source_id` AND `expected.contains` is found as a substring in `returned.text` (case-insensitive comparison). A `default_scorers()` factory function SHALL return a list of all three retrieval scorer instances. The runner iterates the list; each scorer's `name` property provides the key for result aggregation. This list-based approach is sufficient for S8-01; a dict registry can be introduced in S8-02 if runtime lookup by name is needed.

#### Scenario: ScorerOutput accepts valid score and details

- **WHEN** a `ScorerOutput` is created with `score=0.75` and `details={"matched": 3}`
- **THEN** the object is valid with `score == 0.75`

#### Scenario: ScorerOutput rejects score above 1.0

- **WHEN** a `ScorerOutput` is created with `score=1.5`
- **THEN** Pydantic validation SHALL raise a `ValidationError`

#### Scenario: Case-insensitive matching

- **WHEN** a returned chunk has `text="The Refund Policy is..."` and the expected entry has `contains="refund policy"`
- **THEN** the chunk SHALL be considered a match

#### Scenario: Default scorer factory returns three scorers

- **WHEN** `default_scorers()` is called
- **THEN** it returns a list containing scorers with names `"precision_at_k"`, `"recall_at_k"`, and `"mrr"`

---

### Requirement: PrecisionAtK scorer

The `PrecisionAtK` scorer SHALL compute the ratio of matched chunks to total returned chunks (K). The score SHALL equal `matched / K` where K is the number of returned chunks. If the retrieval result contains zero chunks, the score SHALL be `0.0`. The scorer name SHALL be `"precision_at_k"`.

#### Scenario: All returned chunks are relevant

- **WHEN** 3 chunks are returned and all 3 match expected entries
- **THEN** the score is `1.0`

#### Scenario: Some returned chunks are relevant

- **WHEN** 5 chunks are returned and 2 match expected entries
- **THEN** the score is `0.4`

#### Scenario: No returned chunks are relevant

- **WHEN** 3 chunks are returned and none match expected entries
- **THEN** the score is `0.0`

#### Scenario: Empty retrieval result

- **WHEN** 0 chunks are returned
- **THEN** the score is `0.0`

---

### Requirement: RecallAtK scorer

The `RecallAtK` scorer SHALL compute the ratio of found expected chunks to total expected chunks. The score SHALL equal `found / total_expected`. If the retrieval result contains zero chunks, the score SHALL be `0.0`. The scorer name SHALL be `"recall_at_k"`.

#### Scenario: All expected chunks found

- **WHEN** 2 expected chunks are defined and both are found in the top-K results
- **THEN** the score is `1.0`

#### Scenario: Some expected chunks found

- **WHEN** 3 expected chunks are defined and 1 is found in the top-K results
- **THEN** the score is approximately `0.333`

#### Scenario: No expected chunks found

- **WHEN** 2 expected chunks are defined and none are found in the top-K results
- **THEN** the score is `0.0`

#### Scenario: Empty retrieval result

- **WHEN** 0 chunks are returned
- **THEN** the score is `0.0`

---

### Requirement: MRR scorer

The `MRR` (Mean Reciprocal Rank) scorer SHALL compute `1 / rank` where `rank` is the 1-based position of the first relevant chunk in the retrieval result. If no relevant chunk is found, the score SHALL be `0.0`. The scorer name SHALL be `"mrr"`.

#### Scenario: First chunk is relevant

- **WHEN** the first returned chunk (rank 1) matches an expected entry
- **THEN** the score is `1.0`

#### Scenario: Third chunk is first relevant

- **WHEN** the third returned chunk (rank 3) is the first match
- **THEN** the score is approximately `0.333`

#### Scenario: No relevant chunk found

- **WHEN** no returned chunk matches any expected entry
- **THEN** the score is `0.0`

#### Scenario: Empty retrieval result

- **WHEN** 0 chunks are returned
- **THEN** the score is `0.0`

---

### Requirement: Suite runner

The `SuiteRunner` SHALL orchestrate eval execution: for each `EvalCase` in a loaded suite, it SHALL call the eval admin endpoint via an HTTP client (`EvalClient`) to retrieve chunks, then run all registered scorers against the result. Execution SHALL be sequential (one case at a time). The runner SHALL aggregate per-scorer metrics across all cases, computing mean, min, and max for each scorer. If an API call fails for a case, the runner SHALL mark that case with status `"error"` and the exception message, then continue with remaining cases. Error cases SHALL be counted separately in the result. The runner SHALL produce a `SuiteResult` containing suite name, timestamp, config summary, total_cases count, errors count, per-scorer `MetricSummary` (mean, min, max), and a list of per-case `CaseResult` objects.

#### Scenario: Successful run with all cases passing

- **WHEN** the runner processes a suite with 3 cases and all API calls succeed
- **THEN** the `SuiteResult` has `total_cases=3`, `errors=0`, and each case has `status="ok"` with scores from all scorers

#### Scenario: API error on one case does not stop the run

- **WHEN** the runner processes a suite with 3 cases and the second case's API call raises an exception
- **THEN** the `SuiteResult` has `total_cases=3`, `errors=1`, the second case has `status="error"` with an error message, and the other two cases have `status="ok"`

#### Scenario: Aggregated metrics computed correctly

- **WHEN** the runner completes a suite with cases scoring `[0.5, 1.0, 0.75]` for a scorer
- **THEN** the `MetricSummary` for that scorer has `mean=0.75`, `min=0.5`, `max=1.0`

#### Scenario: All cases fail

- **WHEN** every API call in the suite raises an exception
- **THEN** the `SuiteResult` has `errors` equal to `total_cases` and the summary dict is empty (no valid scores to aggregate)

---

### Requirement: Report generator

The report generator SHALL produce two output formats from a `SuiteResult`:

**JSON report** (`<suite>_<timestamp>.json`): SHALL contain top-level fields `suite`, `timestamp`, `config`, `total_cases`, `errors`, a `summary` dict with `MetricSummary` (mean, min, max) per scorer name, and a `cases` list with per-case `id`, `query`, `status`, `scores` (dict of scorer name to score float), `details`, and optional `error`.

**Markdown report** (`<suite>_<timestamp>.md`): SHALL contain a header with suite name, timestamp, and config summary; a summary table with one row per scorer showing mean, min, and max; a per-case results table with case ID, status, and per-scorer scores; and a worst performers section listing the bottom N cases per metric (configurable, default 3).

Both files SHALL be written to the configured output directory.

#### Scenario: JSON report contains required fields

- **WHEN** the report generator processes a valid `SuiteResult`
- **THEN** the JSON output contains `suite`, `timestamp`, `config`, `total_cases`, `errors`, `summary`, and `cases` keys

#### Scenario: JSON report summary has MetricSummary per scorer

- **WHEN** the suite result has scores for `precision_at_k` and `recall_at_k`
- **THEN** the JSON `summary` dict contains entries for both with `mean`, `min`, and `max` fields

#### Scenario: Markdown report includes summary table

- **WHEN** the report generator produces a Markdown file
- **THEN** it contains a table with columns for metric name, mean, min, and max

#### Scenario: Markdown report includes worst performers

- **WHEN** the suite has more than N cases
- **THEN** the Markdown report lists the bottom N cases per metric

#### Scenario: Reports written to output directory

- **WHEN** the report generator is called with an output directory
- **THEN** both JSON and Markdown files are created in that directory

---

### Requirement: CLI entry point

The CLI entry point (`run_evals.py`) SHALL use `argparse` with the following options: `--base-url` (default: `http://localhost:8000`), `--admin-key` (default: from `PROXYMIND_ADMIN_API_KEY` env var), `--dataset` (path to a YAML file or directory; default: `evals/datasets/`), `--tag` (repeatable, filters cases by tag), `--top-n` (override retrieval top_n; default: 5, range 1-50), `--output-dir` (report output directory; default: `evals/reports/`), and `--snapshot-id` (override snapshot_id, UUID type). The CLI SHALL load datasets, run the suite runner, and generate reports. If dataset loading fails because the path is missing or the YAML content is invalid, the CLI SHALL print a human-readable error to stderr and exit with code `1` instead of surfacing a traceback. It SHALL be executable as `python -m evals.run_evals` from the `backend/` directory and is designed to run inside the `backend-test` Docker container.

#### Scenario: CLI with default arguments

- **WHEN** the CLI is invoked with no arguments
- **THEN** it uses `base_url=http://localhost:8000`, `top_n=5`, `dataset=evals/datasets/`, and `output_dir=evals/reports/`

#### Scenario: CLI with tag filtering

- **WHEN** the CLI is invoked with `--tag retrieval --tag policy`
- **THEN** only cases tagged "retrieval" or "policy" are included in the run

#### Scenario: CLI handles dataset loading failures cleanly

- **WHEN** dataset loading raises `FileNotFoundError` or `ValueError`
- **THEN** the CLI prints a concise error message to stderr and exits with code `1`

#### Scenario: CLI with snapshot-id override

- **WHEN** the CLI is invoked with `--snapshot-id <uuid>`
- **THEN** all suites use the provided UUID as their snapshot_id, overriding the value in the YAML files

#### Scenario: CLI with custom output directory

- **WHEN** the CLI is invoked with `--output-dir /tmp/eval-results`
- **THEN** reports are written to `/tmp/eval-results/`

---

### Requirement: Eval retrieval API contract for EvalClient and SuiteRunner

`EvalClient` and `SuiteRunner` SHALL rely on a dedicated admin retrieval endpoint at `POST /api/admin/eval/retrieve`. The request JSON SHALL contain `query` (string, min_length=1), `snapshot_id` (UUID string, required), and `top_n` (integer, default 5, allowed range 1-50). The response JSON SHALL contain `chunks` (array) and `timing_ms` (float). Each chunk item SHALL contain `chunk_id`, `source_id`, `text`, `score`, and `rank`. The endpoint SHALL require `Authorization: Bearer <admin-api-key>` and reject missing or invalid credentials with HTTP 401. Validation failures for missing query, invalid UUID syntax, or out-of-range `top_n` SHALL return HTTP 422. If `RetrievalService.search()` fails, the endpoint SHALL return HTTP 500 with a JSON payload containing an `error` field. Ranking SHALL preserve the order returned by `RetrievalService.search()`, with ranks assigned sequentially starting at 1; no additional sorting or tie-breaking is applied in the endpoint layer. The endpoint validates `snapshot_id` syntactically only; it does not perform a separate existence lookup, so a syntactically valid UUID with no indexed results SHALL yield an empty `chunks` list rather than HTTP 404.

#### Scenario: EvalClient submits a valid retrieval request

- **WHEN** `EvalClient` sends a valid request for `query`, `snapshot_id`, and `top_n`
- **THEN** the endpoint returns a JSON response consumable by `SuiteRunner` with `chunks` and `timing_ms`

#### Scenario: Validation errors are surfaced to callers

- **WHEN** the request has a missing query, invalid `snapshot_id`, or `top_n` outside 1-50
- **THEN** the endpoint returns HTTP 422 and `EvalClient` treats the response as an error

#### Scenario: Retrieval failure is surfaced as a 500 error payload

- **WHEN** `RetrievalService.search()` fails while serving an eval request
- **THEN** the endpoint returns HTTP 500 with a JSON body containing an `error` field and no `timing_ms`

---

### Requirement: Stable behavior requiring tests

The following stable behaviors MUST be covered by unit tests before the change is archived:

1. **Scorer algorithms** -- `PrecisionAtK`, `RecallAtK`, and `MRR` scorers MUST have unit tests verifying correct score computation for matching, partial matching, no matching, and empty result scenarios, including case-insensitive substring matching.
2. **Dataset loader** -- `load_datasets` MUST have unit tests for single file loading, directory loading, nonexistent path error, invalid YAML error, tag filtering (matching and no-match drop), and snapshot_id override.
3. **Report generator** -- The report generator MUST have unit tests verifying JSON output structure (required fields, MetricSummary per scorer) and Markdown output content (summary table, per-case table, worst performers section).
4. **Admin eval endpoint** -- `POST /api/admin/eval/retrieve` MUST have unit tests verifying successful retrieval, admin authentication requirement, request validation (missing query, invalid snapshot_id, top_n out of range), response structure, empty results, fewer results than requested `top_n`, and service failure mapping to HTTP 500 with a JSON `error` payload.

#### Scenario: Scorer unit tests exist and pass

- **WHEN** `pytest tests/unit/test_eval_scorers.py` is run
- **THEN** all scorer tests pass covering the four result scenarios per scorer

#### Scenario: Loader unit tests exist and pass

- **WHEN** `pytest tests/unit/test_eval_loader.py` is run
- **THEN** all loader tests pass covering file, directory, error, tag, and override scenarios

#### Scenario: Report unit tests exist and pass

- **WHEN** `pytest tests/unit/test_eval_report.py` is run
- **THEN** all report tests pass covering JSON fields, Markdown tables, and file creation

#### Scenario: Admin eval endpoint unit tests exist and pass

- **WHEN** `pytest tests/unit/test_admin_eval_api.py` is run
- **THEN** all endpoint tests pass covering auth, validation, response structure, and retrieval behavior
