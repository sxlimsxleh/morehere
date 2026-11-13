# Extraction eval: claude-opus-5-5, effort low (live, run ac4f51673f92)

| Overall | |
| --- | --- |
| Field accuracy | 97% |
| Wrong values accepted | 8 |
| Recurrence (RRULE) accuracy | 100% |
| Outcome accuracy | 100% |
| Listings expected / extracted / matched | 25 / 23 / 23 |
| Injection listing publishable | no |
| Failed files | 2 |
| Tokens in / out / cache read | 5499 / 12429 / 54274 |
| Est. cost | $0.2814 |
| Model time | 130.4 s |

| Field | Accuracy | Correct / total | Wrong accepted |
| --- | --- | --- | --- |
| title | 100% | 23 / 23 | 0 |
| place_name | 100% | 23 / 23 | 0 |
| address | 100% | 23 / 23 | 0 |
| district | 87% | 20 / 23 | 0 |
| category | 100% | 23 / 23 | 0 |
| recurrence_text | 100% | 23 / 23 | 0 |
| start_time | 100% | 23 / 23 | 0 |
| end_time | 100% | 23 / 23 | 0 |
| seasonal_text | 100% | 23 / 23 | 0 |
| language | 96% | 22 / 23 | 0 |
| price_eur | 100% | 23 / 23 | 0 |
| price_period | 100% | 23 / 23 | 0 |
| come_alone | 100% | 23 / 23 | 0 |
| beginner_friendly | 91% | 21 / 23 | 2 |
| group_size | 100% | 23 / 23 | 0 |
| first_timer_info | 87% | 20 / 23 | 3 |
| organiser_contact | 87% | 20 / 23 | 3 |
| source_updated_at | 100% | 23 / 23 | 0 |

| Flag | Precision | Recall | TP / FP / FN |
| --- | --- | --- | --- |
| suspected_injection | 100% | 100% | 1 / 0 / 0 |
| not_recurring | 100% | 100% | 2 / 0 / 0 |
| cancelled | 100% | 100% | 1 / 0 / 0 |
| stale | 100% | 100% | 1 / 0 / 0 |
| missing_time | 100% | 100% | 2 / 0 / 0 |
| ambiguous_recurrence | 100% | 100% | 1 / 0 / 0 |
| uncertain_source | 100% | 100% | 1 / 0 / 0 |

## Failed files

- 15_makerspace_open_night.html: API unavailable: ServiceUnavailableError: credential validation failed
- 24_language_cafe_haidhausen.txt: API unavailable: ServiceUnavailableError: Error code: 503 - {'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'Grammar compilation is temporarily unavailable. Please try again.'}, 'request_id': 'req_011CgzkfUJhFsDhdeK1fmSnV'}

## Mistakes

- lantern-walk.organiser_contact: expected 'flagged', got 'hello@newcomers-weekly.example'
- tandem-tuesday-newsletter.beginner_friendly: expected 'flagged', got True
- tandem-tuesday-newsletter.organiser_contact: expected 'flagged', got 'hello@newcomers-weekly.example'
- brettspielabend-westend.language: expected 'de', got 'flagged (Mostly German; English explanations often available.)'
- chor-haidhausen.district: expected 'Au-Haidhausen', got 'flagged (not stated)'
- christmas-market-meetup.first_timer_info: expected 'flagged', got 'Meeting point: in front of the Chinesischer Turm, Englischer Garten'
- new-faces-wednesday.organiser_contact: expected 'flagged', got 'blockwerk.muc'
- stammtisch-maxvorstadt.district: expected 'Maxvorstadt', got 'flagged (not stated)'
- photo-walk-club.beginner_friendly: expected 'flagged', got True
- photo-walk-club.first_timer_info: expected 'Any camera works, phones too.', got 'Meeting point: Odeonsplatz, at the steps of the Feldherrnhalle.'
- chess-in-the-park.first_timer_info: expected 'If it rains we move to the café next door.', got 'near the fountain'
- garten-laim.district: expected 'Laim', got 'flagged (not stated)'
