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

## M2 · pgvector copied from its official image, not apt-installed

- **Chose:** a multi-stage Dockerfile that copies `vector.so` and its SQL files from `pgvector/pgvector:0.8.0-pg16` into `postgis/postgis:16-3.5`. The build needs no network beyond Docker Hub. Checked: `vector.so` needs glibc ≥ 2.14 and only links libc, so it runs on the PostGIS image's older Debian.
- **Rejected:** `apt-get install postgresql-16-pgvector` in the PostGIS image. Simpler to read, but needs Debian mirrors at build time, which the cloud dev environment blocks (and CI might too).

## M2 · Schedule stored as JSONB

- **Chose:** `listings.schedule` is JSONB holding a `Schedule`, validated by Pydantic in `repo.py` on the way in and out.
- **Rejected:** separate columns (rrule, dtstart, ...) or a schedules table. Recurrence is expanded in Python anyway, and breaks/exdates are lists; columns would add joins and buy nothing.
- **Where the AI got it wrong:** the first version stored a missing schedule as JSON `null`, not SQL `NULL` (SQLAlchemy's default for JSON columns). The CHECK "published needs a schedule" could never fire. A test that bypassed the repo caught it; fixed with `JSONB(none_as_null=True)`.

## M2 · Evidence rows are owned by the link that uses them

- **Chose:** each field-evidence link and each tag inserts its own `evidence` row; saving a listing again deletes the old ones. Simple, and no orphans.
- **Rejected:** deduplicating identical evidence across links. Saves a few rows, costs reference counting. Revisit if evidence volume matters.

## M2 · Hand-written migrations with a drift test

- **Chose:** `0001_initial_schema.py` written by hand (readable, explainable), plus a test that runs `alembic check` and fails if `tables.py` and the migrations disagree.
- **Rejected:** committing raw autogenerate output. It works, but it's noisy and easy to merge without reading.

## M2 · Database tests skip locally, fail in CI

- **Chose:** `make test` skips database tests if Postgres is down; `make test-db` (`MOREHERE_REQUIRE_DB=1`) fails instead. Each test runs in a transaction that is rolled back.
- **Rejected:** testcontainers. One more dependency and slower startup, for what `make db` already gives us.

## M2 · Vector column waits for the search milestone

- **Chose:** enable the `vector` extension now, add the embedding column when we pick the embedding model (its dimension is part of the column type).

## M3 · Parse from the stored payload, never from the HTTP response

- **Chose:** every run stores the Overpass response as a `RawRecord` first, then parses what was stored. `make osm-replay` re-runs parsing with no network.
- **Rejected:** parse-then-store. It's one step shorter, but a parser bug would then need a new fetch to fix, and Overpass is slow and rate-limited.

## M3 · District by location, with PostGIS assembling the boundaries

- **Chose:** load the 25 Stadtbezirk relations from OSM (`out geom`) and let `ST_BuildArea` turn their member ways into polygons (handles split ways and holes); every located place gets its district by `ST_Covers`. Location beats any district name in text, which settles the "Giesing could be two districts" flags from M1 for anything with coordinates.
- **Rejected:** assembling rings in Python (shapely or hand-written): more code to get wrong, and one more dependency.

## M3 · Places that disappear from OSM are reported, not deleted

- **Chose:** `places.last_seen_at`; each run logs `places_not_seen_this_run`. Milestone 6 decides when a place is hidden.
- **Rejected:** deleting missing places. One broken Overpass response (it does return partial results on timeouts) would wipe listings' places.

## M3 · Retries: 429/5xx/network errors and Overpass "remark" errors, never 4xx

- **Chose:** tenacity, up to 4 attempts, exponential backoff, `Retry-After` honoured (capped at 2 min). Overpass sometimes answers 200 with `"remark": "runtime error: Query timed out"`; that counts as a failure and is retried.
- **Where the AI got it wrong:** the module logger was named `__name__`, which is `"__main__"` under `python -m`, so the CLI's logs bypassed the JSON handler and printed as plain text. Caught on the first real run; loggers are now named explicitly, with a regression test.

## M3 · First real run (12 Nov 2026, from a Codespace)

- overpass-api.de refuses the cloud dev environment, so the first run happened in a GitHub Codespace. Results: all 25 Stadtbezirke matched (none unmatched or missing); 1,413 places (911 cafés, 318 community/arts centres, 118 libraries, 43 coworking, 16 climbing, 7 makerspaces); 33 unnamed skipped; 1,276 inside a district. The 137 without one lie in the bounding box but outside the city; the feed will show Munich only (API milestone). One 502 was retried successfully.
- OSM is noisy (a Nespresso shop tagged as a café, cafés without addresses). Acceptable: places are the map layer; listings are curated.

## M4 · Recurrence is parsed by rules, not by the LLM

- **Chose:** a small rule-based parser for English and German phrases; anything it can't read with certainty returns no RRULE plus a reason (`ambiguous`, `not_recurring`, `unparsed`) and goes to the curator. All 25 golden phrases produce their expected RRULE.
- **Rejected:** asking the LLM for the RRULE. Rule 1 (code decides), and a parser can be tested exhaustively.
- **Decided with Selim:** "jeden zweiten Freitag" / "every second Friday" without "im Monat"/"of the month" means every other week; with it, the 2nd Friday of the month. "Biweekly" stays ambiguous.

## M4 · Real feeds list dates, so series are inferred

- Research (below) showed that public feeds such as Luma's mostly contain one VEVENT per date, not RRULEs. `infer_rrule` finds weekly, every-other-week and nth/last-weekday-monthly series from at least 3 dated events with the same title, place, weekday and local start time, tolerating a skipped week. Irregular groups are left alone.
- **Rejected:** a lower minimum (2 events). Two dates fit too many rules to be evidence of one.

## M4 · Retry policy moved to `http.py`

- Shared by OSM and iCal (and later sources); OSM only adds its "remark" error as retryable.

## M4 · Occurrences: walk the rule once

- **Where the AI got it wrong:** `next_occurrences` first called `rule.after()` in a loop, which recomputes from dtstart on every call (quadratic); a test with a long walk took 7 s. Now it iterates `rule.xafter()` once, with a cap.

## M4+ · Series group on titles without edition numbers

- **Why:** the first real probe (Luma Munich Discover feed) showed numbered titles ("Knight Gambit Vol.14", "Brunch & Workshop #3"). Grouping by exact title would split one series into one-offs.
- **Chose:** strip explicit edition markers only (Vol./#/No./Nr./Night/Teil/Edition/Ausgabe + number) and compare letters and digits, so emoji and punctuation don't split a series either. Weekday, local start time and place must still match, so the rule is no looser.
- **Rejected:** stripping all numbers. "5k Run Club" and "Repair Café 246" would lose meaning, and unrelated events would merge.
- **Added:** `series_hints` in the probe output: numbered one-offs with their event link, so a discover feed points to the host calendars worth probing.

## M5 · Structured outputs instead of a `record_listing` tool

- **Chose:** `output_config.format` with a JSON schema; the model gets no tools at all. It guarantees the reply shape, allows several listings per document (a newsletter), and is stricter than "one tool that can't act".
- **Why the change:** the default model (`claude-opus-5-5`) rejects forced tool use (`tool_choice` any/tool), so "exactly one tool, always called" can't be enforced; `auto` doesn't guarantee a call.
- **Rejected:** a tool with `tool_choice: auto` plus retries when it isn't called. More code and a failure mode that structured outputs simply don't have.

## M5 · The model makes claims; code decides

- Every field comes back as `{value, source_text, note}`. `ground.py` accepts a value only if the quote occurs in the document text and supports the value: times, prices and dates are parsed out of the quote; names and phrases must appear in it; district names map to a Stadtbezirk via config (ambiguous -> flagged). Judgement fields (category, language, come alone, ...) need a real quote but can't be string-matched; the eval's "wrong accepted" column watches them.
- Flags are code's decision from grounded evidence: recurrence via `recurrence.py`, `missing_time`, `stale` from the page's own date, `suspected_injection` from the model's report **or** a pattern check. A test feeds an "obedient" model reply (it ignores the injection) and the listing is still never publishable.
- A fake "perfect model" built from the labels scores 100% on every metric; that proves grounding doesn't reject correct answers. Mutation checks: disabling the quote check or the injection pattern check makes tests fail.

## M5 · Determinism without temperature (rule 10 rewritten)

- Current models reject `temperature`. Runs are made comparable with a pinned model and effort, and CI replays recorded responses keyed on model + effort + prompt version + document. Run-to-run variation is measured by running the live eval twice.

## M5 · Live evals run in the Codespace

- The API key stays in the Codespace's `.env`, not in the cloud dev session (whose Anthropic traffic bypasses its credential proxy, so a key would have to sit in a file there). Recordings and results are committed from the Codespace.

## M5 · Refusal fallback on by default

- `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`): if a safety classifier declines, the API retries on Anthropic's recommended model in the same call. Unlikely for this content, but a refused record would otherwise fail. A refusal of the whole chain is an `ExtractionError` and the record is retried later.

## M5 · No union types in the output schema

- **Where the AI got it wrong:** the first live call returned 400: the schema had 54 nullable (`anyOf ... null`) parameters, and the API compiles at most 16 union-typed parameters per schema. I had used nullables for "not stated" on every value, quote and note.
- **Chose:** every value, quote and note is a plain string, and `""` means "nothing"; yes/no fields are `"true"`/`"false"`/`""`; prices come back as text. Code converts and type-checks while grounding. A test counts the union parameters in the schema (0) so this can't regress.
- **Rejected:** keeping nullables only on `value` (18 fields, still over 16) or splitting the call per field group (more calls, more cost, and listings would have to be stitched back together).
- Also: a rejected request (400/401/403/404) now stops the run with one line; network, rate-limit and server errors fail only that record.

## M5 · A flat "facts" schema (second live run)

- **Where the AI got it wrong (again):** after removing unions, the API rejected the schema as "compiled grammar too large": one object per field (18 objects with value/quote/note, enums inside) inside a listings array. Structured outputs compile the schema into a grammar for every output token, and big nested schemas don't fit.
- **Chose:** each listing is a list of facts `{field, value, source_text, note}`, all strings, with `field` an enum of the 18 names; fields the document doesn't mention are left out ("not stated"). About 1,150 characters instead of 6,898. Allowed values for category, language, price period and group size moved into the prompt; code still rejects anything else while grounding. Two different answers for one field are flagged "conflicting".
- **Rejected:** dropping structured outputs and validating free-form JSON (no shape guarantee, retries needed), or one call per group of fields (more cost, listings must be stitched together).
- **Lesson:** I should have tested the schema against the real API with one call before building on it. Tests now pin the schema's size and shape, but only a live call proves the API accepts it.

## M5 · First eval: what the 46 mistakes were

Baseline (claude-opus-5-5, effort medium, 24 documents): field accuracy 90%, 22 wrong values accepted, flags/RRULE/outcomes 100%, $0.47. Of the 46 mistakes:

- **Scoring too strict (~15):** case and punctuation, two phrasings of one schedule, a longer quote of the same place. Fixed in `evaluation.py`: free text compared by words, `recurrence_text` by the RRULE it yields, place names and tips by containment.
- **My labels were wrong or stricter than the text (~25):** "free" does not state a price *period*; "6-10 people" straddled my own "under 10"; tips the model found that I had missed; districts read from venue names. Labels and conventions updated (golden/labels.json), with `also_ok` for honest judgement calls (photo walk: outdoors or arts_crafts).
- **Real model errors (~6):** an event page given as the organiser's contact, directions inside place names, a paraphrased first-timer tip, "donation" for free entry. Fixed in the prompt (v2026-11-13.4), and first-timer tips must now be verbatim (rule 2), so a paraphrase is flagged instead of accepted.

On the same recorded responses, the scoring, grounding and label changes alone take field accuracy to 98% and wrong values accepted to 5; the prompt changes need a new live run.

**Lesson:** a hand-labelled set encodes the labeller's conventions. Several "model errors" were conventions I had never written down. Writing them into `conventions` (and the prompt) mattered more than prompt cleverness.

## M5 · Results with prompt v4, and the effort choice

| Run (claude-opus-5-5, 24 documents) | Field accuracy | Wrong values accepted | Flags, RRULE, outcomes | Cost | Model time |
| --- | --- | --- | --- | --- | --- |
| Baseline, old prompt and labels | 90% | 22 | 100% | $0.47 | 183 s |
| v4, medium effort (re-scored) | 99.6% | 0 | 100% | $0.44 | 173 s |
| v4, low effort (re-scored) | 99.0% | 3 | 100% | $0.28 | 130 s, 2 documents failed (503) |

- **Prompt v4 fixed what it targeted:** no event pages as contacts, no directions inside place names, price period only when stated, group sizes right; place_name, price_period and group_size went to 100%.
- **After the v4 run, labels changed only where** the document supports the model (the Lantern Walk is run by the newsletter team, so its email is a contact; `blockwerk.muc` is the venue's own profile), where my labels broke my own new district convention (four names like "Offener Chor Haidhausen" are not location statements), or where a document has several valid first-timer tips (`also_ok`). Two judgement calls were left as they are (FabLab "beginner-friendly", board-game "language"); in both the model flags instead of guessing.
- **Chose effort `medium`** (already the default in `config/llm.yaml`). Low is ~36% cheaper (about 1.2 vs 1.8 cents a document) but accepted 3 wrong values on judgement fields (beginner-friendly from "nobody judges", a newsletter's email as an organiser's contact). At our volume the difference is cents; wrong values reach users.
- **Also:** the SDK now retries 4 times (low lost 2 documents to "grammar compilation temporarily unavailable"), and reports show one decimal (99.56% had been displayed as "100%").
- **Caveat, honestly:** labels were revised after seeing model output, on only 24 documents, so 99.6% is an optimistic number. The real test is new documents the labels have never been tuned on: the listings curated in milestone 7 will become a held-out set.

## M6 · Same activity = same place + same rule + start within 30 minutes

- **Chose:** titles don't decide (the Luma feed and the newsletter name Tandem Tuesday differently); place, schedule rule and start time do. Places match by normalised address ("Hohenzollernstr. 41" = "Hohenzollernstraße 41") with a name check, or by a very similar name in the same district; otherwise a new place is created from the text (no coordinates until a curator adds them).
- **Rejected:** title similarity as the main signal: it would merge the decoy "English-German Language Café Haidhausen" with Tandem Tuesday (same day, same time, similar name, different café).
- **Evidence so far is thin:** the golden set has exactly one true duplicate pair and one decoy. Merge precision/recall is 100% on perfect drafts and on both recorded live runs, but that's one pair. The curated listings in milestone 7 should add more.

## M6 · Conflicts: the more reliable source wins, and the curator is told

- Per field, the value from the source with the higher `reliability` in `config/sources.yaml` is kept, and the listing gets a review note ("conflict on price_eur: 5.0 (email-inbox) vs 0.0 (organiser-form); kept organiser-form"). A conflict sends a published listing back to review.

## M6 · Regular Score: unknown is neutral, distance waits for the user

- Unknown fields count 0.5 and are named in `based_on` ("unknown: language"), so groups with terse websites aren't buried. Distance needs the user's location, so it's scored at query time (milestone 8); without it the weights are rescaled over the other five.
- Scales (weekly 1.0 / every other week 0.7 / monthly 0.5; free 1.0 ... over 20 € 0.2; small group 1.0 ...) are starting points to tune against "I went" data, not findings.

## M6 · Verification and freshness

- A fact counts as verified when its source was fetched, unless the source is stale itself (the photo walk's page says "last updated March 2026", so that listing starts unverified). `make freshness` hides published listings not verified within 60 days and shows them again once re-verified; a curator's own "hidden" is never undone.
- **Where the AI got it wrong:** the first version of the new database tests committed listings and left them behind, which broke the OSM tests that ran after them; then the cleanup itself failed, because deleting a listing leaves the evidence rows it pointed at. Tests now clean up before and after, evidence included.

## M6 · Known limits (deferred, agreed)

- iCal EXDATEs aren't carried into drafts, so the pub quiz's Christmas skips are lost.
- Places created from text have no coordinates (no geocoding service yet: another external host with its own terms).
