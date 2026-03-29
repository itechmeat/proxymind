# S8-01: Eval Framework — Design Spec

## Story

**S8-01: Eval framework**
Test harness, dataset format, suite runner, report generation. Separate from CI.

- **Outcome:** eval suite can be run and produces a report
- **Verification:** `run-evals` → report with metrics
- **Tasks:** dataset format, eval runner, report generator

## Design Decisions

| Question | Decision | Rationale |
|----------|----------|-----------|
| Entry point | CLI script (`run_evals.py`) | Evals are not tests — they produce metrics and reports, not pass/fail. Separate entry point reinforces the CI/evals boundary defined in the architecture. CLI is easier to extend for Gemini Batch API in S8-02. |
| Dataset format | YAML | Eval datasets contain multiline prompts, expected answers, and persona descriptions. YAML is human-readable, supports comments for case annotation, and is natural for multiline content. JSON would require escaping. |
| Dataset storage | In-repo (`backend/evals/datasets/`) | Datasets are small (dozens of cases) at this stage. Git versioning ensures full reproducibility. Can be externalized later if needed (YAGNI). |
| Report format | JSON + Markdown | JSON for machine consumption (comparison, trends). Markdown for human review in terminal or GitHub. Markdown is auto-generated from JSON in a single pass. |
| System interaction | HTTP API (end-to-end) | Evals must assess the system as users see it. End-to-end testing catches integration bugs. Docker compose is already available. Clear separation between eval framework and SUT. |
| Retrieval debug data | Dedicated admin eval endpoint | Keeps chat API clean — no debug parameters. Eval endpoint returns exactly what metrics need (ranked chunks with text). Protected by existing admin API key (S7-01). |
| LLM-as-judge | Deferred to S8-02 | S8-01 scope is infrastructure: dataset format, runner, report generator. S8-02 defines eval prompts, scoring rubrics, and human review process. S8-01 provides extension point via scorer protocol. |
| Ground truth format | source_id + text substring | Stable across reindexing (source_id is permanent, text substring survives re-chunking). More precise than source_id alone. No dependency on volatile chunk_ids. Easy to verify manually. |

## Approach

**Pluggable scorer pipeline** — four components with clear responsibilities:

1. **Dataset loader** — parses YAML, validates schema with Pydantic models
2. **Suite runner** — orchestrates API calls per eval case, collects raw results
3. **Scorer registry** — set of scorers implementing a common protocol. S8-01 ships retrieval scorers; S8-02 adds LLM-judge scorers without changing the runner.
4. **Report generator** — transforms scored results into JSON + Markdown

Why not monolithic: S8-02 adds LLM-judge scorers — pluggable architecture avoids refactoring.
Why not pytest-based: evals produce metrics, not pass/fail. Separate entry point matches the project's architectural decision to split CI tests from quality evals.

## Directory Structure

```
backend/
├── evals/
│   ├── __init__.py
│   ├── run_evals.py              # CLI entry point (argparse)
│   ├── config.py                 # EvalConfig (Pydantic): base_url, admin_key, top_k, output_dir
│   ├── loader.py                 # YAML dataset loader + Pydantic validation
│   ├── runner.py                 # SuiteRunner: orchestrates API calls, collects raw results
│   ├── client.py                 # EvalClient: async HTTP client for eval admin endpoints
│   ├── report.py                 # ReportGenerator: JSON + Markdown output
│   ├── scorers/
│   │   ├── __init__.py           # Scorer protocol + registry
│   │   ├── precision.py          # PrecisionAtK
│   │   ├── recall.py             # RecallAtK
│   │   └── mrr.py                # MRR
│   ├── datasets/
│   │   └── retrieval_basic.yaml  # Seed dataset (demo/smoke)
│   └── reports/                  # Generated reports (gitignored)
│       └── .gitkeep
├── app/
│   └── api/
│       └── admin_eval.py         # POST /api/admin/eval/retrieve
```

- `evals/` is top-level in backend, not inside `app/` — it is a tool, not part of the application
- `evals/reports/` is gitignored — reports are local artifacts
- `evals/datasets/` is versioned in git
- One new API file `app/api/admin_eval.py` for the eval endpoint (follows existing pattern: no `v1` prefix)

## Dataset Schema

YAML file describes one eval suite:

```yaml
suite: retrieval_basic
description: "Basic retrieval quality checks"
snapshot_id: "uuid-of-active-snapshot"
cases:
  - id: "ret-001"
    query: "What is the company's refund policy?"
    expected:
      - source_id: "uuid-of-refund-doc"
        contains: "30-day money-back guarantee"
      - source_id: "uuid-of-terms-doc"
        contains: "refund request"
    tags: ["retrieval", "policy"]
  - id: "ret-002"
    query: "How to contact support?"
    expected:
      - source_id: "uuid-of-support-doc"
        contains: "support@example.com"
    tags: ["retrieval", "contact"]
```

Pydantic models for validation:

- **`EvalSuite`** — suite name, description, snapshot_id (UUID), list of `EvalCase`
- **`EvalCase`** — id (unique string), query (string), list of `ExpectedChunk`, tags (optional list of strings)
- **`ExpectedChunk`** — source_id (UUID), contains (string)

Tags enable filtered runs: `run_evals.py --tag retrieval`.

