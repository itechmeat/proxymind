## MODIFIED Requirements

### Requirement: Placeholder App component

The frontend SHALL render a functional chat interface (ChatPage) via React Router instead of the bootstrap placeholder. The App component SHALL configure React Router with the chat page at the root path (`/`). The placeholder landing page content, `App.css`, and unused assets (`hero.png`, `vite.svg`, `react.svg`) SHALL be removed.

#### Scenario: App component renders chat interface

- **WHEN** the Vite dev server is started with `bun run dev`
- **THEN** the browser SHALL display the chat interface (header, message list, input) at `http://localhost:5173`

#### Scenario: App component uses React Router

- **WHEN** inspecting `frontend/src/App.tsx`
- **THEN** it SHALL configure `BrowserRouter` with a route rendering `ChatPage` at path `/`

#### Scenario: Bootstrap assets removed

- **WHEN** inspecting `frontend/src/`
- **THEN** `App.css`, `assets/hero.png`, `assets/vite.svg`, and `assets/react.svg` SHALL NOT exist

### Requirement: Frontend .env with VITE_API_URL

The frontend SHALL use a `.env` file with a `VITE_API_URL` variable. The default value SHALL be empty (empty string), meaning all API requests use relative paths (`/api/...`). In development, the Vite `server.proxy` configuration forwards `/api` requests to the backend. In production, Caddy serves both frontend and backend on the same origin. An absolute URL MAY be set to override this behavior for non-standard deployments.

Additional environment variables SHALL be defined:
- `VITE_TWIN_NAME` — display name for the digital twin (default: `ProxyMind`)
- `VITE_TWIN_AVATAR_URL` — URL for the twin's avatar image (default: empty, falls back to initials)

#### Scenario: VITE_API_URL defaults to empty

- **WHEN** inspecting `frontend/.env.example`
- **THEN** `VITE_API_URL` SHALL be present with an empty default value

#### Scenario: Twin configuration variables exist

- **WHEN** inspecting `frontend/.env.example`
- **THEN** it SHALL contain `VITE_TWIN_NAME` and `VITE_TWIN_AVATAR_URL`

#### Scenario: Vite dev proxy forwards API requests

- **WHEN** the Vite dev server is running and a request is made to `/api/chat/sessions`
- **THEN** Vite SHALL proxy the request to `http://localhost:8000/api/chat/sessions`

### Requirement: package.json scripts

The `package.json` SHALL define scripts for common development tasks: starting the dev server, running the linter, running the formatter, running the production build, and running tests.

#### Scenario: Dev script starts Vite dev server

- **WHEN** `bun run dev` is executed in the `frontend/` directory
- **THEN** the Vite development server SHALL start on `localhost:5173`

#### Scenario: Lint script runs Biome check

- **WHEN** `bun run lint` is executed in the `frontend/` directory
- **THEN** Biome SHALL check the source code for lint and format violations

#### Scenario: Format script runs Biome format

- **WHEN** `bun run format` is executed in the `frontend/` directory
- **THEN** Biome SHALL format the source code in place

#### Scenario: Test script runs Vitest

- **WHEN** `bun run test` is executed in the `frontend/` directory
- **THEN** Vitest SHALL run the full test suite and exit with code 0 on success

#### Scenario: Watch test script runs Vitest in watch mode

- **WHEN** `bun run test:watch` is executed in the `frontend/` directory
- **THEN** Vitest SHALL run in watch mode, re-running tests on file changes
