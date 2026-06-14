PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
COMPOSE ?= docker compose
export PYTHONPATH := apps/api:packages/shared:packages/worker

.PHONY: venv web-deps lint test test-integration compose-up compose-down migrate qa-smoke verify clean

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

compose-up:
	$(COMPOSE) up -d --build

compose-down:
	$(COMPOSE) down --remove-orphans

migrate: venv
	DATABASE_URL=$${DATABASE_URL:-postgresql+psycopg://contextsmith:contextsmith@localhost:55432/contextsmith} $(BIN)/alembic upgrade head

qa-smoke: venv compose-up
	$(BIN)/python scripts/wait_for_http.py http://localhost:18000/readyz 120
	$(BIN)/python scripts/wait_for_http.py http://localhost:13000/api/health 120
	$(BIN)/python scripts/qa_smoke.py

verify: lint test compose-up migrate test-integration qa-smoke

clean:
	rm -rf $(VENV) .pytest_cache .ruff_cache