## Scorer Protocol

```
Protocol Scorer:
    name: str
    score(case: EvalCase, result: RetrievalResult) -> ScorerOutput
```

- **`RetrievalResult`** — list of `ReturnedChunk` (chunk_id, source_id, score, text, rank)
- **`ScorerOutput`** — `{score: float, details: dict}`

### Retrieval Scorers (S8-01)

**PrecisionAtK** — of the top-K returned chunks, how many match an expected entry (source_id matches AND text contains the substring). `score = matched / K`.

**RecallAtK** — of all expected chunks, how many are found in the top-K results. `score = found / total_expected`.

**MRR (Mean Reciprocal Rank)** — `1 / rank_of_first_relevant_chunk`. If no relevant chunk is found, score is 0.

Matching logic: a returned chunk matches an expected entry when `returned.source_id == expected.source_id` AND `expected.contains in returned.text` (case-insensitive).

### Scorer Registry

Simple dict `{name: scorer_instance}`. Default registry includes all three retrieval scorers. In S8-02, LLM-judge scorers are added through the same protocol — no runner changes needed.

## Admin Eval Endpoint

`POST /api/admin/eval/retrieve`

**Request:**
```json
{
  "query": "What is the refund policy?",
  "snapshot_id": "550e8400-e29b-41d4-a716-446655440000",
  "top_n": 5
}
```

**Response:**
```json
{
  "chunks": [
    {
      "chunk_id": "uuid",
      "source_id": "uuid",
      "score": 0.87,
      "text": "Full chunk text content for matching...",
      "rank": 1
    }
  ],
  "timing_ms": 142
}
```

- Protected by admin API key (existing middleware from S7-01)
- Calls `RetrievalService.search()` directly — no LLM, no chat session
- Returns full chunk text to enable `contains` matching in scorers
- `top_n` defaults to 5 (eval-specific default, independent of the backend's `retrieval_top_n` setting)

## Suite Runner

`SuiteRunner` orchestrates execution:

1. Loads YAML via `loader.py` → list of `EvalSuite`
2. For each `EvalCase`, calls `EvalClient.retrieve(query, snapshot_id, top_n)`
3. For each result, runs all registered scorers
4. Collects `SuiteResult` — per-case scores + aggregated metrics (mean, min, max per scorer)
5. Passes `SuiteResult` to `ReportGenerator`

Execution is sequential (one request at a time). Parallelization is not in scope for S8-01 — can be added later via `asyncio.gather` with a concurrency limit.

Error handling: if an API call fails for a case, the case is marked as `error` with the exception message. The runner continues with remaining cases. Errors are reported in the final output.

## Report Generator

### JSON Report (`reports/<suite>_<timestamp>.json`)

```json
{
  "suite": "retrieval_basic",
  "timestamp": "2026-03-28T14:30:00Z",
  "config": {
    "base_url": "http://localhost:8000",
    "top_n": 5,
    "snapshot_id": "550e8400-e29b-41d4-a716-446655440000"
  },
  "total_cases": 10,
  "errors": 0,
  "summary": {
    "precision_at_k": { "mean": 0.72, "min": 0.4, "max": 1.0 },
    "recall_at_k": { "mean": 0.85, "min": 0.5, "max": 1.0 },
    "mrr": { "mean": 0.91, "min": 0.33, "max": 1.0 }
  },
  "cases": [
    {
      "id": "ret-001",
      "query": "What is the company's refund policy?",
      "status": "ok",
      "scores": {
        "precision_at_k": 0.8,
        "recall_at_k": 1.0,
        "mrr": 1.0
      },
      "details": { "...scorer-specific details..." }
    }
  ]
}
```

### Markdown Report (`reports/<suite>_<timestamp>.md`)

Contains:
- Header with timestamp, suite name, config summary
- Summary table with aggregated metrics (mean, min, max)
- Per-case table with scores and status flags (low precision, missed recall)
- Worst performers section (bottom 3 per metric)

## CLI Entry Point

```
python -m evals.run_evals [OPTIONS]

Options:
  --base-url       API base URL (default: http://localhost:8000)
  --admin-key      Admin API key (default: from PROXYMIND_ADMIN_API_KEY env)
  --dataset        Path to specific YAML file (default: all in datasets/)
  --tag            Filter cases by tag (repeatable)
  --top-n          Override retrieval top_n (default: from dataset or 5)
  --output-dir     Report output directory (default: evals/reports/)
  --snapshot-id    Override snapshot_id (default: from dataset)
```

Run in Docker: `docker compose run --rm backend-test python -m evals.run_evals`

## Dependencies

New Python dependencies required:
- `pyyaml` — YAML parsing for dataset files

No other new dependencies. `httpx` (already in dev dependencies), `pydantic` (already a dependency), and stdlib modules cover the rest.

## Out of Scope for S8-01

- LLM-as-judge scorers (S8-02)
- Answer metrics: Groundedness, Citation accuracy, Persona fidelity, Refusal quality (S8-02)
- Eval via chat API with SSE streaming (S8-02, for answer evals)
- Parallel eval case execution
- Comparison reports (diff between two runs)
- Gemini Batch API for bulk eval
- CI integration / automated scheduling
- Threshold-based pass/fail (evals produce metrics, not verdicts)
