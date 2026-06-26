PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
COMPOSE ?= docker compose
ifneq (,$(wildcard .env))
include .env
export
endif
SOURCEBRIEF_API_PORT ?= $(or $(CONTEXTSMITH_API_PORT),18000)
SOURCEBRIEF_WEB_PORT ?= $(or $(CONTEXTSMITH_WEB_PORT),13000)
SOURCEBRIEF_POSTGRES_PORT ?= $(or $(CONTEXTSMITH_POSTGRES_PORT),55432)
POSTGRES_USER ?= sourcebrief
POSTGRES_PASSWORD ?= sourcebrief
POSTGRES_DB ?= sourcebrief
API_URL ?= http://localhost:$(SOURCEBRIEF_API_PORT)
WEB_URL ?= http://localhost:$(SOURCEBRIEF_WEB_PORT)
DATABASE_URL ?= $(if $(SOURCEBRIEF_DATABASE_URL),$(SOURCEBRIEF_DATABASE_URL),$(if $(CONTEXTSMITH_DATABASE_URL),$(CONTEXTSMITH_DATABASE_URL),postgresql+psycopg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:$(SOURCEBRIEF_POSTGRES_PORT)/$(POSTGRES_DB)))
export PYTHONPATH := apps/api:packages/shared:packages/worker

.PHONY: help quickstart-doctor quickstart-ready print-api-url print-web-url venv web-deps lint typecheck test test-integration compose-up compose-down compose-ps compose-logs migrate migrate-compose qa-smoke alpha-eval collect-e2e-evidence release-gate verify clean prepare-qa-fixtures

help:
	@printf 'SourceBrief common commands\n\n'
	@printf '  make compose-up             Build/start API, workers, web, Postgres, and Redis\n'
	@printf '  make quickstart-doctor      Check quickstart prerequisites and remote browser config\n'
	@printf '  make quickstart-ready       Wait for API and web health using .env ports\n'
	@printf '  make compose-down           Stop local services and remove orphan containers\n'
	@printf '  make compose-ps             Show local service status\n'
	@printf '  make compose-logs           Tail API, worker, and frontend logs\n'
	@printf '  make migrate                Run Alembic migrations from the host venv\n'
	@printf '  make lint                   Python lint plus frontend typecheck\n'
	@printf '  make typecheck              Backend mypy plus frontend typecheck\n'
	@printf '  make test                   Unit tests\n'
	@printf '  make test-integration       Integration tests against real services\n'
	@printf '  make qa-smoke               Run the real API/worker/frontend smoke flow\n'
	@printf '  make alpha-eval             Run natural-language alpha retrieval eval\n'
	@printf '  make collect-e2e-evidence   Write a redacted launch evidence bundle under artifacts/e2e/\n'
	@printf '  make verify                 Full local acceptance/release gate\n'
	@printf '  make clean                  Remove local Python/tool caches\n'

quickstart-doctor:
	python3 scripts/check_quickstart_prereqs.py

quickstart-ready:
	python3 scripts/wait_for_http.py http://localhost:$(SOURCEBRIEF_API_PORT)/readyz 120
	python3 scripts/wait_for_http.py http://localhost:$(SOURCEBRIEF_WEB_PORT)/api/health 120

print-api-url:
	@printf 'http://localhost:%s\n' '$(SOURCEBRIEF_API_PORT)'

print-web-url:
	@printf 'http://localhost:%s\n' '$(SOURCEBRIEF_WEB_PORT)'

venv:
	uv venv --python 3.11 --allow-existing $(VENV)
	uv pip install --python $(BIN)/python -e '.[dev]'

web-deps:
	npm --prefix apps/web install

lint: venv web-deps
	$(BIN)/ruff check apps packages tests scripts
	npm --prefix apps/web run lint

typecheck: venv web-deps
	$(BIN)/python -m mypy apps packages scripts --ignore-missing-imports --follow-imports=silent
	npm --prefix apps/web run lint

test: venv
	$(BIN)/pytest tests/unit -q

test-integration: venv
	SOURCEBRIEF_DEV_AUTH=true $(BIN)/pytest tests/integration -q

prepare-qa-fixtures:
	mkdir -p tmp/qa-git-fixtures

compose-up: prepare-qa-fixtures
	$(COMPOSE) up -d --build

compose-down:
	$(COMPOSE) down --remove-orphans

compose-ps:
	$(COMPOSE) ps

compose-logs:
	$(COMPOSE) logs --tail=200 api worker-default worker-maintenance frontend

migrate: venv
	DATABASE_URL=$(DATABASE_URL) $(BIN)/alembic upgrade head

migrate-compose: compose-up
	$(COMPOSE) exec -T api alembic upgrade head

qa-smoke: venv compose-up
	$(BIN)/python scripts/wait_for_http.py $(API_URL)/readyz 120
	$(BIN)/python scripts/wait_for_http.py $(WEB_URL)/api/health 120
	API_URL=$(API_URL) WEB_URL=$(WEB_URL) SOURCEBRIEF_API_URL=$(API_URL) SOURCEBRIEF_WEB_URL=$(WEB_URL) $(BIN)/python scripts/qa_smoke.py

alpha-eval: venv compose-up
	$(BIN)/python scripts/wait_for_http.py $(API_URL)/readyz 120
	API_URL=$(API_URL) SOURCEBRIEF_API_URL=$(API_URL) $(BIN)/python scripts/alpha_eval.py

collect-e2e-evidence: venv
	$(BIN)/python scripts/collect_e2e_evidence.py

release-gate:
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) test
	$(MAKE) compose-up
	$(MAKE) migrate
	$(MAKE) migrate-compose
	$(MAKE) test-integration
	$(MAKE) qa-smoke
	$(MAKE) alpha-eval

verify: release-gate

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache
