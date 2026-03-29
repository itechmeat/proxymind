# eval-answer-scoring

LLM-as-judge answer quality scorers: groundedness, citation accuracy, persona fidelity, and refusal quality. Each scorer uses a 1-5 rubric normalized to 0.0-1.0, powered by a configurable EvalJudge wrapper over LiteLLM.

## ADDED Requirements

### Requirement: EvalJudge wrapper

The `EvalJudge` class SHALL provide an `async judge(prompt: str) -> str` method that calls an LLM via LiteLLM. The judge model SHALL be configurable via `EVAL_JUDGE_MODEL` environment variable (read through `EvalConfig`). When `EVAL_JUDGE_MODEL` is not set, the judge SHALL fall back to the twin's `LLM_MODEL`. The judge SHALL handle retries (via tenacity) and timeouts. All answer quality scorers SHALL use `EvalJudge` for their LLM-as-judge calls.

#### Scenario: Judge uses configured model

- **WHEN** `EVAL_JUDGE_MODEL` is set to `"gemini-2.0-flash"` and `judge(prompt)` is called
- **THEN** the LiteLLM call SHALL use `"gemini-2.0-flash"` as the model

#### Scenario: Judge falls back to twin model

- **WHEN** `EVAL_JUDGE_MODEL` is not set and `LLM_MODEL` is `"gemini-2.0-pro"`
- **THEN** the judge SHALL use `"gemini-2.0-pro"` as the model

#### Scenario: Judge parses response text

- **WHEN** the LLM returns a response
- **THEN** the judge SHALL return the response content as a plain string for the scorer to parse

---

### Requirement: Judge response parsing

All answer quality scorers SHALL prompt the judge to return output in the format `"Score: <1-5>\nReasoning: <brief explanation>"`. Each scorer SHALL parse the judge response using a regex to extract the integer score (1-5) and the reasoning text. If parsing fails (malformed response, score outside 1-5 range, or missing format), the scorer SHALL return a `ScorerOutput` with `score=0.0` and `details` containing an `"error"` key with the raw judge response.

#### Scenario: Valid judge response parsed

- **WHEN** the judge returns `"Score: 4\nReasoning: Most claims are well-supported"`
- **THEN** the scorer extracts raw score `4` and reasoning `"Most claims are well-supported"`

#### Scenario: Malformed response yields error

- **WHEN** the judge returns `"I think this is a 4 out of 5"`
- **THEN** the scorer SHALL return `ScorerOutput(score=0.0, details={"error": ...})` where `error` contains the raw judge response

#### Scenario: Score outside valid range yields error

- **WHEN** the judge returns `"Score: 7\nReasoning: Excellent"`
- **THEN** the scorer SHALL return `ScorerOutput(score=0.0, details={"error": ...})`

---

### Requirement: Score normalization

All answer quality scorers SHALL normalize the raw 1-5 judge score to a 0.0-1.0 float using the formula `normalized = (raw - 1) / 4`. Raw score 5 SHALL produce 1.0, raw score 4 SHALL produce 0.75, raw score 3 SHALL produce 0.50, raw score 2 SHALL produce 0.25, and raw score 1 SHALL produce 0.00. The normalized score SHALL be used in the `ScorerOutput.score` field to maintain compatibility with existing retrieval metrics.

#### Scenario: Raw score 5 normalizes to 1.0

- **WHEN** the judge returns a raw score of 5
- **THEN** the normalized score is `1.0`

#### Scenario: Raw score 3 normalizes to 0.5

- **WHEN** the judge returns a raw score of 3
- **THEN** the normalized score is `0.5`

#### Scenario: Raw score 1 normalizes to 0.0

- **WHEN** the judge returns a raw score of 1
- **THEN** the normalized score is `0.0`

---

### Requirement: Groundedness scorer

The `Groundedness` scorer SHALL implement the `AnswerScorer` protocol with `name = "groundedness"`. The scorer SHALL construct a judge prompt containing the twin's answer text and the retrieved chunks (text + source_id). The judge SHALL evaluate whether each factual claim in the answer can be traced to a specific retrieved chunk, using a 1-5 rubric: 5 = every claim directly supported, 4 = core claims supported with one minor unsupported detail, 3 = mixed support, 2 = mostly unsupported, 1 = fabricated or contradicts chunks. The raw score SHALL be normalized to 0.0-1.0. The `ScorerOutput.details` SHALL include the judge reasoning.

#### Scenario: Fully grounded answer scores high

- **WHEN** the answer contains only claims traceable to the retrieved chunks and the judge returns `"Score: 5\nReasoning: All claims supported"`
- **THEN** the scorer returns `ScorerOutput(score=1.0, details={"reasoning": "All claims supported", "raw_score": 5})`

#### Scenario: Fabricated answer scores low

- **WHEN** the answer contradicts the retrieved chunks and the judge returns `"Score: 1\nReasoning: Fabricated content"`
- **THEN** the scorer returns `ScorerOutput(score=0.0, details={"reasoning": "Fabricated content", "raw_score": 1})`

#### Scenario: Scorer includes chunks in prompt

