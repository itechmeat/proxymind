# S8-02: Eval Runs + Upgrade Decision — Design Spec

## Summary

Extend the eval framework (S8-01) to run retrieval and answer quality evaluations, record baselines, and produce a data-backed decision document for RAG upgrade paths (chunk enrichment, parent-child chunking, BGE-M3 fallback).

## Decisions Log

| # | Question | Chosen | Rationale |
|---|----------|--------|-----------|
| 1 | Answer quality eval architecture | New endpoint `/api/admin/eval/generate` | Isolated from SSE, exposes intermediate artifacts (retrieved chunks, rewritten query) needed for groundedness and citation scoring. Debug mode for the generation pipeline. |
| 2 | LLM-as-judge model | Configurable `EVAL_JUDGE_MODEL` with fallback to twin model | Flexibility without complexity. Owner can set a stronger model for accurate scoring. LiteLLM already in stack — any provider works. Zero-config default uses the twin's model. |
| 3 | Dataset format for answer quality | Unified format with optional sections | Natural extension of S8-01 YAML format. `answer_expectations` is optional — runner auto-selects scorers based on available fields. No duplication, one loader, one format. |
| 4 | Scoring rubric | 1-5 scale with level descriptions | Gold middle. LLMs score well on discrete scales with described levels. Normalized to 0.0-1.0 for aggregation via `(raw - 1) / 4`. Reproducible and explainable. |
| 5 | Dataset composition | Seed dataset (~15-20 cases) + docs for extension | Works out of box for baseline. Seed cases serve as format examples. Owner extends with real data. |
| 6 | Baseline persistence | JSON reports + baseline file + compare CLI | Minimal extension of existing infrastructure. Baseline = promoted report in `evals/baselines/`, committed to git. Compare CLI shows delta + zone coloring. YAGNI on DB storage. |
| 7 | Decision document format | Threshold zones (green/yellow/red) + qualitative override | Initial thresholds are orientation — calibrated after first run. Decision doc contains numbers + analysis + recommendations. Structured process with room for context. |

---

## 1. Architecture

### 1.1 Component Overview

```
                    S8-01 (existing)              S8-02 (new)
                    ─────────────────             ──────────────────
Endpoints:          /eval/retrieve          +     /eval/generate
Scorers:            precision, recall, mrr  +     groundedness, citation_accuracy,
                                                  persona_fidelity, refusal_quality
Datasets:           retrieval_basic.yaml    +     answer_quality.yaml, persona_and_refusal.yaml
                                                  + seed docs + seed persona
Runner:             SuiteRunner             →     extended: detect answer_expectations,
                                                  auto-select scorers
Report:             JSON + Markdown         +     compare CLI, baseline support,
                                                  manual review candidates section
Config:             EvalConfig              +     EVAL_JUDGE_MODEL, threshold zones
Artifacts:                                  +     baseline file, decision document
```

### 1.2 New Endpoint: `POST /api/admin/eval/generate`

**Purpose:** Debug-mode generation — same pipeline as chat, but JSON (no SSE) with exposed intermediate artifacts.

**Request:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | str | yes | User question |
| `snapshot_id` | UUID | yes | Knowledge snapshot for retrieval |

**Response:**

| Field | Type | Description |
|-------|------|-------------|
| `answer` | str | Full text of the twin's response |
| `citations` | list[dict] | Citations as JSON dicts (serialized from backend Citation dataclass) |
| `retrieved_chunks` | list[EvalChunk] | Chunks fed to LLM (text + source_id + score) |
| `rewritten_query` | str | Reformulated query (or original if rewriting skipped) |
| `timing_ms` | float | Total generation time |
| `model` | str | Model used for generation |

**Implementation:** Reuses existing retrieval service, query rewriter, prompt assembler, and LLM service. The only difference from the chat endpoint: synchronous JSON response instead of SSE, and exposure of `retrieved_chunks` and `rewritten_query` in the response body.

**Auth:** Same admin API key as other `/api/admin/*` endpoints.

### 1.3 EvalJudge

A wrapper around LiteLLM for judge calls:

- Reads `EVAL_JUDGE_MODEL` from env (via `EvalConfig`)
- Falls back to the twin's `LLM_MODEL` if not set
- Provides `async judge(prompt: str) -> str` method
- Handles retries (tenacity) and timeouts
- Each answer quality scorer uses `EvalJudge` to call the LLM-as-judge

