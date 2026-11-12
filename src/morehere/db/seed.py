"""Load the source registry (config/sources.yaml) into the database.

Run with `make seed`. Safe to run repeatedly: sources are upserted by source_id.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import Engine

from morehere.db.repo import upsert_source
from morehere.db.session import make_engine, session_scope
from morehere.models import Source

DEFAULT_SOURCES_PATH = Path(__file__).resolve().parents[3] / "config" / "sources.yaml"


def load_sources(path: Path = DEFAULT_SOURCES_PATH) -> list[Source]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [Source.model_validate(item) for item in data["sources"]]


def seed_sources(engine: Engine, path: Path = DEFAULT_SOURCES_PATH) -> int:
    sources = load_sources(path)
    with session_scope(engine) as session:
        for source in sources:
            upsert_source(session, source)
    return len(sources)


def main() -> None:
    engine = make_engine()
    count = seed_sources(engine)
    print(f"Seeded {count} sources.")


if __name__ == "__main__":
    main()
