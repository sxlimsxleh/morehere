# morehere.

*Make more of this city yours.*

A scout that helps people new to Munich become a regular somewhere: it finds the recurring groups, work-friendly cafés and community spaces where the same faces show up week after week, and nudges you to keep going back.

**Status:** milestone 5 (extraction) done: Claude reads messy documents into listing drafts, code checks every value against a verbatim quote, and evals score it on 24 hand-labelled Munich documents: 99.6% field accuracy, no wrong values accepted, every flag right (claude-opus-5-5, effort medium, about 1.8 cents a document). Results in `evals/results/`.

## Run it

```bash
make setup     # uv sync
make db        # Postgres 16 + PostGIS + pgvector in Docker
make migrate   # create the tables
make seed      # load the source registry
make osm-districts  # Munich's 25 district boundaries from OpenStreetMap
make osm       # cafés, libraries, community centres, coworking, makerspaces, climbing
make ical-probe URL=https://...  # check what a calendar feed offers
make evals     # score extraction on the golden set (needs ANTHROPIC_API_KEY in .env)
make test      # all tests (database tests skip if Postgres isn't running)
```

Place data © OpenStreetMap contributors, available under the [ODbL](https://opendatacommons.org/licenses/odbl/).

## What's here

- `src/morehere/models.py`: the data contracts. "Grounded or flagged" and "no evidence, no tag" are enforced when objects are built.
- `src/morehere/db/`: tables, hand-written Alembic migrations, and `repo.py`, the only code that converts between Pydantic models and rows.
- `config/sources.yaml`: the source registry: every source with its legal status, licence, refresh schedule and reliability.
- `config/munich.yaml`: everything city-specific (districts and aliases, freshness window, score weights, OSM tags).
- `data/raw/`: 24 invented but realistic inputs (iCal feeds, newsletters, venue pages, a pasted Instagram caption, a form submission, a prompt-injection attempt).
- `golden/labels.json`: the correct extraction for each input, with the verbatim source span for every value. `tests/test_dataset.py` checks every span really occurs in its file.

All organisers, venues and contacts in `data/raw/` are invented; street names are real, and URLs and emails use `.example` domains.
