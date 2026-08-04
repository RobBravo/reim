# REIM developer commands.
#
#   make setup      create the virtualenv and install everything
#   make check      lint + typecheck + tests (what CI runs)
#
# Container commands use docker by default; set CONTAINER_ENGINE=podman to use
# podman instead.

.DEFAULT_GOAL := help
SHELL := /bin/bash

VENV ?= .venv
PYTHON ?= $(VENV)/bin/python
PIP ?= $(VENV)/bin/pip
CONTAINER_ENGINE ?= docker
COMPOSE ?= $(CONTAINER_ENGINE) compose

# Local PostgreSQL used by integration tests (separate from docker compose).
TEST_DB_CONTAINER ?= reim-test-postgres
TEST_DB_PORT ?= 55432
TEST_DATABASE_URL ?= postgresql+psycopg://reim:reim@localhost:$(TEST_DB_PORT)/reim

PIPELINE ?=

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------
.PHONY: setup
setup: ## Create the virtualenv and install dependencies
	python3.12 -m venv $(VENV) 2>/dev/null || python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"
	@test -f .env || cp .env.example .env
	@echo "Environment ready. Next: make db-up && make migrate && make seed"

.PHONY: clean
clean: ## Remove caches and build artefacts
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage dist build
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

# --------------------------------------------------------------------------
# Docker Compose stack
# --------------------------------------------------------------------------
.PHONY: up
up: ## Start PostgreSQL and the API
	$(COMPOSE) up --build -d
	@echo "API: http://localhost:$${REIM_API_PORT:-8000}/docs"

.PHONY: down
down: ## Stop the stack (data volume is kept)
	$(COMPOSE) down

.PHONY: down-volumes
down-volumes: ## Stop the stack and delete the database volume
	$(COMPOSE) down --volumes

.PHONY: logs
logs: ## Follow stack logs
	$(COMPOSE) logs -f

.PHONY: ps
ps: ## Show stack status
	$(COMPOSE) ps

.PHONY: build
build: ## Build the API image
	$(COMPOSE) build

# --------------------------------------------------------------------------
# Standalone database for local development and tests
# --------------------------------------------------------------------------
.PHONY: db-up
db-up: ## Start a standalone PostgreSQL 16 for tests (port $(TEST_DB_PORT))
	@$(CONTAINER_ENGINE) start $(TEST_DB_CONTAINER) 2>/dev/null || \
	$(CONTAINER_ENGINE) run -d --name $(TEST_DB_CONTAINER) \
		-e POSTGRES_USER=reim -e POSTGRES_PASSWORD=reim -e POSTGRES_DB=reim \
		-p $(TEST_DB_PORT):5432 postgres:16-alpine
	@echo "Waiting for PostgreSQL..."
	@for i in $$(seq 1 30); do \
		$(CONTAINER_ENGINE) exec $(TEST_DB_CONTAINER) pg_isready -U reim -d reim >/dev/null 2>&1 && break; \
		sleep 1; \
	done
	@echo "Ready. export REIM_TEST_DATABASE_URL=$(TEST_DATABASE_URL)"

.PHONY: db-down
db-down: ## Remove the standalone test database
	-$(CONTAINER_ENGINE) rm -f $(TEST_DB_CONTAINER)

# --------------------------------------------------------------------------
# Database schema and data
# --------------------------------------------------------------------------
.PHONY: migrate
migrate: ## Apply migrations to head
	$(VENV)/bin/alembic upgrade head

.PHONY: migrate-down
migrate-down: ## Roll back one migration
	$(VENV)/bin/alembic downgrade -1

.PHONY: migrate-check
migrate-check: ## Fail if the models have drifted from the migrations
	$(VENV)/bin/alembic upgrade head
	$(VENV)/bin/alembic check

.PHONY: revision
revision: ## Autogenerate a migration: make revision MESSAGE="add x"
	$(VENV)/bin/alembic revision --autogenerate -m "$(MESSAGE)"

.PHONY: seed
seed: ## Seed countries, organizations, indicators and catalog sources
	$(PYTHON) -m reim.cli db seed

# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------
.PHONY: run-api
run-api: ## Run the API locally with reload
	$(VENV)/bin/uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: run-pipeline
run-pipeline: ## Run one pipeline: make run-pipeline PIPELINE=worldbank_ni_cpi_inflation
	@test -n "$(PIPELINE)" || { echo "Usage: make run-pipeline PIPELINE=<key>"; exit 2; }
	$(PYTHON) -m reim.cli pipeline run $(PIPELINE)

.PHONY: run-all-pipelines
run-all-pipelines: ## Run every enabled pipeline
	$(PYTHON) -m reim.cli pipeline run-all

.PHONY: catalog-validate
catalog-validate: ## Validate the source catalog and quality rules
	$(PYTHON) -m reim.cli catalog validate

.PHONY: quality-report
quality-report: ## Summarise recent quality failures
	$(PYTHON) -m reim.cli quality report

# --------------------------------------------------------------------------
# Quality gates
# --------------------------------------------------------------------------
.PHONY: test
test: ## Run the full test suite (integration tests need db-up)
	REIM_TEST_DATABASE_URL=$${REIM_TEST_DATABASE_URL:-$(TEST_DATABASE_URL)} \
		$(PYTHON) -m pytest

.PHONY: test-unit
test-unit: ## Run unit tests only (no database required)
	$(PYTHON) -m pytest tests/unit

.PHONY: test-cov
test-cov: ## Run tests with a coverage report
	REIM_TEST_DATABASE_URL=$${REIM_TEST_DATABASE_URL:-$(TEST_DATABASE_URL)} \
		$(PYTHON) -m pytest --cov --cov-report=term-missing --cov-report=html

.PHONY: lint
lint: ## Run Ruff (lint + format check)
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

.PHONY: format
format: ## Auto-fix lint issues and format
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

.PHONY: typecheck
typecheck: ## Run MyPy in strict mode
	$(VENV)/bin/mypy reim apps

.PHONY: check
check: lint typecheck catalog-validate test ## Everything CI runs

.PHONY: smoke
smoke: ## Hit the real official sources (opt-in, makes live network calls)
	$(PYTHON) scripts/smoke_test_sources.py
