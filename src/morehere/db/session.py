"""Engine and session handling.

The database URL comes from the DATABASE_URL environment variable, with a default that
matches docker-compose.yml so `make db` + `make migrate` work without any setup.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://morehere:morehere@localhost:5432/morehere"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def make_engine(url: str | None = None) -> Engine:
    # pool_pre_ping: drop dead connections instead of failing the next query
    return create_engine(url or database_url(), pool_pre_ping=True)


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """One unit of work: commit if the block succeeds, roll back if it raises."""
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