---

## 2. Dataset Format

### 2.1 Extended YAML Schema

```yaml
suite: answer_quality
description: Answer quality evaluation with LLM-as-judge
snapshot_id: "00000000-0000-0000-0000-000000000000"
cases:
  - id: aq-001
    query: "What is covered in chapter 3 of the guide?"
    expected:                          # optional — retrieval expectations (S8-01)
      - source_id: "<uuid>"
        contains: "chapter 3"
    answer_expectations:               # optional — answer quality expectations (S8-02)
      should_refuse: false             # true = twin should refuse to answer
      expected_citations:              # source_ids expected in citations
        - "<uuid>"
      persona_tags:                    # persona aspects to verify
        - expert
        - friendly
      groundedness_notes: "Answer should reference guide content"
    tags: [answer, groundedness, citation]
```

### 2.2 New Pydantic Models

```
AnswerExpectations (BaseModel):
    should_refuse: bool = False
    expected_citations: list[UUID] = []
    persona_tags: list[str] = []
    groundedness_notes: str = ""

EvalCase (extended):
    + answer_expectations: AnswerExpectations | None = None

GenerationResult (BaseModel):
    answer: str
    citations: list[dict[str, Any]]       # JSON-serialized citation dicts from HTTP response
    retrieved_chunks: list[ReturnedChunk]
    rewritten_query: str
    timing_ms: float
    model: str
```

### 2.3 Seed Data

**Seed knowledge** (`backend/evals/seed_knowledge/`):

| File | Content | Purpose |
|------|---------|---------|
| `guide.md` | Technical guide with 3-4 chapters | Retrieval precision, groundedness |
| `biography.md` | Prototype biography | Persona fidelity |
| `faq.md` | FAQ with 5-6 Q&A pairs | Citation accuracy |

**Seed persona** (`backend/evals/seed_persona/`):

| File | Content |
|------|---------|
| `IDENTITY.md` | Minimal identity: name, role, background |
| `SOUL.md` | Tone: friendly, expert, concise |
| `BEHAVIOR.md` | Boundaries: stays on topic, refuses off-topic gracefully |

**Seed datasets** (`backend/evals/datasets/`):

| File | Cases | Focus |
|------|-------|-------|
| `retrieval_basic.yaml` | 5-7 | Retrieval precision, recall, MRR (extends S8-01) |
| `answer_quality.yaml` | 5-7 | Groundedness + citation accuracy |
| `persona_and_refusal.yaml` | 5-7 | Persona fidelity (3-4) + refusal quality (2-3) |

Total: ~15-20 cases.

---

## 3. Answer Quality Scorers

All scorers implement the existing `Scorer` Protocol. Each contains a rubric prompt for LLM-as-judge and normalizes the 1-5 score to 0.0-1.0.

### 3.1 Groundedness Scorer

**Metric name:** `groundedness`

**Judge input:** answer text + retrieved chunks (text + source_id)

**Rubric:**

| Score | Description |
|-------|-------------|
| 5 | Every factual claim is directly supported by retrieved chunks |
| 4 | Core claims supported, one minor unsupported detail |
| 3 | Mixed — some claims supported, some not traceable to chunks |
| 2 | Mostly unsupported, only fragments grounded |
| 1 | Fabricated or contradicts retrieved chunks |

**Judge task:** For each factual claim in the answer, determine whether it can be traced to a specific retrieved chunk. Return a score (1-5) and a brief explanation.

### 3.2 Citation Accuracy Scorer

**Metric name:** `citation_accuracy`

**Judge input:** answer text + citations array + retrieved chunks + expected_citations (from dataset)

**Rubric:**

| Score | Description |
|-------|-------------|
| 5 | All [source:N] markers map to correct, relevant sources; no missing citations for key claims |
| 4 | Citations correct, one minor source missing |
| 3 | Some citations correct, some point to wrong sources or are missing |
| 2 | Most citations incorrect or missing |
| 1 | No citations or all incorrect |

**Judge task:** Verify each citation marker points to the source that actually contains the referenced information. Check for missing citations on key factual claims.

### 3.3 Persona Fidelity Scorer

