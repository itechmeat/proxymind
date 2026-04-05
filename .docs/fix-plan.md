# S7-03 Regression / Fix Loop

## Goal

Run the full auth/chat/admin regression loop through existing automated tests first, not by manually replaying flows that are already covered.

The loop MUST stay full, but custom actions MUST only cover gaps that are not yet represented in tests.

## Core Rule

1. Existing automated tests are the default source of truth.
2. Do not manually repeat user journeys already covered by Playwright, Vitest, or backend pytest.
3. Manual browser exploration is allowed only for:
   - a newly reported issue that has no test yet
   - a UX path not covered by the current test suites
   - debugging a failing automated browser test
4. If a manual run finds a real product issue, add or extend a test for it before closing the loop.

## Test-First Regression Matrix

### 1. Full isolated regression

Default full cycle:

```bash
make test-all-isolated
```

This is the canonical full run. It already includes:

- isolated backend pytest
- frontend Vitest
- real-browser Playwright against the isolated `api-e2e` stack
- a dedicated Docker Compose project namespace for the isolated stack (`proxymind-e2e` by default)
- a dedicated isolated API host port (`18001` by default) so the namespaced stack does not collide with legacy local containers on `8001`

### 2. Backend coverage

Command:

```bash
make test-backend-isolated
```

What it covers:

- backend unit tests
- backend integration tests
- auth API behavior
- protected chat API behavior
- isolated stack seed behavior

### 3. Frontend unit/integration coverage

Command:

```bash
make test-frontend-isolated
```

What it covers:

- frontend unit tests
- React integration tests
- transport/session/auth state behavior already represented in Vitest

### 4. Browser coverage

Command:

```bash
make test-e2e-isolated
```

This is the required browser-backed run. It uses a real browser through Playwright against the isolated test stack.

Current browser suites:

- `frontend/e2e/auth-journeys.spec.ts`
  - anonymous route guard
  - register
  - verify email
  - sign in
  - sign out
- `frontend/e2e/password-recovery.spec.ts`
  - forgot password
  - reset password
- `frontend/e2e/chat-session.spec.ts`
  - authenticated chat access
  - twin profile bootstrap
  - send message
  - restore session after reload
- `frontend/e2e/admin-auth.spec.ts`
  - invalid admin key rejection
  - valid admin sign-in and admin access

## Detailed Workflow

### Standard cycle

1. Start from the isolated test stack workflow.
2. Run:

```bash
make test-all-isolated
```

3. If everything passes, the cycle is complete.
4. If anything fails, record the failure in the findings table below using:
   - command
   - failing suite/test name
   - observed error
   - root-cause notes
5. Fix the smallest sensible batch.
6. Re-run the most targeted failing command first.
7. After the targeted rerun passes, re-run the full cycle again:

```bash
make test-all-isolated
```

8. Repeat until the full isolated run is green.

### Manual browser fallback

Only use manual browser actions when one of these is true:

- the issue is not covered by any current Playwright spec
- Playwright fails but the browser trace is not enough to understand the product problem
- a new UX path was added and has not been automated yet

Allowed tools:

- `agent-browser` first
- browser MCP / Playwright trace inspection as fallback

Required follow-up:

- if the manual run reveals a real defect in an existing product path, convert that path into an automated test before marking it fixed

## Operational Commands

Fresh isolated stack:

```bash
make e2e-down-v
make e2e-up-build
```

Inspect isolated namespace only:

```bash
docker compose -p proxymind-e2e -f docker-compose.yml -f docker-compose.e2e.yml ps
docker compose -p proxymind-e2e -f docker-compose.yml -f docker-compose.e2e.yml logs -f api-e2e
```

Seed isolated browser/API baseline:

```bash
make e2e-seed
```

`make e2e-seed` MUST wait for `api-e2e` health before running the seed script. The seed step is not allowed to race the API startup/migration path on a fresh stack.

Full isolated regression:

```bash
make test-all-isolated
```

Targeted browser-only rerun:

```bash
make test-e2e-isolated
```

## Findings

| ID | Status | Command / Suite | Failure | Root cause | Fix | Test added or updated |
| --- | --- | --- | --- | --- | --- | --- |
| none | clear | — | No open findings at the moment. | — | — | — |

## Notes

- Browser coverage is still mandatory, but the browser run should come from Playwright first, not from manual replay.
- Backend verification stays inside Docker containers only.
- The isolated stack is the default regression environment for this loop.
- The isolated stack MUST stay in its own Docker Compose project namespace so `down -v` and log/debug commands do not touch the default dev stack.
- The isolated API host port SHOULD stay separate from the legacy pre-namespace default (`8001`). The default for the namespaced stack is `18001`, overridable via `E2E_API_HOST_PORT`.
- Local runs may reuse the isolated stack for speed; CI should recreate it from scratch.
- `openspec validate --specs` still fails repo-wide because canonical specs do not yet use the validator's required template. Treat that as baseline repo state unless a separate story migrates the spec corpus.
