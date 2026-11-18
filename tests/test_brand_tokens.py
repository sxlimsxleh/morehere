"""The brand colours stay readable: every text/background pair the app uses meets WCAG AA.

Reads app/src/theme/tokens.ts (the source of truth for the app) so a colour change
that breaks contrast fails here before it reaches a screen.
"""

import re
from pathlib import Path

import pytest

TOKENS = Path(__file__).resolve().parents[1] / "app" / "src" / "theme" / "tokens.ts"

TEXT = 4.5  # WCAG AA, normal text
UI = 3.0  # WCAG AA, large text and non-text UI (button shapes, focus rings, outlines that matter)

# (foreground, background, minimum ratio). Checked in both light and dark.
PAIRS: list[tuple[str, str, float]] = [
    ("ink", "background", TEXT),
    ("ink", "surface", TEXT),
    ("ink", "surfaceMist", TEXT),
    ("inkMuted", "background", TEXT),
    ("inkMuted", "surface", TEXT),
    ("onPrimary", "primary", TEXT),
    ("onPrimary", "primaryPressed", TEXT),
    ("onPrimaryTint", "primaryTint", TEXT),
    ("link", "surface", TEXT),
    ("link", "background", TEXT),
    ("onAccent", "accent", TEXT),
    ("onAccent", "accentPressed", TEXT),
    ("onAccentTint", "accentTint", TEXT),
    ("onSuccessTint", "successTint", TEXT),
    ("onWarningTint", "warningTint", TEXT),
    ("onErrorTint", "errorTint", TEXT),
    ("error", "surface", TEXT),  # inline error text
    ("onDisabled", "disabled", TEXT),
    ("focusRing", "background", UI),
    ("focusRing", "surface", UI),
    ("link", "background", UI),  # selected tab underline
]


def palette(name: str) -> dict[str, str]:
    source = TOKENS.read_text()
    block = re.search(rf"export const {name} = \{{(.*?)\}} as const;", source, re.S)
    assert block, f"no `export const {name} = {{ ... }} as const;` in {TOKENS}"
    return {k: v.upper() for k, v in re.findall(r'(\w+): "#([0-9A-Fa-f]{6})"', block.group(1))}


def luminance(hex6: str) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (int(hex6[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_contrast_formula() -> None:
    assert contrast("000000", "FFFFFF") == pytest.approx(21.0)
    assert contrast("777777", "FFFFFF") == pytest.approx(4.48, abs=0.01)


def test_light_and_dark_have_the_same_names() -> None:
    assert palette("light").keys() == palette("dark").keys()


# Colours used for text. In dark mode all of them must be light (brand rule).
TEXT_TOKENS = sorted({fg for fg, _, minimum in PAIRS if minimum == TEXT})


@pytest.mark.parametrize("name", TEXT_TOKENS)
def test_dark_mode_text_is_light(name: str) -> None:
    lum = luminance(palette("dark")[name])
    assert lum >= 0.3, (
        f"dark: {name} is a dark colour (luminance {lum:.2f}); text must be light in dark mode"
    )


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize(("fg", "bg", "minimum"), PAIRS)
def test_pair_is_readable(theme: str, fg: str, bg: str, minimum: float) -> None:
    colours = palette(theme)
    ratio = contrast(colours[fg], colours[bg])
    assert ratio >= minimum, f"{theme}: {fg} on {bg} is {ratio:.2f}:1, needs {minimum}:1"
