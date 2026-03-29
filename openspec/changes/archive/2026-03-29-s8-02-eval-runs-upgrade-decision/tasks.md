## 1. Models and Config

- [x] 1.1 Add AnswerExpectations and GenerationResult to evals/models.py, make EvalCase.expected optional
- [x] 1.2 Add ThresholdZone, DEFAULT_THRESHOLDS, judge_model, persona_path to evals/config.py
- [x] 1.3 Write unit tests for new models and config (test_eval_models.py, test_eval_config.py)

## 2. EvalJudge Wrapper

- [x] 2.1 Create evals/judge.py with EvalJudge class, parse_judge_response(), normalize()
- [x] 2.2 Write unit tests for judge response parsing, normalization, and LLM call (test_eval_judge.py)

## 3. Answer Quality Scorers

- [x] 3.1 Create evals/scorers/groundedness.py with rubric prompt and scoring logic
- [x] 3.2 Create evals/scorers/citation_accuracy.py with rubric prompt and scoring logic
- [x] 3.3 Create evals/scorers/persona_fidelity.py with rubric prompt, persona file loading, conditional execution
- [x] 3.4 Create evals/scorers/refusal_quality.py with rubric prompt, conditional execution on should_refuse
- [x] 3.5 Write unit tests for all 4 scorers (test_eval_answer_scorers.py) — mock judge calls

## 4. Scorers Init and Client Extension

- [x] 4.1 Add AnswerScorer protocol and default_answer_scorers() to evals/scorers/**init**.py
- [x] 4.2 Add generate() method to evals/client.py
- [x] 4.3 Write unit test for client.generate() (test_eval_client.py)

## 5. Runner Extension

- [x] 5.1 Extend SuiteRunner to accept answer_scorers, auto-select based on case fields
- [x] 5.2 Add retrieved_chunks_summary to case details in runner
- [x] 5.3 Write unit tests for scorer auto-selection (test_eval_runner.py)

## 6. Report Extension

- [x] 6.1 Add Manual Review Candidates section to ReportGenerator (worst performers with judge score, full answer, judge reasoning, chunks summary)
- [x] 6.2 Write unit test for manual review section generation (test_eval_report.py)

## 7. Compare CLI

- [x] 7.1 Create evals/compare.py with compare_reports(), format_comparison(), main()
- [x] 7.2 Write unit tests for delta computation, zone classification, output format, and exit codes (0 = no RED, 1 = any RED) (test_eval_compare.py)

## 8. Backend Endpoint

- [x] 8.1 Add EvalGenerateRequest and EvalGenerateResponse schemas to app/api/eval_schemas.py
- [x] 8.2 Add POST /api/admin/eval/generate endpoint to app/api/admin_eval.py
- [x] 8.3 Write unit test for the generate endpoint (test_eval_generate_endpoint.py)

## 9. CLI Wiring

- [x] 9.1 Add --judge-model and --persona-path args to evals/run_evals.py, wire answer scorers to runner
- [x] 9.2 Verify existing run_evals tests still pass

## 10. Seed Data

- [x] 10.1 Create seed knowledge documents (evals/seed_knowledge/guide.md, biography.md, faq.md)
- [x] 10.2 Create seed persona files (evals/seed_persona/IDENTITY.md, SOUL.md, BEHAVIOR.md)
- [x] 10.3 Create eval datasets (evals/datasets/answer_quality.yaml, persona_and_refusal.yaml)
- [x] 10.4 Create evals/baselines/.gitkeep

## 11. Decision Document and Loader

- [x] 11.1 Create decision document template (docs/eval-decision-v1.md)
- [x] 11.2 Write loader test for answer-only cases (test_eval_loader.py)

## 12. Integration Verification

- [x] 12.1 Run all eval unit tests in Docker and verify they pass
- [x] 12.2 Run full backend test suite in Docker and verify no regressions
- [x] 12.3 Verify CLI help output for run_evals and compare
- [x] 12.4 Verify datasets load correctly with new format