- **WHEN** the scorer constructs the judge prompt
- **THEN** the prompt SHALL contain each retrieved chunk's text and source_id

---

### Requirement: Citation accuracy scorer

The `CitationAccuracy` scorer SHALL implement the `AnswerScorer` protocol with `name = "citation_accuracy"`. The scorer SHALL construct a judge prompt containing the answer text, the citations array, the retrieved chunks, and the `expected_citations` from the dataset case (if provided). The judge SHALL verify that each `[source:N]` marker in the answer maps to a correct and relevant source, and check for missing citations on key factual claims, using a 1-5 rubric: 5 = all markers correct and no missing citations, 4 = citations correct with one minor source missing, 3 = some correct and some wrong or missing, 2 = most incorrect or missing, 1 = no citations or all incorrect. The raw score SHALL be normalized to 0.0-1.0.

#### Scenario: All citations correct

- **WHEN** every `[source:N]` marker in the answer maps to the correct source and no key claims lack citations, and the judge returns `"Score: 5\nReasoning: Perfect citation coverage"`
- **THEN** the scorer returns `ScorerOutput(score=1.0, ...)`

#### Scenario: No citations present

- **WHEN** the answer contains no citation markers and the judge returns `"Score: 1\nReasoning: No citations found"`
- **THEN** the scorer returns `ScorerOutput(score=0.0, ...)`

#### Scenario: Expected citations included in prompt

- **WHEN** the eval case has `answer_expectations.expected_citations` with source UUIDs
- **THEN** the judge prompt SHALL include those expected source IDs for reference

---

### Requirement: Persona fidelity scorer

The `PersonaFidelity` scorer SHALL implement the `AnswerScorer` protocol with `name = "persona_fidelity"`. The scorer SHALL load persona files (IDENTITY.md, SOUL.md, BEHAVIOR.md) from a configurable path. The judge prompt SHALL contain the answer text, the content of all three persona files, and the `persona_tags` from the dataset case. The judge SHALL evaluate alignment with the persona's voice, style, and boundaries, using a 1-5 rubric: 5 = perfect match, 4 = mostly aligned with minor deviation, 3 = recognizable but inconsistent, 2 = mostly generic, 1 = completely ignores persona. The scorer SHALL only execute on cases where `answer_expectations.persona_tags` is non-empty; for cases without persona_tags, the scorer SHALL be skipped.

#### Scenario: Persona-aligned answer scores high

- **WHEN** the answer matches the persona's tone and boundaries and the judge returns `"Score: 5\nReasoning: Perfect persona match"`
- **THEN** the scorer returns `ScorerOutput(score=1.0, ...)`

#### Scenario: Generic answer scores low

- **WHEN** the answer ignores the persona entirely and the judge returns `"Score: 1\nReasoning: Generic AI response"`
- **THEN** the scorer returns `ScorerOutput(score=0.0, ...)`

#### Scenario: Scorer skipped when no persona_tags

- **WHEN** the eval case has no `persona_tags` (empty list or not set)
- **THEN** the persona fidelity scorer SHALL not execute and SHALL not produce a score for that case

#### Scenario: Persona files loaded from configured path

- **WHEN** the scorer is initialized with `persona_path="evals/seed_persona/"`
- **THEN** it SHALL read IDENTITY.md, SOUL.md, and BEHAVIOR.md from that directory

---

### Requirement: Refusal quality scorer

The `RefusalQuality` scorer SHALL implement the `AnswerScorer` protocol with `name = "refusal_quality"`. The scorer SHALL construct a judge prompt containing the answer text, the original query, and the retrieved chunks (expected to be empty or irrelevant for refusal cases). The judge SHALL evaluate whether the twin correctly refuses when the query is outside its knowledge and whether the refusal is helpful and honest, using a 1-5 rubric: 5 = honest and helpful refusal that acknowledges the gap and suggests alternatives, 4 = correct but slightly generic refusal, 3 = awkward refusal or partial answer, 2 = attempts to answer with fabricated info, 1 = confidently fabricates an answer. The scorer SHALL only execute on cases where `answer_expectations.should_refuse == True`; for other cases, the scorer SHALL be skipped.

#### Scenario: Helpful refusal scores high

- **WHEN** the twin honestly refuses and suggests what it can help with, and the judge returns `"Score: 5\nReasoning: Excellent refusal"`
- **THEN** the scorer returns `ScorerOutput(score=1.0, ...)`

#### Scenario: Fabricated answer instead of refusal scores low

- **WHEN** the twin fabricates an answer on an out-of-scope topic and the judge returns `"Score: 1\nReasoning: Fabricated instead of refusing"`
- **THEN** the scorer returns `ScorerOutput(score=0.0, ...)`

#### Scenario: Scorer skipped when should_refuse is False

- **WHEN** the eval case has `answer_expectations.should_refuse == False` or no `answer_expectations`
- **THEN** the refusal quality scorer SHALL not execute and SHALL not produce a score for that case

#### Scenario: Query and chunks included in prompt

- **WHEN** the scorer constructs the judge prompt for a refusal case
- **THEN** the prompt SHALL contain the original query and the retrieved chunks (to show what context was available)
