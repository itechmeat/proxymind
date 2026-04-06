# Isolated Test Stack Design

## Goal

Move integration and browser testing onto an isolated hybrid test stack that never touches the default development data plane.

## Scope

This design covers:

- isolated Docker services for test execution
- backend pytest execution against isolated stores
- Playwright execution against isolated API/runtime services
- local reuse of the test stack for speed
- always-fresh lifecycle in CI for determinism

This design does not change production deployment topology.

## Architecture

The repository will keep the current `docker-compose.yml` for normal development and add a dedicated `docker-compose.e2e.yml` override for isolated test infrastructure.

The isolated stack MUST run under a separate Docker Compose project namespace, defaulting to `proxymind-e2e`. This is required so stack lifecycle commands (`up`, `down -v`, `ps`, `logs`) do not accidentally target the default development project even when both stacks are present on the same machine.

The isolated API SHOULD also use a dedicated host port, defaulting to `18001`, instead of reusing the legacy pre-namespace port `8001`. Docker project namespaces do not isolate host-port bindings, so the dedicated port prevents collisions with older local E2E containers that may still be present.

The isolated stack will use dedicated services and data boundaries:

- `postgres-e2e`
- `redis-e2e`
- `redis-test-e2e`
- `qdrant-e2e`
- `seaweedfs-e2e`
- `api-e2e`
- `backend-test-e2e`

Isolation rules:

- browser tests talk only to `api-e2e`
- `api-e2e` talks only to `postgres-e2e`, `redis-e2e`, `qdrant-e2e`, and `seaweedfs-e2e`
- backend pytest runs only inside `backend-test-e2e`
- `backend-test-e2e` uses its own database, Redis instance, Qdrant collection, and SeaweedFS root path
- the default `api`, `postgres`, `redis`, `qdrant`, and `seaweedfs` services remain untouched for normal development

## Data Boundaries

The stack will avoid cross-suite collisions without cloning every service twice when that is unnecessary:

- PostgreSQL: one `postgres-e2e` service with separate databases for API runtime and pytest
- Redis: separate services for API and pytest because the current app hardcodes Redis DB `0`
- Qdrant: one `qdrant-e2e` service with separate collections for API runtime and pytest
- SeaweedFS: one `seaweedfs-e2e` service with separate filer root paths for API runtime and pytest

This keeps the stack smaller while preserving effective isolation.

## Lifecycle

Hybrid mode:

- local runs reuse the isolated stack by default
- CI always recreates the isolated stack from scratch and tears it down with volumes
- both modes operate inside the dedicated `proxymind-e2e` Compose project namespace
- both modes use the dedicated isolated API host port unless `E2E_API_HOST_PORT` overrides it explicitly

Playwright global setup/teardown will enforce that lifecycle for browser runs. Make targets will provide the same lifecycle for backend pytest and combined isolated runs.

The seed workflow MUST wait for `api-e2e` to become healthy before executing `seed_isolated_test_stack`. A simple detached `up` is insufficient on a fresh volume set because schema migration and application startup may still be in progress.

## Verification

The implementation must prove:

- Playwright uses `api-e2e`, not the default `api`
- backend pytest uses `backend-test-e2e`, not the default `backend-test`
- isolated compose commands operate inside the dedicated `proxymind-e2e` namespace
- isolated API host-port binding defaults to `18001`, not the legacy `8001`
- CI-mode setup resets the isolated stack
- local-mode setup reuses it
- all existing backend unit/integration tests still pass against the isolated test stack
- Playwright auth/chat/admin journeys still pass against the isolated stack
