SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose -f deploy/compose/docker-compose.yml
BACKEND := backend
WEB := web
UV := uv --directory $(BACKEND)

.PHONY: help
help: ## List available targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_.-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# --- local stack -------------------------------------------------------------

.PHONY: up
up: ## Start the local stack (Postgres, Redis, MinIO, Keycloak) and wait until healthy
	$(COMPOSE) up -d --wait

.PHONY: down
down: ## Stop the local stack
	$(COMPOSE) down

.PHONY: reset
reset: ## Stop the local stack and delete its volumes
	$(COMPOSE) down -v

# --- backend -----------------------------------------------------------------

.PHONY: backend-install
backend-install: ## Install backend dependencies into backend/.venv
	$(UV) sync --frozen

.PHONY: browsers
browsers: ## Download the headless Chromium used by rendered-page tests and the browser worker
	$(UV) run playwright install chromium

.PHONY: backend-lint
backend-lint: ## Run ruff and import-linter on the backend
	$(UV) run ruff check src tests alembic
	$(UV) run ruff format --check src tests alembic
	$(UV) run lint-imports

.PHONY: backend-typecheck
backend-typecheck: ## Run mypy --strict on the backend
	$(UV) run mypy

.PHONY: backend-test
backend-test: ## Run backend unit tests (no external services)
	$(UV) run pytest -m "not integration"

.PHONY: backend-test-integration
backend-test-integration: ## Run backend integration tests (requires `make up`)
	$(UV) run pytest -m integration

.PHONY: backend-check
backend-check: backend-lint backend-typecheck backend-test openapi-check ## Lint, type-check, unit-test the backend and check API drift

.PHONY: migrate
migrate: ## Apply database migrations to the local stack
	$(UV) run alembic upgrade head

.PHONY: openapi
openapi: ## Regenerate the committed OpenAPI schema and web API types
	$(UV) run python -m pricing_assistant.openapi > $(WEB)/openapi.json
	cd $(WEB) && npm run gen:api

.PHONY: openapi-check
openapi-check: ## Fail if the committed OpenAPI schema or generated web types are out of date
	$(UV) run python -m pricing_assistant.openapi | diff -u $(WEB)/openapi.json - \
		|| (echo "OpenAPI schema drift: run 'make openapi'" && exit 1)
	cd $(WEB) && npx --no-install openapi-typescript openapi.json -o .schema-check.d.ts >/dev/null \
		&& { diff -u src/lib/api/schema.d.ts .schema-check.d.ts; status=$$?; rm -f .schema-check.d.ts; \
		     [ $$status -eq 0 ] || (echo "Web API types drift: run 'make openapi'" && exit 1); }

# --- web ---------------------------------------------------------------------

.PHONY: web-install
web-install: ## Install web dependencies
	cd $(WEB) && npm ci

.PHONY: web-check
web-check: ## Lint, type-check and unit-test the web app
	cd $(WEB) && npm run lint && npm run typecheck && npm test

.PHONY: e2e
e2e: ## Browser end-to-end tests against the local stack (needs `make up`; seeds pricing_e2e)
	cd $(WEB) && npx playwright test

# --- run ---------------------------------------------------------------------

.PHONY: demo
demo: ## Run the app on seeded demo data: web http://localhost:3000, API :8000 (needs `make up`)
	./deploy/scripts/demo.sh

# --- aggregate ---------------------------------------------------------------

.PHONY: test
test: backend-check backend-test-integration web-check ## Run all checks and tests
