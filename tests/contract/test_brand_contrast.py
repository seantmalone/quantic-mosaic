"""Every brand colour pair clears WCAG AA, on both grounds and in both themes (UX W5).

`docs/brand.md` §3 publishes a measured contrast table and then states the rule that makes it
binding: *"a new colour is only in the system once its ratio against `--paper`, `--card` and
`--sunk` is measured and written into this table. There is no 'decorative' text colour."* Until now
that was a claim in a document. This recomputes it from the tokens `static/brand/brand.css`
actually ships, in the light block and in the dark one, so a token edited to a prettier value fails
here rather than in somebody's eyes.

It is deliberately the *token* half of the check. The painted half — the colours a browser really
resolved on a real page, where a rule using the wrong token shows up — is
`tests/ux/test_accessibility.py`, which shares this suite's arithmetic (`tests/support/contrast.py`).
"""

from __future__ import annotations

import re

import pytest

from hrmosaic.web.api import PACKAGE_DIR
from tests.support import contrast

BRAND_CSS = (PACKAGE_DIR / "static" / "brand" / "brand.css").read_text(encoding="utf-8")

#: `--name: value;` inside one declaration block.
DECLARATION = re.compile(r"--([a-z0-9-]+)\s*:\s*([^;]+);")

#: The three grounds every ink is read on, and the accent ground the user's own message uses.
GROUNDS = ("paper", "card", "sunk")

#: Text pairs: (foreground token, background token). Straight from `docs/brand.md` §3's table.
TEXT_PAIRS = (
    *[(ink, ground) for ink in ("ink", "ink-soft", "ink-mute", "accent") for ground in GROUNDS],
    *[(ink, "accent-soft") for ink in ("ink", "ink-soft", "accent")],
    ("on-accent", "accent"),
    ("on-accent", "accent-strong"),
    *[("warn", ground) for ground in ("warn-soft", "card", "paper")],
    *[("danger", ground) for ground in ("danger-soft", "card", "paper")],
    *[("ok", ground) for ground in ("ok-soft", "card", "paper")],
)

#: A boundary, a focus indicator or a meaningful graphic — AA asks 3:1 of these, not 4.5.
BOUNDARY_TOKENS = ("line-strong", "focus", "mark-a", "mark-b", "mark-c")
NON_TEXT_PAIRS = tuple((token, ground) for token in BOUNDARY_TOKENS for ground in ("card", "paper"))


def _pair_id(value: object) -> str | None:
    """Parametrized ids read as `ink-soft-card-light`, not as `foreground0`."""
    return value if isinstance(value, str) else None


def _block(marker: str) -> dict[str, str]:
    """The declarations of the block that opens at `marker`, up to its matching brace."""
    start = BRAND_CSS.index(marker) + len(marker)
    depth, end = 1, start
    while depth:
        end += 1
        if BRAND_CSS[end] == "{":
            depth += 1
        elif BRAND_CSS[end] == "}":
            depth -= 1
    return dict(DECLARATION.findall(BRAND_CSS[start:end]))


def _themes() -> dict[str, dict[str, str]]:
    """`{"light": {...}, "dark": {...}}` — dark is the base block with its overrides applied.

    Both dark blocks are read, and they are asserted identical: `brand.css` writes the palette
    twice, once behind `prefers-color-scheme` and once behind an explicit `data-theme`, and two
    copies of a palette are two palettes waiting to disagree.
    """
    light = _block(":root {")
    by_preference = _block(':root:not([data-theme="light"]) {')
    explicit = _block(':root[data-theme="dark"] {')
    assert by_preference == explicit, (
        "the two dark blocks are the same palette written twice; they have drifted: "
        f"{sorted(set(by_preference.items()) ^ set(explicit.items()))}"
    )
    return {"light": light, "dark": {**light, **explicit}}


THEMES = _themes()


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("foreground,background", TEXT_PAIRS, ids=_pair_id)
def test_every_text_pair_clears_the_aa_floor(theme, foreground, background):
    tokens = THEMES[theme]
    measured = contrast.ratio(tokens[foreground], tokens[background])
    assert measured >= contrast.AA_TEXT, (
        f"--{foreground} on --{background} in {theme} is {measured:.2f}:1, below AA's {contrast.AA_TEXT}"
    )


@pytest.mark.parametrize("theme", sorted(THEMES))
@pytest.mark.parametrize("foreground,background", NON_TEXT_PAIRS, ids=_pair_id)
def test_every_boundary_and_graphic_pair_clears_the_non_text_floor(theme, foreground, background):
    tokens = THEMES[theme]
    measured = contrast.ratio(tokens[foreground], tokens[background])
    assert measured >= contrast.AA_NON_TEXT, (
        f"--{foreground} on --{background} in {theme} is {measured:.2f}:1, below AA's {contrast.AA_NON_TEXT}"
    )


def test_the_published_table_is_the_measured_one():
    """Three spot values out of `docs/brand.md` §3, so the document and the tokens are one fact.

    Not the whole table — several of its rows fold three pairs into one cell — but enough that a
    token edited without re-measuring shows up as a document that no longer describes the product.
    """
    light, dark = THEMES["light"], THEMES["dark"]
    assert round(contrast.ratio(light["ink"], light["card"]), 2) == 17.29
    assert round(contrast.ratio(light["line-strong"], light["paper"]), 2) == 3.17
    assert round(contrast.ratio(dark["accent"], dark["card"]), 2) == 9.20


def test_the_two_themes_define_the_same_names():
    """A token that exists in light and not in dark is a colour that falls back to the wrong theme."""
    light_colours = {name for name, value in THEMES["light"].items() if value.strip().startswith("#")}
    overridden = {name for name, value in _block(':root[data-theme="dark"] {').items()}
    missing = sorted(light_colours - overridden)
    assert not missing, f"these light colours have no dark value: {missing}"
