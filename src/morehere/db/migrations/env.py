"""Alembic environment: runs migrations against DATABASE_URL (or a URL passed in config)."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from geoalchemy2 import alembic_helpers

from morehere.db.session import database_url, make_engine
from morehere.db.tables import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    # Only compare tables we define. PostGIS (and the postgis Docker image's tiger
    # geocoder and topology extensions) create tables of their own; leave them alone.
    if type_ == "table" and reflected and compare_to is None:
        return False
    return alembic_helpers.include_object(obj, name, type_, reflected, compare_to)


def run_migrations_online() -> None:
    # Tests pass their own URL via config attributes; otherwise use DATABASE_URL.
    url = config.attributes.get("database_url") or database_url()
    engine = make_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            process_revision_directives=alembic_helpers.writer,
            render_item=alembic_helpers.render_item,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (SQL script) migrations are not supported; run against a database.")
run_migrations_online()
