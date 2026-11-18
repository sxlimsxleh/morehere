"""Write the API's OpenAPI schema to app/openapi.json (the Expo app's types come from it).

    python -m morehere.api.export_openapi            # write
    python -m morehere.api.export_openapi --check    # fail if the committed file is stale

Builds the app without connecting to a database.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine

from morehere.api.app import create_app

OPENAPI_PATH = Path(__file__).resolve().parents[3] / "app" / "openapi.json"


def openapi_json() -> str:
    # A never-connected engine: building the schema needs no database.
    app = create_app(engine=create_engine("postgresql+psycopg://unused@localhost/unused"))
    return json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    current = openapi_json()
    if args.check:
        if not OPENAPI_PATH.exists() or OPENAPI_PATH.read_text(encoding="utf-8") != current:
            sys.exit("app/openapi.json is out of date: run `make openapi`")
        print("app/openapi.json is up to date")
        return
    OPENAPI_PATH.write_text(current, encoding="utf-8")
    print(f"wrote {OPENAPI_PATH}")


if __name__ == "__main__":
    main()
