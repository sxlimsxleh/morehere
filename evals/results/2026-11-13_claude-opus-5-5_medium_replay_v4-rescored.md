# Extraction eval: claude-opus-5-5, effort medium (replay, run 4c502b3cdbec)

| Overall | |
| --- | --- |
| Field accuracy | 99.6% |
| Wrong values accepted | 0 |
| Recurrence (RRULE) accuracy | 100.0% |
| Outcome accuracy | 100.0% |
| Listings expected / extracted / matched | 25 / 25 / 25 |
| Merge precision / recall | 100.0% / 100.0% (1 / 0 / 0 TP/FP/FN) |
| Injection listing publishable | no |
| Failed files | 0 |
| Tokens in / out / cache read | 5835 / 19535 / 56741 |
| Est. cost | $0.4377 |
| Model time | 0.0 s |

| Field | Accuracy | Correct / total | Wrong accepted |
| --- | --- | --- | --- |
| title | 100.0% | 25 / 25 | 0 |
| place_name | 100.0% | 25 / 25 | 0 |
| address | 100.0% | 25 / 25 | 0 |
| district | 100.0% | 25 / 25 | 0 |
| category | 100.0% | 25 / 25 | 0 |
| recurrence_text | 100.0% | 25 / 25 | 0 |
| start_time | 100.0% | 25 / 25 | 0 |
| end_time | 100.0% | 25 / 25 | 0 |
| seasonal_text | 100.0% | 25 / 25 | 0 |
| language | 96.0% | 24 / 25 | 0 |
| price_eur | 100.0% | 25 / 25 | 0 |
| price_period | 100.0% | 25 / 25 | 0 |
| come_alone | 100.0% | 25 / 25 | 0 |
| beginner_friendly | 96.0% | 24 / 25 | 0 |
| group_size | 100.0% | 25 / 25 | 0 |
| first_timer_info | 100.0% | 25 / 25 | 0 |
| organiser_contact | 100.0% | 25 / 25 | 0 |
| source_updated_at | 100.0% | 25 / 25 | 0 |

| Flag | Precision | Recall | TP / FP / FN |
| --- | --- | --- | --- |
| suspected_injection | 100.0% | 100.0% | 1 / 0 / 0 |
| not_recurring | 100.0% | 100.0% | 2 / 0 / 0 |
| cancelled | 100.0% | 100.0% | 1 / 0 / 0 |
| stale | 100.0% | 100.0% | 1 / 0 / 0 |
| missing_time | 100.0% | 100.0% | 2 / 0 / 0 |
| ambiguous_recurrence | 100.0% | 100.0% | 1 / 0 / 0 |
| uncertain_source | 100.0% | 100.0% | 1 / 0 / 0 |

## Mistakes

- brettspielabend-westend.language: expected 'de', got 'flagged (Mostly German; English explanations often available, so the language is not clearly de or en+de.)'
- fablab-open-night.beginner_friendly: expected True, got 'flagged (not stated)'
