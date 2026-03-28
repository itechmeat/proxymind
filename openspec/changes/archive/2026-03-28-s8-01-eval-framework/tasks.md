## 1. Project Setup

- [x] 1.1 Add `pyyaml>=6.0.2` to `backend/pyproject.toml` dependencies
- [x] 1.2 Add `backend/evals/reports/` and `!backend/evals/reports/.gitkeep` to `.gitignore`
- [x] 1.3 Create `backend/evals/reports/.gitkeep`

## 2. Pydantic Models and Config

- [x] 2.1 Write unit tests for dataset models (`ExpectedChunk`, `EvalCase`, `EvalSuite` with `min_length=1`, unique case IDs), result models (`ReturnedChunk`, `RetrievalResult`, `ScorerOutput`, `CaseResult`, `MetricSummary`, `SuiteResult`), and `EvalConfig` (defaults, `snapshot_id` as `UUID | None`)
- [x] 2.2 Create `backend/evals/__init__.py`, `backend/evals/models.py`, `backend/evals/config.py` — implement all models to pass tests

## 3. YAML Dataset Loader

- [x] 3.1 Write unit tests for loader: single file, directory, nonexistent path, invalid YAML, tag filtering (matching tags, no-match drops suite), snapshot_id override (`UUID` type)
- [x] 3.2 Implement `backend/evals/loader.py` — `load_datasets()` with Pydantic validation, tag filtering (skip suites with 0 matching cases), snapshot_id override

## 4. Scorer Protocol and Retrieval Scorers

- [x] 4.1 Write unit tests for all three scorers: `PrecisionAtK` (all relevant, half, none, empty, case-insensitive), `RecallAtK` (all found, partial, none, empty), `MRRScorer` (first/second/third relevant, none, empty)
- [x] 4.2 Create `backend/evals/scorers/__init__.py` — `Scorer` protocol, `chunk_matches_expected()` helper (case-insensitive source_id + contains), `default_scorers()` factory
- [x] 4.3 Implement `backend/evals/scorers/precision.py` — `PrecisionAtK` scorer
- [x] 4.4 Implement `backend/evals/scorers/recall.py` — `RecallAtK` scorer
- [x] 4.5 Implement `backend/evals/scorers/mrr.py` — `MRRScorer`

## 5. Admin Eval Endpoint

- [x] 5.1 Write unit tests for `POST /api/admin/eval/retrieve`: success with mock `RetrievalService`, custom `top_n`, empty query rejection (422), invalid `snapshot_id` rejection (422), `top_n` out of range rejection (422 for 0 and 51), missing Bearer auth rejection (401), invalid Bearer token rejection (401), response structure validation (all required fields present), field mapping (`text_content` → `text`, sequential 1-based ranks)
- [x] 5.2 Create `backend/app/api/eval_schemas.py` — `EvalRetrieveRequest`, `EvalChunkResponse`, `EvalRetrieveResponse`
- [x] 5.3 Create `backend/app/api/admin_eval.py` — router with `prefix="/api/admin/eval"`, `verify_admin_key` dependency, `POST /retrieve` endpoint calling `RetrievalService.search()`
- [x] 5.4 Register `admin_eval_router` in `backend/app/main.py`

## 6. Eval HTTP Client

- [x] 6.1 Write unit tests for `EvalClient.retrieve()`: success path (using `Mock` for response, `AsyncMock` for `http_client.post`), API error handling (`EvalClientError`)
- [x] 6.2 Implement `backend/evals/client.py` — `EvalClient` with async `retrieve()` method, `EvalClientError` exception

## 7. Suite Runner

- [x] 7.1 Write unit tests for `SuiteRunner.run()`: produces `SuiteResult` with aggregated metrics, handles per-case API errors (marks as "error", continues)
- [x] 7.2 Implement `backend/evals/runner.py` — `SuiteRunner` with sequential execution, per-scorer scoring, metric aggregation (mean, min, max)

## 8. Report Generator

- [x] 8.1 Write unit tests for `ReportGenerator`: JSON report structure (top-level `total_cases`/`errors`, `summary` with `MetricSummary`), Markdown report content (summary table, per-case table, worst performers), `generate()` produces both files, report with errors
- [x] 8.2 Implement `backend/evals/report.py` — `ReportGenerator` with `write_json()`, `write_markdown()`, `generate()`

## 9. CLI Entry Point and Seed Dataset

- [x] 9.1 Create `backend/evals/run_evals.py` — argparse CLI with `--base-url`, `--admin-key`, `--dataset`, `--tag`, `--top-n` (validated: range 1-50, argparse error on out-of-range), `--output-dir`, `--snapshot-id` (validated as UUID); async main orchestrating loader → runner → reporter
- [x] 9.2 Create `backend/evals/datasets/retrieval_basic.yaml` — seed dataset with placeholder UUIDs and comment pointing to `backend-test` container

## 10. Integration Verification

- [x] 10.1 Run all eval-related unit tests together and confirm they pass
- [x] 10.2 Run full backend test suite to confirm no regressions
- [x] 10.3 Run ruff lint on `evals/` and `app/api/admin_eval.py`, `app/api/eval_schemas.py`

`10.2` completed successfully in the long-lived `backend-test` service via `docker compose exec -T backend-test python -m pytest tests/ -q` after switching away from the broken one-off `docker compose run` path, whose `sleep infinity` entrypoint conflicts with command overrides.
