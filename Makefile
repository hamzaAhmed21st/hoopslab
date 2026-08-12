.PHONY: sync check format test test-unit source-validate db-up db-down migrate

sync:
	uv sync --locked --all-groups

check:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

format:
	uv run ruff check --fix .
	uv run ruff format .

test:
	HOOPSLAB_TEST_DATABASE_URL="$${HOOPSLAB_DATABASE_URL:-postgresql+psycopg://hoopslab:hoopslab@localhost:5432/hoopslab}" uv run pytest

test-unit:
	uv run pytest

source-validate:
	uv run python scripts/validate_source.py

db-up:
	docker compose up -d --wait db

db-down:
	docker compose down

migrate:
	uv run alembic upgrade head
