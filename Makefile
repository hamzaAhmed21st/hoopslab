.PHONY: sync check format test test-unit source-validate ingest quality features develop-model lock-model evaluate-model verify-model api frontend-sync frontend frontend-check stack-up db-up db-down migrate

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

ingest:
	uv run python scripts/ingest.py

quality:
	uv run python scripts/data_quality.py

features:
	uv run python scripts/build_features.py

develop-model:
	uv run python scripts/develop_model.py

lock-model:
	uv run python scripts/lock_model.py

evaluate-model:
	uv run python scripts/evaluate_model.py

verify-model:
	uv run python scripts/verify_model.py

api:
	uv run uvicorn hoopslab.api.app:app --host 0.0.0.0 --port 8000

frontend-sync:
	cd frontend && CI=true pnpm install --frozen-lockfile

frontend:
	cd frontend && pnpm dev

frontend-check:
	cd frontend && CI=true pnpm lint
	cd frontend && CI=true pnpm typecheck
	cd frontend && CI=true pnpm test
	cd frontend && CI=true pnpm build

stack-up:
	docker compose up --build --wait

db-up:
	docker compose up -d --wait db

db-down:
	docker compose down

migrate:
	uv run alembic upgrade head
