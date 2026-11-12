.PHONY: setup test test-db lint format db db-down db-reset migrate seed

setup:
	uv sync

# All tests; database tests are skipped if Postgres is not running.
test:
	uv run pytest

# Database tests only; fail (not skip) if Postgres is not running.
test-db:
	MOREHERE_REQUIRE_DB=1 uv run pytest -m db

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

# Local Postgres 16 + PostGIS + pgvector (docker-compose.yml)
db:
	docker compose up -d --build --wait db

db-down:
	docker compose down

# Deletes all local data.
db-reset:
	docker compose down -v
	docker compose up -d --build --wait db

migrate:
	uv run alembic upgrade head

seed:
	uv run python -m morehere.db.seed
