# morehere. brand v1 — "Isar & Ochre"

*Make more of this city yours.*

The tokens live in `app/src/theme/tokens.ts`; this page says when to use what.
`tests/test_brand_tokens.py` checks that every text/background pair stays readable
(WCAG AA, 4.5:1 for text) in light and dark mode. Screens use token names, never hex values.

## The idea

morehere. helps you become a regular somewhere. The story the app tells is a
**line of postcards**: each place you go back to becomes a postcard pinned on your line.
An empty slot is always waiting for the next one. It's a collection of places that are
starting to be yours, not a score or a streak.

The colours are Munich without the blue-and-white cliché: the **milky turquoise of the
Isar** for anything you tap, the **ochre of the Theatinerkirche** for the good moments,
deep **petrol** for text, on warm **linen** paper. Dark mode is the Isar at night.

Why these and not others: the big "meet people / go out" apps own red/coral (Meetup,
Airbnb), orange (Eventbrite), yellow (Bumble For Friends), bright blue and black.
Teal with ochre is free. See DECISIONS.md, M9a.

## Wordmark

- `morehere.` in **Outfit Bold (700)**, letter spacing about −4%, all lowercase, as one word.
- The full stop is the brand mark: **ochre** (`wordmarkDot`), the rest in `ink`.
- On dark backgrounds: linen text, ochre dot.
- Never: split the word ("more here"), capitalise it, drop the dot, outline it or set it in another font.
- **App icon:** `m.` in linen on Isar teal, ochre dot. The full word is too long to read at icon size.

## Colour roles

| Role | Token | Rule |
| --- | --- | --- |
| Page | `background` | Linen. Most of every screen. |
| Cards, sheets, nav | `surface` | White, with a `border` outline (1.5). No heavy shadows. |
| Text | `ink`, `inkMuted` | `inkSubtle` is for decoration only, never text. |
| **Tap me** | `primary` | Main buttons, selected tab, links, focus ring. Only things you can tap are teal. |
| **Good moment** | `accent` | "I went!", a new postcard, a small highlight. Rare on purpose: about one per screen. Always dark text on it. |
| Tags | `primaryTint` / `accentTint` | Facts about a place ("come alone OK", "beginners welcome") use teal tint; money ("free", "€5") uses ochre tint. |
| Status | `success`, `warning*`, `error` | Only for real status (a reminder is set, a form error). Ochre already reads as "warning", so warnings use its tint. |

Rough proportions on any screen: ~65% linen and white, ~25% ink, ~8% teal, ~2% ochre.

## Type

Outfit only. The scale is in `tokens.type`:

- `display` 34: the hero line ("Somewhere to be tonight.")
- `title` 28
- `heading` 22: card titles
- `subheading` 18
- `body` 16
- `bodyStrong` 16: buttons
- `label` 14: tags, tabs
- `caption` 13: quotes, "last verified"
- `overline` 12, uppercase

Headings are bold with tight spacing; body text is regular, never lighter than 400.

## Shape and space

- Corners: tags 8, buttons 14, cards 20, sheets 28, pills fully round.
- Spacing on a 4-point grid (`tokens.space`).
- Every tappable thing is at least **44 × 44**; buttons are 48 tall.

## Components

**Buttons**

- Primary: teal with white text.
- Accent ("I went!" only): ochre with ink text.
- Secondary: white with a `borderStrong` outline.
- States:
  - Pressed: the `*Pressed` colour.
  - Disabled: `disabled` / `onDisabled`, and say why nearby.
  - Keyboard focus: a 2-point `focusRing` with a 2-point gap.

**Tabs:** a selected tab is bold and has a teal underline. Colour is never the only signal.

**Tags:** every user-facing tag is backed by evidence (CLAUDE.md rule 3). Tapping a tag shows the quote and the source. A tag with no evidence is not shown at all.

**Cards:**

- Category and district in `onPrimaryTint`, plus the time.
- The title, then one honest first-timer line.
- One or two tags, then at most two buttons.

**Postcards:**

- One card per place you've been to at least twice, pinned on a thin `borderStrong` line, slightly rotated (−4° to +4°).
- The next slot is a dashed outline with a `+`.
- A new postcard arrives with a short ochre glow, the only animation that celebrates.

## Voice

We sound like a friend who has lived here a few years and is glad you came: warm, honest, a bit dry, never pushy.

1. **Honest over hype.** Say what it's actually like, including the awkward bits. People trust "you'll probably be the only new person, and that's normal" more than "amazing community!".
2. **Plain words.** Write "Save it", not "Add to favourites". Write "Every Wednesday, 19:30", not "Recurring weekly event".
3. **Invite, never guilt.** No FOMO, no streaks to lose, no "you missed 3 events". Going back is the reward.
4. **Small and specific.** Name the room, the price and who to ask for. Details make a first visit less scary.
5. **Short.** One idea per sentence. Buttons have one or two words.
6. **Say how we know.** Facts come with their source and a "last verified" date. If we're unsure, we say so.

| Moment | Do | Don't |
| --- | --- | --- |
| Main action | Save it | Add to favourites |
| After going | I went! | Check in |
| Card line | No sheet music needed. Your first two rehearsals are free. | Join our amazing choir community today! |
| Reminder | Choir's at 19:30. The door's on the courtyard side. | Don't miss out! Event starting soon! |
| Nudge to return | Tandem Tuesday: one more visit and it joins your line. | You're about to lose your 3-week streak! |
| Empty postcards | No postcards yet. Go somewhere twice and it'll show up here. | You haven't done anything yet. |
| Unsure fact | Usually starts at 19:00 (last checked 12 Nov). Worth a quick look before you go. | Starts at 19:00. |
| Error | That didn't save. Check your connection and try again. | Error 500: request failed. |
| Weekly digest subject | Three things to go back to this week | 🔥 Don't miss this week's HOTTEST events |

**No emoji in the interface.** Icons do that job, and they stay consistent.
**German names stay German** ("Offener Chor Haidhausen", "Stammtisch"), and are explained in English where they're not obvious.