**Metric name:** `persona_fidelity`

**Judge input:** answer text + IDENTITY.md + SOUL.md + BEHAVIOR.md content + persona_tags from dataset

**Rubric:**

| Score | Description |
|-------|-------------|
| 5 | Tone, style, and boundaries perfectly match persona files |
| 4 | Mostly aligned, minor deviation in tone or formality |
| 3 | Recognizable but inconsistent — shifts between persona and generic |
| 2 | Mostly generic, occasional persona elements |
| 1 | Completely ignores persona, generic AI assistant response |

**Judge task:** Evaluate whether the response reflects the persona's voice, style, and boundaries as defined in the persona files. Focus on the aspects indicated by `persona_tags`.

**Persona file loading:** The scorer reads persona files from a configurable path (default: `persona/`). For seed evals, uses `evals/seed_persona/`.

### 3.4 Refusal Quality Scorer

**Metric name:** `refusal_quality`

**Judge input:** answer text + query + retrieved chunks (expected: empty or irrelevant)

**Rubric:**

| Score | Description |
|-------|-------------|
| 5 | Honest, helpful refusal; acknowledges gap; suggests what it can help with |
| 4 | Correct refusal, slightly generic |
| 3 | Refuses but awkwardly, or partially answers when should fully refuse |
| 2 | Attempts to answer with fabricated info instead of refusing |
| 1 | Confidently fabricates an answer on a topic outside knowledge |

**Judge task:** Evaluate whether the twin correctly refuses when the query is outside its knowledge, and whether the refusal is helpful and honest.

**Conditional execution:** Only runs on cases where `answer_expectations.should_refuse == True`.

### 3.5 Score Normalization

All 1-5 raw scores are normalized: `normalized = (raw - 1) / 4`

| Raw | Normalized |
|-----|------------|
| 5 | 1.00 |
| 4 | 0.75 |
| 3 | 0.50 |
| 2 | 0.25 |
| 1 | 0.00 |

Compatible with existing retrieval metrics (0.0-1.0 range) in reports and aggregation.

### 3.6 Judge Response Parsing

Each scorer prompts the judge to return structured output:

```
Score: <1-5>
Reasoning: <brief explanation>
```

The scorer parses this with a simple regex. If parsing fails (malformed response), the case is marked as `error` with the raw judge response in details.

---

## 4. Runner Extension

### 4.1 Scorer Auto-Selection

`SuiteRunner` determines which scorers to apply for each case:

| Case has | Calls endpoint | Scorers applied |
|----------|---------------|-----------------|
| `expected` only | `/eval/retrieve` | precision_at_k, recall_at_k, mrr |
| `answer_expectations` only | `/eval/generate` | groundedness, citation_accuracy, persona_fidelity*, refusal_quality* |
| Both | `/eval/retrieve` + `/eval/generate` | All applicable |

*persona_fidelity runs when `persona_tags` is non-empty.
*refusal_quality runs when `should_refuse == True`.

### 4.2 EvalClient Extension

New method:

```
async def generate(query, snapshot_id) -> GenerationResult
```

Posts to `/api/admin/eval/generate`, returns full generation result. Single-turn only — multi-turn evaluation is out of scope for this story.

### 4.3 CaseResult Extension

`CaseResult.details` now includes:
- `answer` — twin's full response (for manual review)
- `judge_reasoning` — per-metric explanation from judge (for manual review)

---

## 5. Compare CLI

### 5.1 Command

```bash
python -m evals.compare \
    --baseline evals/baselines/v1_baseline.json \
    --current evals/reports/suite_2026-03-30.json
```

### 5.2 Output

```
Metric              Baseline    Current     Delta    Zone
──────────────────────────────────────────────────────────
precision_at_k      0.72        0.78        +0.06    GREEN
recall_at_k         0.65        0.68        +0.03    YELLOW
mrr                 0.80        0.82        +0.02    GREEN
groundedness        —           0.85        (new)    GREEN
citation_accuracy   —           0.70        (new)    YELLOW
persona_fidelity    —           0.78        (new)    GREEN
refusal_quality     —           0.90        (new)    GREEN
```

### 5.3 Threshold Zones

Initial thresholds (calibrated after first baseline run):

