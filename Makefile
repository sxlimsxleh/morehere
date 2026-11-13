.PHONY: setup test test-db lint format db db-down db-reset migrate seed osm osm-districts osm-replay ical ical-probe extract-samples extract evals evals-recorded

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

# OpenStreetMap base layer (needs network access to overpass-api.de)
osm-districts:
	uv run python -m morehere.sources.osm districts

osm:
	uv run python -m morehere.sources.osm places

# Re-parse the latest stored OSM payload; no network.
osm-replay:
	uv run python -m morehere.sources.osm replay

# iCal feeds in the source registry (sources with kind=ical and a url)
ical:
	uv run python -m morehere.sources.ical ingest

# Check what a feed offers before adding it: make ical-probe URL=https://...
ical-probe:
	uv run python -m morehere.sources.ical probe "$(URL)"

# --- Extraction (milestone 5) ---------------------------------------------------
# Load data/raw/ samples into the database as raw records (for trying extraction).
extract-samples:
	uv run python -m morehere.extract samples

# Extract every raw record without drafts (needs ANTHROPIC_API_KEY in .env).
extract:
	uv run python -m morehere.extract run

# Live eval: calls the API, records responses, writes evals/results/.
# Optional: make evals EFFORT=low MODEL=claude-opus-5-5 TAG=baseline
evals:
	uv run python evals/run_evals.py --mode live $(if $(MODEL),--model $(MODEL)) $(if $(EFFORT),--effort $(EFFORT)) $(if $(TAG),--tag $(TAG))

# Replay recorded responses: no key, no network (CI).
evals-recorded:
	uv run python evals/run_evals.py --mode replay $(if $(MODEL),--model $(MODEL)) $(if $(EFFORT),--effort $(EFFORT)) $(if $(TAG),--tag $(TAG))
