PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
COMPOSE ?= docker compose
ifneq (,$(wildcard .env))
include .env
export
endif
CONTEXTSMITH_API_PORT ?= 18000
CONTEXTSMITH_WEB_PORT ?= 13000
CONTEXTSMITH_POSTGRES_PORT ?= 55432
POSTGRES_USER ?= contextsmith
POSTGRES_PASSWORD ?= contextsmith
POSTGRES_DB ?= contextsmith
API_URL ?= http://localhost:$(CONTEXTSMITH_API_PORT)
WEB_URL ?= http://localhost:$(CONTEXTSMITH_WEB_PORT)
DATABASE_URL ?= $(if $(CONTEXTSMITH_DATABASE_URL),$(CONTEXTSMITH_DATABASE_URL),postgresql+psycopg://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:$(CONTEXTSMITH_POSTGRES_PORT)/$(POSTGRES_DB))
export PYTHONPATH := apps/api:packages/shared:packages/worker

.PHONY: venv web-deps lint test test-integration compose-up compose-down compose-ps compose-logs migrate migrate-compose qa-smoke verify clean prepare-qa-fixtures

venv:
	uv venv --python 3.11 --allow-existing $(VENV)
	uv pip install --python $(BIN)/python -e '.[dev]'

web-deps:
	npm --prefix apps/web install

lint: venv web-deps
	$(BIN)/ruff check apps packages tests scripts
	npm --prefix apps/web run lint

test: venv
	$(BIN)/pytest tests/unit -q

test-integration: venv
	$(BIN)/pytest tests/integration -q

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
	API_URL=$(API_URL) WEB_URL=$(WEB_URL) CONTEXTSMITH_API_URL=$(API_URL) CONTEXTSMITH_WEB_URL=$(WEB_URL) $(BIN)/python scripts/qa_smoke.py

verify: lint test compose-up migrate migrate-compose test-integration qa-smoke

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache
