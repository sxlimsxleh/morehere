# morehere.

*Make more of this city yours.*

A scout that helps people new to Munich become a regular somewhere: it finds the recurring groups, work-friendly cafés and community spaces where the same faces show up week after week, and nudges you to keep going back.

**Status:** milestone 1 (foundations): data contracts, city config and a labelled dataset of messy Munich inputs. See [CLAUDE.md](CLAUDE.md) for the design rules and milestones.

## Run it

```bash
make setup   # uv sync
make test    # pytest
make lint    # ruff
```

## What's here

- `src/morehere/models.py`: the data contracts. "Grounded or flagged" and "no evidence, no tag" are enforced when objects are built.
- `config/munich.yaml`: everything city-specific (districts and aliases, freshness window, score weights, OSM tags).
- `data/raw/`: 24 invented but realistic inputs (iCal feeds, newsletters, venue pages, a pasted Instagram caption, a form submission, a prompt-injection attempt).
- `golden/labels.json`: the correct extraction for each input, with the verbatim source span for every value. `tests/test_dataset.py` checks every span really occurs in its file.

All organisers, venues and contacts in `data/raw/` are invented; street names are real, and URLs and emails use `.example` domains.
