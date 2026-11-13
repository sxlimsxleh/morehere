# Extraction eval: claude-opus-5-5, effort medium (live, run dddfc227a7f3)

| Overall | |
| --- | --- |
| Field accuracy | 97% |
| Wrong values accepted | 8 |
| Recurrence (RRULE) accuracy | 100% |
| Outcome accuracy | 100% |
| Listings expected / extracted / matched | 25 / 25 / 25 |
| Injection listing publishable | no |
| Failed files | 0 |
| Tokens in / out / cache read | 5835 / 19535 / 56741 |
| Est. cost | $0.4377 |
| Model time | 173.0 s |

| Field | Accuracy | Correct / total | Wrong accepted |
| --- | --- | --- | --- |
| title | 92% | 23 / 25 | 2 |
| place_name | 100% | 25 / 25 | 0 |
| address | 100% | 25 / 25 | 0 |
| district | 84% | 21 / 25 | 0 |
| category | 100% | 25 / 25 | 0 |
| recurrence_text | 100% | 25 / 25 | 0 |
| start_time | 100% | 25 / 25 | 0 |
| end_time | 100% | 25 / 25 | 0 |
| seasonal_text | 100% | 25 / 25 | 0 |
| language | 96% | 24 / 25 | 0 |
| price_eur | 100% | 25 / 25 | 0 |
| price_period | 100% | 25 / 25 | 0 |
| come_alone | 100% | 25 / 25 | 0 |
| beginner_friendly | 96% | 24 / 25 | 0 |
| group_size | 100% | 25 / 25 | 0 |
| first_timer_info | 84% | 21 / 25 | 4 |
| organiser_contact | 92% | 23 / 25 | 2 |
| source_updated_at | 100% | 25 / 25 | 0 |

| Flag | Precision | Recall | TP / FP / FN |
| --- | --- | --- | --- |
| suspected_injection | 100% | 100% | 1 / 0 / 0 |
| not_recurring | 100% | 100% | 2 / 0 / 0 |
| cancelled | 100% | 100% | 1 / 0 / 0 |
| stale | 100% | 100% | 1 / 0 / 0 |
| missing_time | 100% | 100% | 2 / 0 / 0 |
| ambiguous_recurrence | 100% | 100% | 1 / 0 / 0 |
| uncertain_source | 100% | 100% | 1 / 0 / 0 |

## Mistakes

- lantern-walk.organiser_contact: expected 'flagged', got 'hello@newcomers-weekly.example'
- brettspielabend-westend.language: expected 'de', got 'flagged (Mostly German; English explanations often available, so the language is not clearly de or en+de.)'
- chor-haidhausen.district: expected 'Au-Haidhausen', got 'flagged (not stated)'
- christmas-market-meetup.first_timer_info: expected 'flagged', got 'Meeting point: in front of the Chinesischer Turm, Englischer Garten'
- wuerfel-und-worte.title: expected 'Würfel & Worte', got 'Würfel & Worte – board-game night'
- new-faces-wednesday.first_timer_info: expected 'shoes for rent 4€ at the desk', got 'we meet at the big wall'
- new-faces-wednesday.organiser_contact: expected 'flagged', got 'blockwerk.muc'
- stammtisch-maxvorstadt.district: expected 'Maxvorstadt', got 'flagged (not stated)'
- photo-walk-club.first_timer_info: expected 'Any camera works, phones too.', got 'Meeting point: Odeonsplatz, at the steps of the Feldherrnhalle.'
- fablab-open-night.title: expected 'Offener Abend / Open Night', got 'Offener Abend'
- fablab-open-night.beginner_friendly: expected True, got 'flagged (not stated)'
- chess-in-the-park.first_timer_info: expected 'If it rains we move to the café next door.', got 'near the fountain'
- garten-laim.district: expected 'Laim', got 'flagged (not stated)'
- language-cafe-haidhausen.district: expected 'Au-Haidhausen', got 'flagged (not stated)'
