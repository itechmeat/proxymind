# eval-baseline-comparison

Compare CLI for baseline vs current eval reports with threshold zone classification, delta computation, and formatted output. Enables data-driven upgrade decisions by highlighting metric regressions and improvements.

## ADDED Requirements

### Requirement: Compare CLI

The compare module SHALL be executable as `python -m evals.compare` from the `backend/` directory. The CLI SHALL accept the following arguments:

- `--baseline` (required) -- path to the baseline JSON report file
- `--current` (required) -- path to the current JSON report file

The CLI SHALL load both JSON reports, match metrics by name, compute the delta (current - baseline) for each metric, classify each metric into a threshold zone, and output a formatted table to stdout. If either file does not exist, the CLI SHALL print a human-readable error to stderr and exit with code 1.

#### Scenario: Compare two reports

- **WHEN** the CLI is invoked with `--baseline evals/baselines/v1_baseline.json --current evals/reports/suite_2026-03-30.json`
- **THEN** the output contains a formatted table with columns: Metric, Baseline, Current, Delta, Zone

#### Scenario: Missing baseline file

- **WHEN** the CLI is invoked with a `--baseline` path that does not exist
- **THEN** the CLI prints an error to stderr and exits with code 1

#### Scenario: Missing current file

- **WHEN** the CLI is invoked with a `--current` path that does not exist
- **THEN** the CLI prints an error to stderr and exits with code 1

---

### Requirement: ThresholdZone model

A `ThresholdZone` model SHALL define two float fields: `green_above` (score above this value is GREEN) and `red_below` (score below this value is RED). Scores between `red_below` and `green_above` SHALL be classified as YELLOW. The model SHALL provide a `classify(score: float) -> str` method that returns `"GREEN"`, `"YELLOW"`, or `"RED"` based on the score.

#### Scenario: Score above green threshold

- **WHEN** `classify(0.85)` is called on a ThresholdZone with `green_above=0.70` and `red_below=0.50`
- **THEN** the result is `"GREEN"`

#### Scenario: Score below red threshold

- **WHEN** `classify(0.40)` is called on a ThresholdZone with `green_above=0.70` and `red_below=0.50`
- **THEN** the result is `"RED"`

#### Scenario: Score in yellow zone

- **WHEN** `classify(0.60)` is called on a ThresholdZone with `green_above=0.70` and `red_below=0.50`
- **THEN** the result is `"YELLOW"`

---

### Requirement: Default thresholds

The compare module SHALL define `DEFAULT_THRESHOLDS` as a dict mapping each metric name to a `ThresholdZone`. The default thresholds SHALL be:

| Metric | green_above | red_below |
|--------|-------------|-----------|
| precision_at_k | 0.70 | 0.50 |
| recall_at_k | 0.70 | 0.50 |
| mrr | 0.60 | 0.40 |
| groundedness | 0.75 | 0.50 |
| citation_accuracy | 0.70 | 0.50 |
| persona_fidelity | 0.70 | 0.50 |
| refusal_quality | 0.80 | 0.60 |

These thresholds are initial orientation values stored in `evals/config.py` and SHALL be easy to update after calibration.

#### Scenario: All seven metrics have thresholds

- **WHEN** `DEFAULT_THRESHOLDS` is accessed
- **THEN** it SHALL contain entries for all seven metrics: precision_at_k, recall_at_k, mrr, groundedness, citation_accuracy, persona_fidelity, refusal_quality

#### Scenario: Thresholds classify correctly

- **WHEN** groundedness score is 0.80
- **THEN** `DEFAULT_THRESHOLDS["groundedness"].classify(0.80)` returns `"GREEN"` (since 0.80 > 0.75)

---

### Requirement: Output format

The compare CLI SHALL output a formatted table to stdout containing one row per metric. Each row SHALL display: metric name, baseline value (or `"--"` if the metric is new), current value, delta (with `+`/`-` prefix, or `"(new)"` if no baseline), and zone (GREEN/YELLOW/RED). Metrics present in the current report but absent in the baseline SHALL be displayed with `"--"` for baseline and `"(new)"` for delta, with the zone computed from the current score only.

#### Scenario: Metric with improvement

- **WHEN** baseline has `precision_at_k=0.72` and current has `precision_at_k=0.78`
- **THEN** the row shows Baseline=0.72, Current=0.78, Delta=+0.06

#### Scenario: New metric not in baseline

- **WHEN** current has `groundedness=0.85` and baseline has no groundedness metric
- **THEN** the row shows Baseline=`"--"`, Current=0.85, Delta=`"(new)"`, Zone=GREEN

#### Scenario: Metric with regression

- **WHEN** baseline has `recall_at_k=0.70` and current has `recall_at_k=0.45`
- **THEN** the row shows Delta=-0.25 and Zone=RED (since 0.45 < 0.50)

---

### Requirement: Exit code

The compare CLI SHALL exit with code 0 if no metrics are classified as RED. The CLI SHALL exit with code 1 if any metric is classified as RED. This enables use in scripts and CI-like workflows.

#### Scenario: No red zones exits 0

- **WHEN** all metrics are classified as GREEN or YELLOW
- **THEN** the CLI exits with code 0

#### Scenario: Any red zone exits 1

- **WHEN** at least one metric is classified as RED
- **THEN** the CLI exits with code 1

---

### Requirement: Baselines directory

Baseline reports SHALL be stored in `evals/baselines/`. A `.gitkeep` file SHALL be present to ensure the directory exists in version control. Promoting a report to baseline is a manual step: copying a JSON report from `evals/reports/` to `evals/baselines/` and committing it to git.

#### Scenario: Baselines directory exists

- **WHEN** the eval framework is set up
- **THEN** the `evals/baselines/` directory SHALL exist with a `.gitkeep` file
