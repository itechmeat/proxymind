## ADDED Requirements

### Requirement: Bun + Vite + React scaffold

The frontend SHALL be initialized as a Vite + React + TypeScript project using Bun as the package manager and runtime. Package versions SHALL meet or exceed the minimums specified in `docs/spec.md` for Bun, React, Vite, and Biome.

#### Scenario: Frontend project structure exists

- **WHEN** inspecting the `frontend/` directory
- **THEN** it SHALL contain `package.json`, `vite.config.ts`, `tsconfig.json`, `index.html`, and `src/main.tsx`

#### Scenario: Bun lock file is committed

- **WHEN** cloning the repository
- **THEN** `frontend/bun.lock` SHALL exist and be tracked in git

### Requirement: Biome as sole linter and formatter

Biome SHALL be the only linter and formatter for the frontend. ESLint and Prettier configurations SHALL NOT be present. Biome SHALL be configured via `biome.json` in the frontend directory.

#### Scenario: No ESLint configuration exists

- **WHEN** inspecting the `frontend/` directory
- **THEN** there SHALL be no `.eslintrc`, `.eslintrc.js`, `.eslintrc.json`, `eslint.config.js`, or any ESLint configuration files

#### Scenario: No Prettier configuration exists

- **WHEN** inspecting the `frontend/` directory
- **THEN** there SHALL be no `.prettierrc`, `.prettierrc.js`, `prettier.config.js`, or any Prettier configuration files

#### Scenario: Biome configuration exists

- **WHEN** inspecting `frontend/biome.json`
- **THEN** it SHALL be a valid Biome configuration enabling both linting and formatting

#### Scenario: ESLint is not a dependency

- **WHEN** inspecting `frontend/package.json` dependencies and devDependencies
- **THEN** neither `eslint` nor any `eslint-*` packages SHALL be listed

### Requirement: Placeholder App component

The frontend SHALL include a placeholder `App` component that renders successfully. This serves as the baseline UI to verify the dev server works.

#### Scenario: App component renders

- **WHEN** the Vite dev server is started with `bun run dev`
- **THEN** the browser SHALL display content from the `App` component at `http://localhost:5173`

#### Scenario: App component exists as a module

- **WHEN** inspecting `frontend/src/App.tsx`
- **THEN** it SHALL export a React component

### Requirement: Frontend .env with VITE_API_URL

The frontend SHALL use a `.env` file with a `VITE_API_URL` variable that configures the backend API base URL. Only variables prefixed with `VITE_` are exposed to the client bundle.

#### Scenario: VITE_API_URL is defined in example

- **WHEN** inspecting `frontend/.env.example`
- **THEN** it SHALL contain a `VITE_API_URL` variable with a default value pointing to the local API (e.g., `http://localhost:8000`)

### Requirement: package.json scripts

The `package.json` SHALL define scripts for common development tasks: starting the dev server, running the linter, and running the formatter.

#### Scenario: Dev script starts Vite dev server

- **WHEN** `bun run dev` is executed in the `frontend/` directory
- **THEN** the Vite development server SHALL start on `localhost:5173`

#### Scenario: Lint script runs Biome check

- **WHEN** `bun run lint` is executed in the `frontend/` directory
- **THEN** Biome SHALL check the source code for lint and format violations

#### Scenario: Format script runs Biome format

- **WHEN** `bun run format` is executed in the `frontend/` directory
- **THEN** Biome SHALL format the source code in place
