.DEFAULT_GOAL := help

DOCKER_COMPOSE ?= docker compose
E2E_DOCKER_PROJECT ?= proxymind-e2e
E2E_API_HOST_PORT ?= 18001
E2E_TEST_PASSWORD ?= $(shell sed -n 's/^E2E_TEST_PASSWORD=//p' .env 2>/dev/null | head -n 1)
E2E_DOCKER_COMPOSE ?= docker compose -p $(E2E_DOCKER_PROJECT) -f docker-compose.yml -f docker-compose.e2e.yml
GIT_COMMIT_SHA ?= $(shell git rev-parse HEAD 2>/dev/null || echo unknown)
LOG_TAIL ?= 200
SERVICE ?=
SERVICES ?=
BACKEND_CMD ?=
EVAL_ARGS ?=

export GIT_COMMIT_SHA
export E2E_DOCKER_PROJECT
export E2E_API_HOST_PORT
export E2E_TEST_PASSWORD

.PHONY: help start up up-build stop down down-v restart ps logs build pull config e2e-up e2e-up-build e2e-down e2e-down-v e2e-ps e2e-logs e2e-seed backend-exec-isolated evals-isolated test-backend-isolated test-frontend-isolated test-e2e-isolated test-all-isolated

help: ## Show available targets
	@grep -E '^[a-zA-Z0-9_.-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

start: up ## Alias for `make up`

up: ## Start the Docker Compose stack in detached mode
	$(DOCKER_COMPOSE) up -d $(SERVICES)

up-build: ## Build changed images and start the stack in detached mode
	$(DOCKER_COMPOSE) up -d --build $(SERVICES)

stop: down ## Alias for `make down`

down: ## Stop and remove containers
	$(DOCKER_COMPOSE) down

down-v: ## Stop and remove containers, networks, and named volumes
	$(DOCKER_COMPOSE) down -v

restart: ## Restart the stack
	$(DOCKER_COMPOSE) down
	$(DOCKER_COMPOSE) up -d $(SERVICES)

ps: ## Show current container status
	$(DOCKER_COMPOSE) ps

logs: ## Follow logs. Optional: make logs SERVICE=api
	$(DOCKER_COMPOSE) logs -f --tail=$(LOG_TAIL) $(SERVICE)

build: ## Build services. Optional: make build SERVICES="api worker"
	$(DOCKER_COMPOSE) build $(SERVICES)

pull: ## Pull non-built images declared in compose
	$(DOCKER_COMPOSE) pull $(SERVICES)

config: ## Validate docker compose configuration
	$(DOCKER_COMPOSE) config --quiet

e2e-up: ## Start isolated test stack in detached mode
	$(E2E_DOCKER_COMPOSE) up -d $(if $(SERVICES),$(SERVICES),api-e2e backend-test-e2e)

e2e-up-build: ## Build changed images and start isolated test stack
	$(E2E_DOCKER_COMPOSE) up -d --build $(if $(SERVICES),$(SERVICES),api-e2e backend-test-e2e)

e2e-down: ## Stop and remove isolated test stack containers
	$(E2E_DOCKER_COMPOSE) down

e2e-down-v: ## Stop isolated test stack and remove named volumes
	$(E2E_DOCKER_COMPOSE) down -v --remove-orphans

e2e-ps: ## Show isolated test stack status
	$(E2E_DOCKER_COMPOSE) ps

e2e-logs: ## Follow isolated test stack logs. Optional: make e2e-logs SERVICE=api-e2e
	$(E2E_DOCKER_COMPOSE) logs -f --tail=$(LOG_TAIL) $(SERVICE)

e2e-seed: ## Seed the isolated API stack with a minimal active snapshot
	$(E2E_DOCKER_COMPOSE) up -d --build --wait api-e2e
	$(E2E_DOCKER_COMPOSE) exec -T api-e2e python -m app.scripts.seed_isolated_test_stack

backend-exec-isolated: ## Run an arbitrary command in the isolated backend test runner. Usage: make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_x.py -v"
	@test -n "$(BACKEND_CMD)" || (echo 'BACKEND_CMD is required. Example: make backend-exec-isolated BACKEND_CMD="python -m pytest tests/unit/test_x.py -v"' >&2; exit 1)
	$(E2E_DOCKER_COMPOSE) up -d --build backend-test-e2e
	$(E2E_DOCKER_COMPOSE) exec -T backend-test-e2e sh -c "$(BACKEND_CMD)"

evals-isolated: ## Run evals against the isolated API stack. Optional: make evals-isolated EVAL_ARGS="--help"
	$(E2E_DOCKER_COMPOSE) up -d --build --wait api-e2e
	$(E2E_DOCKER_COMPOSE) up -d --build backend-test-e2e
	$(E2E_DOCKER_COMPOSE) exec -T backend-test-e2e sh -c "python -m evals.run_evals $(EVAL_ARGS)"

test-backend-isolated: ## Run backend unit and integration tests on isolated services
	$(E2E_DOCKER_COMPOSE) up -d --build backend-test-e2e
	$(E2E_DOCKER_COMPOSE) exec -T backend-test-e2e python -m pytest tests/unit tests/integration -q

test-frontend-isolated: ## Run frontend Vitest suite
	cd frontend && bun run test

test-e2e-isolated: ## Run Playwright against isolated services
	$(MAKE) e2e-seed
	cd frontend && E2E_DOCKER_PROJECT=$(E2E_DOCKER_PROJECT) E2E_API_HOST_PORT=$(E2E_API_HOST_PORT) E2E_TEST_PASSWORD=$(E2E_TEST_PASSWORD) bun run test:e2e

test-all-isolated: ## Run backend pytest, frontend Vitest, and Playwright with isolated services
	$(MAKE) test-backend-isolated
	$(MAKE) test-frontend-isolated
	$(MAKE) test-e2e-isolated