| Metric | Green (>) | Yellow | Red (<) |
|--------|-----------|--------|---------|
| precision_at_k | 0.70 | 0.50-0.70 | 0.50 |
| recall_at_k | 0.70 | 0.50-0.70 | 0.50 |
| mrr | 0.60 | 0.40-0.60 | 0.40 |
| groundedness | 0.75 | 0.50-0.75 | 0.50 |
| citation_accuracy | 0.70 | 0.50-0.70 | 0.50 |
| persona_fidelity | 0.70 | 0.50-0.70 | 0.50 |
| refusal_quality | 0.80 | 0.60-0.80 | 0.60 |

Thresholds stored in `evals/config.py` — easy to update after calibration.

### 5.4 Compare Module

`evals/compare.py`:
- Loads two JSON reports
- Matches metrics by name
- Computes delta
- Applies zone classification
- Outputs formatted table to stdout
- Exit code: 0 if no RED zones, 1 if any RED zone (useful in scripts)

---

## 6. Report Extension

### 6.1 Manual Review Candidates

ReportGenerator adds a new section to the Markdown report: **"Manual Review Candidates"**.

For each answer quality metric, the top-3 worst performers are listed with:
- Case ID and query
- Twin's full answer
- Judge score and reasoning
- Retrieved chunks summary

This enables the owner to:
- Verify judge accuracy (calibrate trust in LLM-as-judge)
- Identify systematic issues (e.g., persona drift, citation gaps)
- Record agreement/disagreement in the decision document

### 6.2 Extended JSON Report

JSON report includes new fields in `CaseResult`:
- `answer` — twin's response text
- `generation_timing_ms` — generation time
- `judge_scores` — per-metric raw (1-5) and normalized scores
- `judge_reasoning` — per-metric explanation

---

## 7. Baseline Workflow

### Step-by-step

1. **Prepare seed knowledge:**
   - Ingest seed documents from `evals/seed_knowledge/` into the system
   - Create and publish a snapshot
   - Record `snapshot_id`

2. **Configure persona:**
   - Copy `evals/seed_persona/` files to `persona/` (or configure persona path in eval config)

3. **Run evals:**
   ```bash
   python -m evals.run_evals \
       --dataset evals/datasets/ \
       --snapshot-id <snapshot_id> \
       --output-dir evals/reports
   ```

4. **Review report:**
   - Check Markdown report for metric summary and worst performers
   - Manual review of flagged cases

5. **Promote to baseline:**
   ```bash
   cp evals/reports/<suite>_<timestamp>.json evals/baselines/v1_baseline.json
   git add evals/baselines/v1_baseline.json
   git commit -m "chore(evals): record v1 baseline"
   ```

6. **After upgrades (Phase 9), compare:**
   ```bash
   python -m evals.compare \
       --baseline evals/baselines/v1_baseline.json \
       --current evals/reports/<new_report>.json
   ```

---

## 8. Decision Document

### Location

`docs/eval-decision-v1.md`

### Structure

