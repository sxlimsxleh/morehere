"""The Regular Score: how well a listing supports becoming a regular there (0 to 1).

Deterministic code, never the LLM (rule 1). Each component is a number between 0 and 1;
the total is their weighted average with weights from config/munich.yaml. `based_on`
records which fields fed each component, and "unknown: <field>" where the source didn't
say: unknown counts as neutral (0.5), so terse websites aren't punished (decision M6).

Distance depends on where the user is, so it is only scored when a distance is given
(at query time, milestone 8). Without it, the weights are rescaled over the rest.
"""

from __future__ import annotations

from morehere.models import Listing, RegularScore

NEUTRAL = 0.5

# Starting scales; tune them against real feedback ("I went" twice = it worked).
FREQUENCY = {"weekly": 1.0, "every_other_week": 0.7, "monthly": 0.5}
ENGLISH = {"en": 1.0, "en+de": 0.8, "de": 0.3}
GROUP_SIZE = {"small": 1.0, "medium": 0.8, "large": 0.4}
PRICE_STEPS = [(0.0, 1.0), (5.0, 0.8), (10.0, 0.6), (20.0, 0.4)]  # (up to EUR, score)
DISTANCE_STEPS = [(1000, 1.0), (3000, 0.8), (6000, 0.6), (10000, 0.4)]  # (up to m, score)


def _recurrence(listing: Listing) -> tuple[float, list[str]]:
    if listing.schedule is None:
        return NEUTRAL, ["unknown: schedule"]
    parts = dict(p.split("=", 1) for p in listing.schedule.rrule.split(";"))
    if parts.get("FREQ") == "WEEKLY":
        kind = "weekly" if parts.get("INTERVAL", "1") == "1" else "every_other_week"
    elif parts.get("FREQ") == "MONTHLY":
        kind = "monthly"
    else:
        return NEUTRAL, ["schedule (unusual rule)"]
    score = FREQUENCY[kind]
    break_months = {m for b in listing.schedule.breaks for m in b.months}
    if break_months:  # a summer break makes it a little harder to become a regular
        score *= (12 - len(break_months)) / 12
    return score, ["schedule"]


def _newcomer_welcome(listing: Listing) -> tuple[float, list[str]]:
    # Shares: come alone 0.5, beginners 0.3, a first-timer tip 0.2. Unknown = half a share.
    score, based_on = 0.0, []
    for field, share, value in (
        ("come_alone", 0.5, listing.come_alone),
        ("beginner_friendly", 0.3, listing.beginner_friendly),
        ("first_timer_info", 0.2, bool(listing.first_timer_info) or None),
    ):
        if value is None:
            score += share * NEUTRAL
            based_on.append(f"unknown: {field}")
        else:
            score += share if value else 0.0
            based_on.append(field)
    return score, based_on


def _price(listing: Listing) -> tuple[float, list[str]]:
    if listing.price_eur is None:
        return NEUTRAL, ["unknown: price_eur"]
    per_visit = listing.price_eur / 4 if listing.price_period == "monthly" else listing.price_eur
    for limit, score in PRICE_STEPS:
        if per_visit <= limit:
            return score, ["price_eur"]
    return 0.2, ["price_eur"]


def _lookup(table: dict[str, float], value: str | None, field: str) -> tuple[float, list[str]]:
    if value is None:
        return NEUTRAL, [f"unknown: {field}"]
    return table.get(value, NEUTRAL), [field]


def distance_score(distance_m: float) -> float:
    for limit, score in DISTANCE_STEPS:
        if distance_m <= limit:
            return score
    return 0.2


def regular_score(
    listing: Listing, weights: dict[str, float], distance_m: float | None = None
) -> RegularScore:
    parts: dict[str, tuple[float, list[str]]] = {
        "recurrence": _recurrence(listing),
        "newcomer_welcome": _newcomer_welcome(listing),
        "english": _lookup(ENGLISH, listing.language, "language"),
        "price": _price(listing),
        "group_size": _lookup(GROUP_SIZE, listing.group_size, "group_size"),
    }
    if distance_m is not None:
        parts["distance"] = (distance_score(distance_m), ["distance"])
    used = {name: weights[name] for name in parts if weights.get(name)}
    total = sum(weight * parts[name][0] for name, weight in used.items()) / sum(used.values())
    return RegularScore(
        total=round(total, 3),
        components={name: round(value, 3) for name, (value, _) in parts.items()},
        based_on={name: based_on for name, (_, based_on) in parts.items()},
    )
