# Extraction eval: claude-opus-5-5, effort low (replay, run 9ac2e68472d2)

| Overall | |
| --- | --- |
| Field accuracy | 99.0% |
| Wrong values accepted | 3 |
| Recurrence (RRULE) accuracy | 100.0% |
| Outcome accuracy | 100.0% |
| Listings expected / extracted / matched | 25 / 23 / 23 |
| Injection listing publishable | no |
| Failed files | 2 |
| Tokens in / out / cache read | 5499 / 12429 / 54274 |
| Est. cost | $0.2814 |
| Model time | 0.0 s |

| Field | Accuracy | Correct / total | Wrong accepted |
| --- | --- | --- | --- |
| title | 100.0% | 23 / 23 | 0 |
| place_name | 100.0% | 23 / 23 | 0 |
| address | 100.0% | 23 / 23 | 0 |
| district | 100.0% | 23 / 23 | 0 |
| category | 100.0% | 23 / 23 | 0 |
| recurrence_text | 100.0% | 23 / 23 | 0 |
| start_time | 100.0% | 23 / 23 | 0 |
| end_time | 100.0% | 23 / 23 | 0 |
| seasonal_text | 100.0% | 23 / 23 | 0 |
| language | 95.7% | 22 / 23 | 0 |
| price_eur | 100.0% | 23 / 23 | 0 |
| price_period | 100.0% | 23 / 23 | 0 |
| come_alone | 100.0% | 23 / 23 | 0 |
| beginner_friendly | 91.3% | 21 / 23 | 2 |
| group_size | 100.0% | 23 / 23 | 0 |
| first_timer_info | 100.0% | 23 / 23 | 0 |
| organiser_contact | 95.7% | 22 / 23 | 1 |
| source_updated_at | 100.0% | 23 / 23 | 0 |

| Flag | Precision | Recall | TP / FP / FN |
| --- | --- | --- | --- |
| suspected_injection | 100.0% | 100.0% | 1 / 0 / 0 |
| not_recurring | 100.0% | 100.0% | 2 / 0 / 0 |
| cancelled | 100.0% | 100.0% | 1 / 0 / 0 |
| stale | 100.0% | 100.0% | 1 / 0 / 0 |
| missing_time | 100.0% | 100.0% | 2 / 0 / 0 |
| ambiguous_recurrence | 100.0% | 100.0% | 1 / 0 / 0 |
| uncertain_source | 100.0% | 100.0% | 1 / 0 / 0 |

## Failed files

- 15_makerspace_open_night.html: no recording for this document with claude-opus-5-5/low and prompt 2026-11-13.4; run `make evals` with a key to record it
- 24_language_cafe_haidhausen.txt: no recording for this document with claude-opus-5-5/low and prompt 2026-11-13.4; run `make evals` with a key to record it

## Mistakes

- tandem-tuesday-newsletter.beginner_friendly: expected 'flagged', got True
- tandem-tuesday-newsletter.organiser_contact: expected 'flagged', got 'hello@newcomers-weekly.example'
- brettspielabend-westend.language: expected 'de', got 'flagged (Mostly German; English explanations often available.)'
- photo-walk-club.beginner_friendly: expected 'flagged', got True