1. **Executive summary** — one sentence: overall recommendation
2. **Baseline metrics table** — all metrics with zones (green/yellow/red)
3. **Analysis per upgrade path:**
   - **Chunk enrichment**
     - Trigger: low recall + low groundedness (chunks exist but aren't found, or found chunks lack context)
     - Expected impact: +10-20% recall via keyword/question enrichment
     - Cost: 5-10x ingestion cost increase (mitigated by Batch API)
     - Reference: `docs/rag.md § Chunk enrichment`
   - **Parent-child chunking**
     - Trigger: high precision but low groundedness (found the right fragment, but not enough surrounding context for a good answer)
     - Expected impact: better context completeness for long documents
     - Cost: moderate complexity, schema change for hierarchy
     - Reference: `docs/rag.md § Parent-child chunking`
   - **BGE-M3 fallback**
     - Trigger: BM25 sparse recall significantly lower than dense recall for the target language
     - Expected impact: improved keyword matching for non-English
     - Cost: additional model dependency, moderate complexity
     - Reference: `docs/spec.md § Multilingual support`
4. **Worst performers analysis** — breakdown of specific failing cases
5. **Human review summary** — owner's agreement/disagreement with judge scores
6. **Prioritized recommendations** — ordered list of upgrades with expected impact
7. **Next steps** — specific Phase 9 stories with priority and order

### Generation

The decision document is written manually after reviewing eval results. The eval framework provides the data; the interpretation and prioritization require human judgment.

---

## 9. Configuration

### New Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EVAL_JUDGE_MODEL` | (falls back to `LLM_MODEL`) | Model for LLM-as-judge scoring |

### EvalConfig Extension

```
EvalConfig (extended):
    + judge_model: str | None = None       # from EVAL_JUDGE_MODEL
    + persona_path: str = "persona/"       # path to persona files for persona fidelity scorer
    + seed_persona_path: str = "evals/seed_persona/"  # fallback for seed evals
    + thresholds: dict[str, ThresholdZone] # metric → green/yellow/red boundaries
```

### ThresholdZone Model

```
ThresholdZone:
    green_above: float    # score > this → GREEN
    red_below: float      # score < this → RED
    # yellow = between red_below and green_above
```

---

## 10. File Structure (New/Modified)

```
backend/evals/
├── datasets/
│   ├── retrieval_basic.yaml          # extended with more cases
│   ├── answer_quality.yaml           # NEW — groundedness + citation accuracy
│   └── persona_and_refusal.yaml      # NEW — persona fidelity + refusal quality
├── seed_knowledge/                   # NEW — test documents
│   ├── guide.md
│   ├── biography.md
│   └── faq.md
├── seed_persona/                     # NEW — test persona files
│   ├── IDENTITY.md
│   ├── SOUL.md
│   └── BEHAVIOR.md
├── baselines/                        # NEW — promoted baseline reports
│   └── .gitkeep
├── scorers/
│   ├── __init__.py
│   ├── precision.py                  # existing
│   ├── recall.py                     # existing
│   ├── mrr.py                        # existing
│   ├── groundedness.py               # NEW
│   ├── citation_accuracy.py          # NEW
│   ├── persona_fidelity.py           # NEW
│   └── refusal_quality.py            # NEW
├── reports/                          # existing
├── client.py                         # MODIFIED — add generate() method
├── config.py                         # MODIFIED — add judge_model, thresholds
├── models.py                         # MODIFIED — add AnswerExpectations, GenerationResult
├── runner.py                         # MODIFIED — scorer auto-selection
├── report.py                         # MODIFIED — manual review section, extended JSON
├── judge.py                          # NEW — EvalJudge wrapper
├── compare.py                        # NEW — compare CLI
├── run_evals.py                      # MODIFIED — add --judge-model, --persona-path args, wire answer scorers
└── loader.py                         # MODIFIED — support answer_expectations

backend/app/api/
└── admin_eval.py                     # MODIFIED — add /eval/generate endpoint

docs/
└── eval-decision-v1.md               # NEW — written after eval run (manual)
```

---

## 11. Testing

### Unit Tests (CI)

| Test | What it verifies |
|------|-----------------|
| `test_groundedness_scorer` | Rubric prompt construction, response parsing, score normalization |
| `test_citation_accuracy_scorer` | Citation matching logic, expected_citations comparison |
| `test_persona_fidelity_scorer` | Persona file loading, prompt assembly |
| `test_refusal_quality_scorer` | Conditional execution (only when should_refuse=True) |
| `test_judge_response_parsing` | Regex parsing of "Score: N / Reasoning: ..." format |
| `test_runner_scorer_selection` | Auto-selection based on case fields |
| `test_compare_cli` | Delta computation, zone classification, exit codes |
| `test_dataset_loader_extended` | answer_expectations parsing, optional fields |
| `test_report_manual_review` | Worst performers section generation |

All unit tests mock the LLM judge — no external provider dependency in CI.

### Quality Tests (Evals)

Run separately, not in CI. Require:
- Running backend with populated knowledge base
- `EVAL_JUDGE_MODEL` configured (or falls back to twin model)
- Seed knowledge ingested and snapshot published

---

## 12. Out of Scope

- Automated eval triggering (e.g., on snapshot publish) — future work
- Web UI for eval results — reports are Markdown/JSON files
- A/B testing framework — Phase 9 stories handle before/after comparison via baseline
- Conversation-level evals (multi-turn coherence) — deferred, single-turn sufficient for baseline
- Embedding dimension optimization (1024/1536/3072) — separate eval concern, not part of this story
