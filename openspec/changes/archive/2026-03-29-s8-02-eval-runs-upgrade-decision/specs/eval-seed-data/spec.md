# eval-seed-data

Seed knowledge documents, persona files, eval datasets, and decision document template for reproducible baseline eval runs. Provides out-of-box content so the eval framework can produce meaningful results without requiring real user data.

## ADDED Requirements

### Requirement: Seed knowledge documents

Three Markdown files SHALL be provided in `evals/seed_knowledge/` to serve as test knowledge for eval runs:

| File | Content | Purpose |
|------|---------|---------|
| `guide.md` | Technical guide with 3-4 chapters | Retrieval precision, groundedness scoring |
| `biography.md` | Prototype biography | Persona fidelity scoring |
| `faq.md` | FAQ with 5-6 question-answer pairs | Citation accuracy scoring |

Each file SHALL contain sufficient content (at least several paragraphs) to produce meaningful retrieval results and enable groundedness evaluation. The content SHALL be fictional but internally consistent.

#### Scenario: All three seed knowledge files exist

- **WHEN** the eval seed data is set up
- **THEN** `evals/seed_knowledge/guide.md`, `evals/seed_knowledge/biography.md`, and `evals/seed_knowledge/faq.md` SHALL all exist and be non-empty

#### Scenario: Guide has chapter structure

- **WHEN** `guide.md` is read
- **THEN** it SHALL contain at least 3 distinct chapters or sections with different topics

#### Scenario: FAQ has question-answer pairs

- **WHEN** `faq.md` is read
- **THEN** it SHALL contain at least 5 distinct question-answer pairs

---

### Requirement: Seed persona files

Three persona files SHALL be provided in `evals/seed_persona/` to serve as a test persona for eval runs:

| File | Content |
|------|---------|
| `IDENTITY.md` | Minimal identity: name, role, background |
| `SOUL.md` | Tone: friendly, expert, concise |
| `BEHAVIOR.md` | Boundaries: stays on topic, refuses off-topic gracefully |

These files SHALL follow the same format as production persona files and SHALL be loadable by the persona fidelity scorer.

#### Scenario: All three seed persona files exist

- **WHEN** the eval seed data is set up
- **THEN** `evals/seed_persona/IDENTITY.md`, `evals/seed_persona/SOUL.md`, and `evals/seed_persona/BEHAVIOR.md` SHALL all exist and be non-empty

#### Scenario: Persona files define a consistent character

- **WHEN** the seed persona files are read together
- **THEN** they SHALL describe a consistent persona with a defined identity, tone, and behavioral boundaries

---

### Requirement: Seed eval datasets

Two eval dataset YAML files SHALL be provided in `evals/datasets/`:

| File | Cases | Focus |
|------|-------|-------|
| `answer_quality.yaml` | 5-7 cases | Groundedness + citation accuracy |
| `persona_and_refusal.yaml` | 5-7 cases | Persona fidelity (3-4 cases) + refusal quality (2-3 cases) |

Together with the existing `retrieval_basic.yaml` from S8-01, the total seed dataset SHALL contain approximately 15-20 cases. Each dataset file SHALL conform to the extended YAML schema with optional `answer_expectations`. Refusal cases SHALL have `answer_expectations.should_refuse: true`. Persona cases SHALL have non-empty `answer_expectations.persona_tags`. Each case SHALL have appropriate `tags` for filtering.

#### Scenario: Answer quality dataset exists with correct structure

- **WHEN** `evals/datasets/answer_quality.yaml` is loaded
- **THEN** it SHALL parse as a valid `EvalSuite` with 5-7 cases, each having `answer_expectations`

#### Scenario: Persona and refusal dataset exists with correct structure

- **WHEN** `evals/datasets/persona_and_refusal.yaml` is loaded
- **THEN** it SHALL parse as a valid `EvalSuite` with 5-7 cases, including at least 2 cases with `answer_expectations.should_refuse: true` and at least 3 cases with non-empty `answer_expectations.persona_tags`

#### Scenario: Total seed cases in expected range

- **WHEN** all dataset files in `evals/datasets/` are loaded
- **THEN** the total number of cases across all suites SHALL be between 15 and 20

#### Scenario: Datasets reference seed knowledge content

- **WHEN** dataset cases reference source content
- **THEN** the queries and expectations SHALL correspond to the content in `evals/seed_knowledge/` files

---

### Requirement: Decision document template

A decision document template SHALL be provided at `docs/eval-decision-v1.md`. The template SHALL contain the following sections:

1. Executive summary (placeholder for one-sentence recommendation)
2. Baseline metrics table (placeholder table with all 7 metrics and zone columns)
3. Analysis per upgrade path: chunk enrichment, parent-child chunking, BGE-M3 fallback (with trigger conditions, expected impact, cost, and reference links)
4. Worst performers analysis (placeholder for specific failing cases)
5. Human review summary (placeholder for owner agreement/disagreement with judge scores)
6. Prioritized recommendations (placeholder for ordered upgrade list)
7. Next steps (placeholder for Phase 9 stories with priority and order)

The document is intended to be filled in manually after reviewing eval results. The eval framework provides the data; interpretation and prioritization require human judgment.

#### Scenario: Decision document template exists

- **WHEN** the eval seed data is set up
- **THEN** `docs/eval-decision-v1.md` SHALL exist and be non-empty

#### Scenario: Template contains all required sections

- **WHEN** `docs/eval-decision-v1.md` is read
- **THEN** it SHALL contain headings for executive summary, baseline metrics table, analysis per upgrade path, worst performers analysis, human review summary, prioritized recommendations, and next steps
