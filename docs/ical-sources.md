# Public calendar feeds for Munich: what exists and what's usable

Researched 12 Nov 2026 by web search. The cloud dev session can't open these sites, so nothing here has been fetched yet: run `make ical-probe URL=...` (e.g. in a Codespace) to check a feed before adding it to `config/sources.yaml`.

## What we found

| Source | Feed? | Useful for morehere? | Legal route |
| --- | --- | --- | --- |
| **Luma** (lu.ma / luma.com) | Yes. Each calendar and each city's Discover page offers "Add iCal Subscription" ([Luma help](https://help.luma.com/p/ical-syncing)). The URL format (`api.lu.ma/ics/get?...`) is undocumented, so copy it from the button. | Medium. Munich's Luma is mostly startup/tech, often one-off. Recurring groups (run clubs, coworking, language exchanges) post one event per date, so series must be inferred (`infer_rrule`). | Public feed made for subscribing: `public_feed`. |
| **Meetup** | Old `/events/ical/` links now reportedly 404 or show a login page unless you're signed in ([report](https://wordpress.org/support/?p=16607116)); the API needs a Pro/organiser account. | High content value (many recurring English groups, e.g. a weekly Friday Sprachcafé), but no reliable feed. | Organisers connect their own group, or submit via our form; otherwise link out. Don't scrape. |
| **muenchen.de** (city portal) | No documented iCal export found. | Low; mostly big events. | — |
| **Venue and community-centre websites** (Nachbarschaftstreffs, Kulturhäuser, Repair Cafés) | Unknown per site. Many German community sites run WordPress "The Events Calendar", which exposes `?ical=1`. | **High.** This is where the recurring things are: e.g. a Monday Repair Café at KAP 37, a monthly one at Nachbarschaftstreff Blumenau, weekly Sprachcafés at Kulturhaus Milbertshofen (seen via listings sites). | The venue's own published feed: `public_feed`. |
| **Listings sites** (in-muenchen.de, rausgegangen.de) | Some listings exist; feeds not checked. | They show what exists, but they're aggregators/competitors. | **Don't scrape** (rule 5). Use them to discover venues, then go to the venue's own feed or ask the organiser. |

## What this means

1. iCal will be a **useful but secondary** source. The best recurring content sits on small venue sites and Meetup groups, not in big feeds.
2. The **organiser form and forwarded newsletters** (milestone 5 extraction) stay the main supply, as the plan said.
3. Worth probing first: the Luma Munich Discover feed, and the event pages of 5–10 Nachbarschaftstreffs/Kulturhäuser (look for an "iCal"/"Export"/"Abonnieren" link, or try adding `?ical=1` to a WordPress events page).

## How to add a feed

1. `make ical-probe URL=...` and look at `inferred_series` and `recurring`. A feed with only one-offs isn't worth adding.
2. Add an entry to `config/sources.yaml` with `kind: ical`, `legal_status: public_feed`, the `url`, a refresh schedule and a reliability guess; then `make seed` and `make ical`.
