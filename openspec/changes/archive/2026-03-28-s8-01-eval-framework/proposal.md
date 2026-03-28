## Story

**S8-01: Eval framework**
- **Outcome:** eval suite can be run and produces a report
- **Verification:** `run-evals` → report with metrics
- **Tasks:** dataset format, eval runner, report generator
- **Stable behavior requiring tests:** scorer algorithms (Precision@K, Recall@K, MRR), dataset loader, report generator, admin eval endpoint

## Why

ProxyMind has two testing tracks defined in the architecture: deterministic CI tests and quality evals on real models. CI tests exist and block deployment. Quality evals do not exist yet — there is no way to measure retrieval quality (Precision@K, Recall@K, MRR) or establish baselines for answer quality metrics. Without evals, upgrade decisions (chunk enrichment, parent-child chunking, BGE-M3 — Phase 9) would be guesswork instead of data-driven.

## What Changes

- New standalone eval framework in `backend/evals/` — CLI-based, separate from CI
- YAML dataset format for eval cases with ground truth (source_id + text substring matching)
- Pluggable scorer pipeline: Precision@K, Recall@K, MRR (retrieval metrics); extension point for LLM-as-judge scorers in S8-02
- Suite runner that exercises the system end-to-end via HTTP API
- Report generator producing JSON (machine-readable) + Markdown (human-readable) reports
- New admin eval endpoint (`POST /api/admin/eval/retrieve`) exposing raw retrieval results for scoring
- New dependency: `pyyaml`

## Capabilities

### New Capabilities
- `eval-framework`: Eval runner infrastructure — dataset format, YAML loader, suite runner, scorer protocol, report generator, CLI entry point
- `eval-retrieval-endpoint`: Admin API endpoint for raw retrieval results used by eval scorers

### Modified Capabilities
_None — this change introduces new tooling without modifying existing behavior._

## Impact

- **Code:** new `backend/evals/` package (not part of runtime image — dev/test tool only); new `backend/app/api/admin_eval.py` + `eval_schemas.py`; router registration in `backend/app/main.py`
- **API:** new `POST /api/admin/eval/retrieve` (admin-authenticated)
- **Dependencies:** `pyyaml>=6.0.2` added to `backend/pyproject.toml`
- **Infrastructure:** no changes — evals run in `backend-test` container against a running stack
- **Existing behavior:** no modifications to existing services, endpoints, or tests
