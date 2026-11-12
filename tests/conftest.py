"""Shared fixtures for database tests.

Database tests run against TEST_DATABASE_URL (default: the morehere_test database that
docker-compose creates). If Postgres is not reachable they are skipped, unless
MOREHERE_REQUIRE_DB=1 (set by `make test-db` and CI), in which case they fail.

Each test runs inside a transaction that is rolled back afterwards, so tests never see
each other's data.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from morehere.db.repo import upsert_source
from morehere.db.seed import load_sources
from morehere.db.session import make_engine

REPO_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://morehere:morehere@localhost:5432/morehere_test"
)
REQUIRE_DB = os.environ.get("MOREHERE_REQUIRE_DB") == "1"


def _alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.attributes["database_url"] = TEST_DATABASE_URL
    return config


@pytest.fixture
def alembic_config() -> Config:
    return _alembic_config()


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    engine = make_engine(TEST_DATABASE_URL)
    try:
        with engine.connect():
            pass
    except OperationalError as exc:
        message = (
            f"Postgres not reachable at {TEST_DATABASE_URL} ({type(exc).__name__}); "
            "start it with `make db`"
        )
        if REQUIRE_DB:
            pytest.fail(message)
        pytest.skip(message)

    # Start from an empty database so the migrations are tested from scratch every run.
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    command.upgrade(_alembic_config(), "head")

    yield engine
    engine.dispose()


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back after the test, with the source registry loaded."""
    with db_engine.connect() as connection:
        transaction = connection.begin()
        # Commits inside the test become savepoints; the outer transaction is rolled back.
        db_session = Session(bind=connection, join_transaction_mode="create_savepoint")
        for source in load_sources():
            upsert_source(db_session, source)
        db_session.flush()
        try:
            yield db_session
        finally:
            db_session.close()
            transaction.rollback()
