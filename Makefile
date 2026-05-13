.PHONY: all install format test run deploy help migrate migrate-create migrate-up migrate-down

PY_FILES := $(shell git ls-files '*.py')
ALEMBIC := uv run alembic
PYTHON := uv run python
UVICORN := uv run uvicorn

all: help

install:
	@echo "Installing project dependencies (incl. dev tools)..."
	@uv sync --all-groups
	@uv run pre-commit install

format:
	@echo "Applying Ruff import sorting and style formatting..."
	@uv run ruff check --select I --fix .
	@uv run ruff format .

lint:
	@echo "Linting Python files..."
	@uv run ruff check .
	
run:
	$(UVICORN) app.main:app --reload --host 0.0.0.0 --port 8000

migrate-init:
	$(ALEMBIC) init alembic

migrate:
	@read -p "Enter migration message: " msg; \
	$(ALEMBIC) revision --autogenerate -m "$$msg"

upgrade:
	$(ALEMBIC) upgrade head

downgrade:
	$(ALEMBIC) downgrade -1

help:
	@echo "Thanos Makefile"
	@echo "----------------------"
	@echo "Available commands:"
	@echo "  install       - Install dependencies"
	@echo "  format        - Format Python code"
	@echo "  lint          - Lint Python code"
	@echo "  run           - Run the application"
	@echo "  migrate-init  - Initialize alembic migrations"
	@echo "  migrate       - Create a new migration"
	@echo "  upgrade       - Upgrade the database"
	@echo "  downgrade     - Downgrade the database"
	@echo "  help          - Show this help message"
