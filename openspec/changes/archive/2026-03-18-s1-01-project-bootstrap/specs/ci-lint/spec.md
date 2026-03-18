## ADDED Requirements

### Requirement: GitHub Actions CI workflow

A GitHub Actions workflow SHALL be defined at `.github/workflows/ci.yml`. The workflow SHALL trigger on `push` and `pull_request` events targeting the `master` branch.

#### Scenario: Workflow triggers on push to master

- **WHEN** a commit is pushed to the `master` branch
- **THEN** the CI workflow SHALL execute

#### Scenario: Workflow triggers on pull request to master

- **WHEN** a pull request targeting `master` is opened or updated
- **THEN** the CI workflow SHALL execute

### Requirement: Two parallel lint jobs

The CI workflow SHALL define two independent jobs that run in parallel: `lint-backend` and `lint-frontend`. Neither job SHALL depend on the other.

#### Scenario: Jobs run in parallel

- **WHEN** the CI workflow is triggered
- **THEN** `lint-backend` and `lint-frontend` SHALL start simultaneously without a `needs` dependency between them

### Requirement: Backend lint job with Ruff

The `lint-backend` job SHALL install Python dependencies using `uv` and run Ruff for both linting and format checking. The job SHALL fail if Ruff reports any violations.

#### Scenario: Ruff lint check runs

- **WHEN** the `lint-backend` job executes
- **THEN** it SHALL run `ruff check` against the backend code

#### Scenario: Ruff format check runs

- **WHEN** the `lint-backend` job executes
- **THEN** it SHALL run `ruff format --check` against the backend code

#### Scenario: Backend lint job fails on violations

- **WHEN** the backend code contains Ruff lint or format violations
- **THEN** the `lint-backend` job SHALL exit with a non-zero status

### Requirement: Frontend lint job with Biome

The `lint-frontend` job SHALL install dependencies using Bun and run Biome for combined lint and format checking. The job SHALL fail if Biome reports any violations.

#### Scenario: Biome check runs

- **WHEN** the `lint-frontend` job executes
- **THEN** it SHALL run `biome check` against the frontend code

#### Scenario: Frontend lint job fails on violations

- **WHEN** the frontend code contains Biome lint or format violations
- **THEN** the `lint-frontend` job SHALL exit with a non-zero status

### Requirement: No type checking in CI

The CI workflow SHALL NOT include type checking (pyright, mypy, tsc --noEmit, or equivalent) at this stage. Type checking is deferred to a later story.

#### Scenario: No type check step exists

- **WHEN** inspecting all steps in both CI jobs
- **THEN** there SHALL be no step that runs a type checker (pyright, mypy, tsc, or similar)
