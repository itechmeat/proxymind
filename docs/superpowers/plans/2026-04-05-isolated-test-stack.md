# Isolated Test Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run backend integration and browser E2E tests against an isolated hybrid Docker stack that does not touch normal development data and does not share the default Docker Compose project namespace.

**Architecture:** Keep the default compose file for normal development and add a dedicated E2E override with isolated services. Route Playwright and backend pytest through those services inside a separate Compose project namespace, and bind the isolated API to its own host port to avoid collisions with legacy local stacks. Local runs reuse the stack by default, while CI keeps a fresh lifecycle for determinism.

**Tech Stack:** Docker Compose, FastAPI, pytest, Bun, Playwright, Vite, Make

---

## File Map

- Create: `docker-compose.e2e.yml` — isolated test services and data boundaries
- Create: `frontend/e2e/stack.ts` — shared compose/runtime settings for Playwright isolated stack
- Create: `frontend/e2e/stack.test.ts` — unit tests for stack lifecycle/config logic
- Modify: `frontend/playwright.config.ts` — point browser tests at isolated API URL
- Modify: `frontend/e2e/global-setup.ts` — isolated stack startup and CI reset logic
- Create: `frontend/e2e/global-teardown.ts` — optional stack teardown in CI
- Modify: `frontend/e2e/helpers/user-flows.ts` — read logs/admin key from `api-e2e`
- Modify: `frontend/package.json` — add isolated test scripts if needed
- Modify: `frontend/vitest.config.ts` — include targeted E2E harness unit tests
- Modify: `docker-compose.e2e.yml` — bind isolated API on a dedicated host port
- Modify: `Makefile` — add isolated stack and isolated test targets with a dedicated Compose project name

## Tasks

### Task 1: Add failing tests for E2E stack lifecycle helpers

- [ ] Add unit tests for compose-file args, dedicated Compose project namespace, backend URL selection, and CI/local reset policy
- [ ] Run the targeted test and confirm it fails because the helper does not exist
- [ ] Implement the minimal helper module used by Playwright setup
- [ ] Re-run the targeted test and confirm it passes

### Task 2: Add isolated Docker override

- [ ] Create `docker-compose.e2e.yml` with isolated services for API/runtime and pytest
- [ ] Give API runtime and pytest separate Postgres DB names, Redis services, Qdrant collections, and SeaweedFS roots
- [ ] Validate the merged compose config

### Task 3: Route Playwright through the isolated stack

- [ ] Update Playwright config to use the isolated API URL
- [ ] Update global setup/teardown to apply hybrid lifecycle semantics
- [ ] Update helpers to read logs/admin key from `api-e2e`
- [ ] Run the targeted E2E harness tests and then the browser suite

### Task 4: Add isolated test entrypoints

- [ ] Add Make targets for isolated stack lifecycle and isolated test runs
- [ ] Ensure isolated Make targets use a dedicated Compose project namespace separate from default dev
- [ ] Ensure isolated API host-port binding is dedicated and configurable so namespaced E2E runs do not collide with legacy containers
- [ ] Ensure `e2e-seed` waits for healthy `api-e2e` before running the seed script on fresh volumes
- [ ] Ensure backend pytest runs only inside `backend-test-e2e`
- [ ] Ensure Playwright can be run independently or as part of a combined isolated test flow

### Task 5: Verify end to end

- [ ] Re-read `docs/development.md` and self-review the change
- [ ] Verify dependency floors in `docs/spec.md`
- [ ] Run compose config validation
- [ ] Run backend pytest via `backend-test-e2e`
- [ ] Run frontend Vitest
- [ ] Run Playwright against the isolated stack
