## Story

**S8-02: Eval runs + upgrade decision** (Phase 8: Evals and Quality)

Verification criteria from plan:
- Report with retrieval + answer metrics
- Baseline recorded
- Decision document supported by data

Stable behavior to cover with tests: all new scorers, runner extension, compare CLI, report extension, `/eval/generate` endpoint.

## Why

The eval framework (S8-01) provides the scaffolding — dataset format, retrieval scorers, runner, and reports — but no actual eval runs, no answer quality measurement, and no data to inform RAG upgrade decisions. Without baseline metrics for retrieval quality and answer quality (groundedness, citation accuracy, persona fidelity, refusal quality), Phase 9 upgrade decisions (chunk enrichment, parent-child chunking, BGE-M3 fallback) would be based on intuition rather than data.

## What Changes

- Add `/api/admin/eval/generate` endpoint — debug-mode generation (JSON, no SSE) exposing intermediate artifacts (retrieved chunks, rewritten query) for answer quality scoring
- Add 4 LLM-as-judge answer quality scorers: groundedness, citation accuracy, persona fidelity, refusal quality (1-5 rubric, normalized to 0-1)
- Add `EvalJudge` — LLM-as-judge wrapper over LiteLLM with configurable `EVAL_JUDGE_MODEL`
- Extend dataset format with optional `answer_expectations` section
- Extend `SuiteRunner` to auto-select retrieval vs answer quality scorers based on case fields
- Extend `ReportGenerator` with manual review candidates section (worst performers with full answer, judge reasoning, chunks summary)
- Add compare CLI (`python -m evals.compare`) for baseline vs current report with threshold zones (green/yellow/red)
- Add seed data: 3 knowledge documents, 3 persona files, 2 eval datasets (~15-20 cases)
- Add decision document template (`docs/eval-decision-v1.md`)

## Capabilities

### New Capabilities
- `eval-answer-scoring`: LLM-as-judge scorers for answer quality (groundedness, citation accuracy, persona fidelity, refusal quality), EvalJudge wrapper, scoring rubrics
- `eval-generate-endpoint`: Debug-mode generation endpoint exposing full pipeline artifacts for eval scoring
- `eval-baseline-comparison`: Compare CLI for baseline vs current reports with threshold zone classification
- `eval-seed-data`: Seed knowledge, persona, and eval datasets for reproducible baseline runs

### Modified Capabilities
- `eval-framework`: Extended dataset format (optional `answer_expectations`), runner scorer auto-selection, report manual review section, `run_evals.py` CLI args for judge model and persona path

## Impact

- **Backend API**: New endpoint `POST /api/admin/eval/generate` under admin auth
- **Eval framework** (`backend/evals/`): New scorers, extended models/config/runner/report/client/CLI
- **Dependencies**: No new dependencies — uses existing LiteLLM for judge calls
- **Configuration**: New optional env var `EVAL_JUDGE_MODEL`
- **Docs**: New `docs/eval-decision-v1.md` template
