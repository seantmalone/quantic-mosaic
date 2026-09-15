"""WCAG 2.1 contrast, in one place, for the two suites that measure it (UX W5).

Two things need the same arithmetic and must not disagree about it:

* `tests/contract/test_brand_contrast.py` reads the **tokens** out of `static/brand/brand.css` and
  checks every foreground/background pair `docs/brand.md` §3 publishes, in light and in dark. It
  needs no browser and runs on every commit.
* `tests/ux/test_accessibility.py` reads the colours a **browser actually painted** — `getComputedStyle`
  on the text and the pills of a rendered page, in both colour schemes — and checks the same floors.
  That is where a rule using the wrong token shows up: the tokens can all pass and one selector
  still put `--ink-soft` on an accent fill.

The formula is the one `docs/brand.md` §3 quotes: relative luminance per WCAG 2.1, then
`(L_lighter + 0.05) / (L_darker + 0.05)`. The floors are AA: **4.5** for body text, **3.0** for
large text (18.66px bold, or 24px at any weight) and for a UI boundary or a meaningful graphic.
"""

from __future__ import annotations

import re

#: AA floors (WCAG 2.1 §1.4.3, §1.4.11).
AA_TEXT = 4.5
AA_LARGE_TEXT = 3.0
AA_NON_TEXT = 3.0

#: The size at which text counts as "large" for §1.4.3: 24px, or 18.66px at weight 700+.
LARGE_PX = 24.0
LARGE_BOLD_PX = 18.66
BOLD = 700

_HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_FUNCTIONAL = re.compile(r"^rgba?\(([^)]*)\)$")


def parse_colour(value: str) -> tuple[float, float, float, float]:
    """`#0d5c57`, `#fff`, `rgb(13 92 87)`, `rgba(0, 0, 0, 0.14)` → `(r, g, b, alpha)` in 0–255/0–1.

    Both CSS syntaxes, because `brand.css` writes hex and a browser hands back `rgb(…)` — and the
    modern space-separated `rgb(16 29 28 / 0.07)` form, which the shadow tokens use.
    """
    text = value.strip()
    if _HEX.match(text):
        digits = text[1:]
        if len(digits) == 3:
            digits = "".join(digit * 2 for digit in digits)
        channels = [int(digits[index : index + 2], 16) for index in (0, 2, 4)]
        alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
        return (*channels, alpha)  # type: ignore[return-value]
    match = _FUNCTIONAL.match(text)
    if match is None:
        raise ValueError(f"not a colour this project writes: {value!r}")
    parts = [part for part in re.split(r"[,/\s]+", match.group(1).strip()) if part]
    numbers = [float(part.rstrip("%")) for part in parts]
    red, green, blue = numbers[:3]
    alpha = numbers[3] if len(numbers) > 3 else 1.0
    return (red, green, blue, alpha)


def _channel(value: float) -> float:
    srgb = value / 255
    return srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4


def relative_luminance(colour: str) -> float:
    red, green, blue, _ = parse_colour(colour)
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def over(foreground: str, background: str) -> str:
    """`foreground` composited onto an opaque `background`, so a translucent ink is judged as seen."""
    front = parse_colour(foreground)
    back = parse_colour(background)
    alpha = front[3]
    mix = [round(front[index] * alpha + back[index] * (1 - alpha)) for index in (0, 1, 2)]
    return f"rgb({mix[0]} {mix[1]} {mix[2]})"


def ratio(foreground: str, background: str) -> float:
    """The WCAG contrast ratio, 1.0–21.0. A translucent foreground is composited first."""
    if parse_colour(foreground)[3] < 1:
        foreground = over(foreground, background)
    lighter, darker = sorted((relative_luminance(foreground), relative_luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def floor_for(*, font_px: float, font_weight: int) -> float:
    """AA's floor for text of this size: 3.0 once it is large, 4.5 otherwise."""
    if font_px >= LARGE_PX or (font_weight >= BOLD and font_px >= LARGE_BOLD_PX):
        return AA_LARGE_TEXT
    return AA_TEXT


__all__ = [
    "AA_LARGE_TEXT",
    "AA_NON_TEXT",
    "AA_TEXT",
    "floor_for",
    "over",
    "parse_colour",
    "ratio",
    "relative_luminance",
]
