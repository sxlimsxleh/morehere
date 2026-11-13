# Extraction eval: claude-opus-5-5, effort medium (live, run ab049e3dd5b6)

| Overall | |
| --- | --- |
| Field accuracy | 90% |
| Wrong values accepted | 22 |
| Recurrence (RRULE) accuracy | 100% |
| Outcome accuracy | 100% |
| Listings expected / extracted / matched | 25 / 25 / 25 |
| Injection listing publishable | no |
| Failed files | 0 |
| Tokens in / out / cache read | 5835 / 21145 / 49680 |
| Est. cost | $0.4670 |
| Model time | 182.5 s |

| Field | Accuracy | Correct / total | Wrong accepted |
| --- | --- | --- | --- |
| title | 96% | 24 / 25 | 0 |
| place_name | 84% | 21 / 25 | 4 |
| address | 100% | 25 / 25 | 0 |
| district | 92% | 23 / 25 | 0 |
| category | 92% | 23 / 25 | 2 |
| recurrence_text | 92% | 23 / 25 | 2 |
| start_time | 100% | 25 / 25 | 0 |
| end_time | 100% | 25 / 25 | 0 |
| seasonal_text | 100% | 25 / 25 | 0 |
| language | 92% | 23 / 25 | 1 |
| price_eur | 100% | 25 / 25 | 0 |
| price_period | 36% | 9 / 25 | 1 |
| come_alone | 100% | 25 / 25 | 0 |
| beginner_friendly | 88% | 22 / 25 | 0 |
| group_size | 92% | 23 / 25 | 0 |
| first_timer_info | 60% | 15 / 25 | 10 |
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

- tandem-tuesday-luma.price_period: expected 'per_visit', got 'flagged (not stated)'
- tandem-tuesday-luma.organiser_contact: expected 'flagged', got 'https://lu.ma.example/tandem-tuesday'
- tandem-tuesday-newsletter.price_period: expected 'per_visit', got 'flagged (not stated)'
- tandem-tuesday-newsletter.beginner_friendly: expected True, got 'flagged (not stated)'
- brettspielabend-westend.language: expected 'de', got 'flagged (Mostly played in German; many players are happy to explain in English, so it is unclear whether this counts as de or en+de.)'
- brettspielabend-westend.price_period: expected 'per_visit', got 'flagged (not stated)'
- brettspielabend-westend.first_timer_info: expected 'flagged', got 'Wir haben über 80 Spiele im Regal, ihr könnt aber auch eigene mitbringen.'
- book-swap-sendling.price_period: expected 'per_visit', got 'flagged (not stated)'
- book-swap-sendling.group_size: expected 'small', got 'flagged (Range 6-10 straddles the small (<10) and medium (10-30) boundary.)'
- book-swap-sendling.first_timer_info: expected 'Please bring at least one book to swap.', got 'please bring at least one book to swap'
- chor-haidhausen.place_name: expected 'Pfarrei St. Wolfgang', got 'Saal der Pfarrei St. Wolfgang'
- christmas-market-meetup.place_name: expected 'Chinesischer Turm', got 'Chinesischer Turm, Englischer Garten'
- christmas-market-meetup.price_period: expected 'per_visit', got 'flagged (not stated)'
- christmas-market-meetup.first_timer_info: expected 'flagged', got 'Meet in front of the Chinesischer Turm'
- isar-morning-runners.price_period: expected 'per_visit', got 'flagged (not stated)'
- clay-and-chat.group_size: expected 'small', got 'flagged (States a maximum capacity, not the actual number of participants.)'
- wuerfel-und-worte.price_period: expected 'per_visit', got 'flagged (not stated)'
- wuerfel-und-worte.first_timer_info: expected 'flagged', got 'Bring a game or play one of ours.'
- new-faces-wednesday.first_timer_info: expected 'Shoes for rent at the desk (4€).', got 'we meet at the big wall'
- stammtisch-maxvorstadt.price_period: expected 'per_visit', got 'flagged (not stated)'
- photo-walk-club.place_name: expected 'Odeonsplatz', got 'Odeonsplatz, at the steps of the Feldherrnhalle'
- photo-walk-club.category: expected 'outdoors', got 'arts_crafts'
- photo-walk-club.recurrence_text: expected 'the second Sunday of every month', got 'second Sunday of every month'
- photo-walk-club.price_period: expected 'per_visit', got 'flagged (not stated)'
- photo-walk-club.beginner_friendly: expected True, got 'flagged (not stated)'
- photo-walk-club.first_timer_info: expected 'flagged', got 'Any camera works, phones too.'
- sunrise-yoga.place_name: expected 'Monopteros, Englischer Garten', got 'the meadow next to the Monopteros, Englischer Garten'
- sunrise-yoga.first_timer_info: expected 'Bring your own mat.', got 'bring your own mat'
- silent-study-sundays.district: expected 'Au-Haidhausen', got 'flagged (not stated)'
- silent-study-sundays.price_period: expected 'per_visit', got 'flagged (not stated)'
- fablab-open-night.district: expected 'Thalkirchen-Obersendling-Forstenried-Fürstenried-Solln', got 'flagged (not stated)'
- fablab-open-night.beginner_friendly: expected True, got 'flagged (not stated)'
- fablab-open-night.first_timer_info: expected 'Newcomers get a short tour at 6:30pm.', got 'Einweisung für Neue um 18:30 Uhr – newcomers get a short tour at 6:30pm.'
- kreativabend.recurrence_text: expected 'every last Friday of the month', got 'Jeden letzten Freitag im Monat'
- kreativabend.price_period: expected 'per_visit', got 'flagged (not stated)'
- kreativabend.first_timer_info: expected 'Materials provided.', got 'materials provided'
- chess-in-the-park.price_period: expected 'per_visit', got 'flagged (not stated)'
- chess-in-the-park.first_timer_info: expected 'If it rains we move to the café next door.', got 'Boards provided. Meet near the fountain; if it rains the group moves to the café next door.'
- founders-breakfast.price_period: expected 'per_visit', got 'flagged (not stated)'
- founders-breakfast.organiser_contact: expected 'flagged', got 'https://lu.ma.example/founders-breakfast-muc'
- repair-cafe-giesing.price_period: expected 'per_visit', got 'donation'
- film-club-hinterhof.title: expected 'Film club', got 'flagged (not stated)'
- film-club-hinterhof.language: expected 'flagged', got 'en+de'
- garten-laim.category: expected 'outdoors', got 'volunteering'
- garten-laim.price_period: expected 'per_visit', got 'flagged (not stated)'
- language-cafe-haidhausen.price_period: expected 'per_visit', got 'flagged (not stated)'
