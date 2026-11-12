# Decisions

One entry per decision: what we chose, what we rejected and why, and where the AI got it wrong.

## M1 · Extraction output is a separate `ListingDraft`

- **Chose:** extraction returns a `ListingDraft` where every field is an `ExtractedField` (value + evidence, or flagged + reason). Code and curators turn drafts into `Listing`s with plain values and a `field_evidence` map.
- **Rejected:** one `Listing` model with `ExtractedField`s everywhere. It would push "is this field grounded?" checks into the API and the app, which should only ever see accepted values.

## M1 · The LLM extracts `recurrence_text`, not an RRULE

- **Chose:** the draft holds the verbatim phrase ("jeden 2. Donnerstag im Monat") plus `start_time`; `recurrence.py` (milestone 4) turns it into an RRULE.
- **Rejected:** asking the LLM for the RRULE directly. It is a decision about the schedule, and rule 1 says code decides. A parser can also be unit-tested exhaustively; an LLM can't.

## M1 · Ambiguous districts are flagged, not guessed

- **Chose:** `config/munich.yaml` lists aliases per Stadtbezirk; "Giesing" and "Schwabing" map to two districts each, so a draft that only says "Giesing" gets a flagged district. Geo lookup from the address (milestone 3) can resolve it later.
- **Rejected:** picking the more likely district. A wrong district silently breaks "near me" for exactly the newcomers who can't tell.

## M1 · Invented venues in the dataset

- **Chose:** invented organisers and venues on real Munich streets; `.example` domains for URLs and emails.
- **Rejected:** real venues with made-up schedules. Test data has a habit of leaking into demos, and a false schedule at a real café would mislead people.

## M1 · Python 3.12 (not 3.13)

- **Chose:** `requires-python = ">=3.12,<3.13"` as a conservative default: mature, and it has the `class Foo[T]` generics syntax used in `models.py`.
- **Rejected:** 3.13 for now. It would probably work too; revisit once the database and geo libraries are added and we can check them against it.
