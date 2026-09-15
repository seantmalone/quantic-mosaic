"""**P7** and **P12** completed, on the painted page in both colour schemes (`pytest -m ux`, UX W5).

`tests/ux/test_principles.py` already asserts the half of P12 that W2 built: Enter sends, focus
comes back to the composer, there is one live region and it says one plain sentence per turn. This
file is the rest of the wave's list, and every test here is one of `4.E`'s findings:

* the **skip link** and the landmark it reaches (accessibility-and-responsive-16);
* a **visible focus indicator** on every stop of the keyboard walk (accessibility-and-responsive-4);
* **tap targets** no smaller than 44 px on a phone;
* **no rendered type below the floor** (accessibility-and-responsive-20);
* **reduced motion** honoured by the stylesheet and by Chart.js (accessibility-and-responsive-19);
* **contrast** measured on what the browser actually painted, in light *and* dark — the token half
  is `tests/contract/test_brand_contrast.py`, and the two share `tests/support/contrast.py`;
* **colour is never the only encoding** of a state;
* **every form control has a name**;
* **focus follows the decision** when a turn asks for one (accessibility-and-responsive-4).

Everything runs against the session-scoped `ux_server` unless it needs an unspent stub script, so
the file adds one server to the suite and not nine.
"""

from __future__ import annotations

import re

import pytest

from tests.support import contrast
from tests.ux.conftest import TOKEN

pytestmark = pytest.mark.ux

CHAT_AND_DASHBOARD = ("/", "/dashboard", "/dashboard/evals")

#: Everything a keyboard can land on, minus the things that are deliberately not on screen.
INTERACTIVE = "a[href], button, input:not([type=hidden]), select, textarea, summary, [tabindex]:not([tabindex='-1'])"

#: Every element that holds text of its own, with the colours the browser resolved for it. The
#: background is the nearest painted ancestor, which is what a reader's eye composites against.
PAINTED_TEXT_JS = r"""
() => {
  const painted = (el) => {
    let node = el;
    while (node) {
      const value = getComputedStyle(node).backgroundColor;
      if (value && value !== "transparent" && !/^rgba\(0, 0, 0, 0\)$/.test(value)) return value;
      node = node.parentElement;
    }
    return "rgb(255, 255, 255)";
  };
  const path = (el) => {
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && parts.length < 4) {
      let seg = node.tagName.toLowerCase();
      if (node.id) { seg += "#" + node.id; parts.unshift(seg); break; }
      if (node.classList.length) seg += "." + Array.from(node.classList).join(".");
      parts.unshift(seg);
      node = node.parentElement;
    }
    return parts.join(" > ");
  };
  const out = [];
  for (const el of document.querySelectorAll("body *")) {
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden" || parseFloat(style.opacity) === 0) continue;
    const box = el.getBoundingClientRect();
    if (box.width <= 1 || box.height <= 1) continue;   // visually-hidden text is 1x1 and clipped
    const own = Array.from(el.childNodes)
      .filter((node) => node.nodeType === 3 && node.textContent.trim())
      .map((node) => node.textContent.trim()).join(" ");
    if (!own) continue;
    out.push({
      path: path(el), text: own.slice(0, 60),
      color: style.color, background: painted(el),
      size: parseFloat(style.fontSize), weight: parseInt(style.fontWeight, 10) || 400,
    });
  }
  return out;
}
"""

#: The size of every interactive control a reader can actually hit.
TARGETS_JS = """
(selector) => Array.from(document.querySelectorAll(selector))
  .filter((el) => {
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") return false;
    if (el.closest(".visually-hidden") || el.classList.contains("skip-link")) return false;
    const box = el.getBoundingClientRect();
    return box.width > 0 && box.height > 0;
  })
  .map((el) => {
    // The target is what a thumb can hit, which for a checkbox or a radio is the `<label>` wrapped
    // around it — clicking anywhere in that label activates the control. A 13px checkbox inside a
    // 44px label is a 44px target; sizing the box itself up instead just paints a huge square.
    const label = el.closest("label");
    const box = (label && (el.type === "checkbox" || el.type === "radio") ? label : el).getBoundingClientRect();
    return {
      tag: el.tagName.toLowerCase(),
      name: (el.id || el.className || el.textContent || "").toString().trim().slice(0, 50),
      width: Math.round(box.width * 10) / 10, height: Math.round(box.height * 10) / 10,
    };
  })
"""

#: What the browser paints on the element that currently has focus.
FOCUS_JS = """
() => {
  const el = document.activeElement;
  if (!el || el === document.body) return null;
  const style = getComputedStyle(el);
  return {
    tag: el.tagName.toLowerCase(),
    name: (el.id || el.className || el.textContent || "").toString().trim().slice(0, 50),
    boxShadow: style.boxShadow, outlineStyle: style.outlineStyle, outlineWidth: style.outlineWidth,
  };
}
"""


def _signed_in(browser, base_url: str, **context_options):
    context = browser.new_context(viewport={"width": 1440, "height": 900}, **context_options)
    tab = context.new_page()
    tab.goto(f"{base_url}/?access={TOKEN}", wait_until="networkidle")
    return context, tab


# -- accessibility-and-responsive-16: the skip link and the landmark ----------------------


@pytest.mark.parametrize("route", CHAT_AND_DASHBOARD)
def test_the_skip_link_is_the_first_stop_and_lands_on_the_page(page, ux_server, route):
    """Before it, a keyboard reader walked the masthead — and, on the dashboard, eleven page links —
    on every navigation before reaching anything the page is about."""
    page.goto(f"{ux_server}{route}", wait_until="networkidle")
    page.keyboard.press("Tab")

    first = page.evaluate("() => document.activeElement && document.activeElement.className")
    assert first == "skip-link", f"the first stop in the tab order is {first!r}"

    box = page.eval_on_selector(".skip-link", "e => e.getBoundingClientRect().toJSON()")
    assert box["top"] >= 0, f"the focused skip link is off screen: {box}"

    page.keyboard.press("Enter")
    page.wait_for_timeout(200)
    landed = page.evaluate("() => document.activeElement && document.activeElement.id")
    assert landed == "main-content", f"following the skip link left focus on {landed!r}"


# -- accessibility-and-responsive-4: a focus indicator on every stop ----------------------


@pytest.mark.parametrize("route", CHAT_AND_DASHBOARD)
def test_every_keyboard_stop_paints_a_visible_focus_indicator(page, ux_server, route):
    """`app.css` had no `:focus-visible` rule at all before the brand landed, and the ring it grew
    is a `box-shadow` — which forced-colours modes do not paint, hence the transparent outline
    beside it. This walks the page with Tab and checks every stop shows one of the two."""
    page.goto(f"{ux_server}{route}", wait_until="networkidle")
    unringed, seen = [], 0
    for _ in range(40):
        page.keyboard.press("Tab")
        focused = page.evaluate(FOCUS_JS)
        if focused is None:
            break
        seen += 1
        ringed = focused["boxShadow"] != "none" or (
            focused["outlineStyle"] not in ("none", "") and focused["outlineWidth"] not in ("0px", "")
        )
        if not ringed:
            unringed.append(focused["name"])

    assert seen >= 5, f"the keyboard walk found only {seen} stops on {route}"
    assert not unringed, f"these controls take focus and paint nothing: {unringed}"


# -- tap targets --------------------------------------------------------------------------


@pytest.mark.parametrize("route", CHAT_AND_DASHBOARD)
def test_every_control_is_at_least_44px_on_a_phone(page, ux_server, route):
    """A 29 px pill is a mouse target. 44 px is the figure WCAG 2.5.5 names and the one the plan
    carries, and below 40 rem the stylesheet holds every control to it."""
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{ux_server}{route}", wait_until="networkidle")
    page.wait_for_timeout(200)

    small = [
        target for target in page.evaluate(TARGETS_JS, INTERACTIVE) if target["width"] < 44 or target["height"] < 44
    ]
    assert not small, f"these are under 44px at 390x844: {small}"


# -- accessibility-and-responsive-20: the type floor --------------------------------------


@pytest.mark.parametrize("route", CHAT_AND_DASHBOARD)
def test_no_text_renders_below_the_type_floor(page, ux_server, route):
    """`body { font: 16px }` and `body.dashboard { font-size: 17px }` pinned body copy to pixels; the
    ramp fixed that, but `0.85em` of an already-small parent kept drifting under it. 13 px is the
    floor `--text-floor` names, and it is the size `--text-meta` sets."""
    page.goto(f"{ux_server}{route}", wait_until="networkidle")
    tiny = sorted({(item["size"], item["path"]) for item in page.evaluate(PAINTED_TEXT_JS) if item["size"] < 13})
    assert not tiny, f"text below the 13px floor: {tiny}"


#: `font: …16px…` or `font-size: 14px` in any rule. It replaced W2's narrower guard, which looked
#: for the one `body { font: 16px/… }` rule the brand sweep had already removed.
PIXEL_TYPE = re.compile(r"font(?:-size)?\s*:[^;{}]*?\b\d+(?:\.\d+)?px")


@pytest.mark.parametrize("sheet", ("/static/app.css", "/static/brand/brand.css"))
def test_the_stylesheet_declares_no_pixel_type(page, ux_server, sheet):
    """A `px` font-size ignores the reader's own browser setting, whatever its value is. Both
    sheets: the ramp lives in `brand.css` and every size in `app.css` draws on it."""
    css = page.evaluate("url => fetch(url).then(r => r.text())", f"{ux_server}{sheet}")
    assert css.strip(), f"{sheet} did not load"
    pixels = PIXEL_TYPE.findall(css)
    assert not pixels, f"{sheet} sizes type in pixels: {pixels}"


# -- accessibility-and-responsive-19: reduced motion ---------------------------------------


def test_a_reader_who_asked_for_less_motion_gets_none(browser, ux_server):
    """Both halves: the stylesheet's transitions, and Chart.js, which animates every one of the six
    canvases by default and offered no opt-out at all."""
    context, tab = _signed_in(browser, ux_server, reduced_motion="reduce")
    try:
        tab.goto(f"{ux_server}/dashboard", wait_until="networkidle")
        tab.wait_for_timeout(400)

        durations = tab.evaluate(
            "() => Array.from(document.querySelectorAll('a, button'))"
            ".map(el => getComputedStyle(el).transitionDuration)"
            ".filter(value => value && parseFloat(value) > 0.01)"
        )
        assert not durations, f"these controls still animate under reduced motion: {durations[:5]}"

        animated = tab.evaluate("() => typeof Chart === 'undefined' ? null : Chart.defaults.animation")
        assert animated is False, f"Chart.js still animates under reduced motion: {animated!r}"
    finally:
        context.close()


# -- contrast, on the painted page, in both colour schemes ---------------------------------


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("route", CHAT_AND_DASHBOARD)
def test_the_painted_page_clears_aa_in_both_colour_schemes(browser, ux_server, scheme, route):
    """The tokens all pass on their own (`tests/contract/test_brand_contrast.py`). This is the other
    half: a *rule* that puts one of them on the wrong ground — a soft ink on an accent fill, a muted
    label on a sunk panel — passes the token check and fails here."""
    context, tab = _signed_in(browser, ux_server, color_scheme=scheme)
    try:
        tab.goto(f"{ux_server}{route}", wait_until="networkidle")
        tab.wait_for_timeout(200)
        failures = []
        for item in tab.evaluate(PAINTED_TEXT_JS):
            floor = contrast.floor_for(font_px=item["size"], font_weight=item["weight"])
            measured = contrast.ratio(item["color"], item["background"])
            if measured < floor:
                failures.append(f"{item['path']} {measured:.2f}:1 < {floor} — {item['text']!r}")
        assert not failures, f"{scheme} {route}: " + "; ".join(sorted(set(failures))[:8])
    finally:
        context.close()


# -- colour is never the only encoding ------------------------------------------------------


def test_no_state_is_painted_in_colour_alone(page, ux_server):
    """Every pill, flag and status marker names its state in words as well as in hue — including the
    failed step on the waterfall, which used to be red, bold and nothing else."""
    page.goto(f"{ux_server}/dashboard/safety", wait_until="networkidle")
    wordless = page.evaluate(
        "() => Array.from(document.querySelectorAll('.pill, .flag'))"
        ".filter(el => !el.textContent.trim())"
        ".map(el => el.className)"
    )
    assert not wordless, f"these carry a state in colour and no word: {wordless}"


# -- every control has a name ---------------------------------------------------------------


@pytest.mark.parametrize("route", ("/", "/dashboard/turns"))
def test_every_form_control_carries_a_label(page, ux_server, route):
    """A `<select>` or a text field whose only name is its position is unusable by voice or by
    screen reader; the filter bars are eleven of them on one page."""
    page.goto(f"{ux_server}{route}", wait_until="networkidle")
    unnamed = page.evaluate(
        "() => Array.from(document.querySelectorAll('input:not([type=hidden]), select, textarea'))"
        ".filter(el => {"
        "  if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return false;"
        "  if (el.closest('label')) return false;"
        "  return !(el.id && document.querySelector('label[for=\"' + el.id + '\"]'));"
        "})"
        ".map(el => el.name || el.id || el.outerHTML.slice(0, 60))"
    )
    assert not unnamed, f"these form controls have no accessible name: {unnamed}"


# -- accessibility-and-responsive-4: focus follows the decision -------------------------------


@pytest.mark.parametrize("scripted_server", ["demo_task_2.json"], indirect=True)
def test_a_turn_that_asks_for_a_decision_moves_focus_to_it(scripted_page, scripted_server):
    """`hx-disabled-elt` blurs the pressed Send button to `<body>`, and the confirm card arrives with
    no id htmx could restore from — so the one thing the reader now has to answer was reachable only
    by hunting for it."""
    scripted_page.goto(f"{scripted_server}/", wait_until="networkidle")
    scripted_page.fill(
        "#message",
        "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
        "— and can you open the request for me?",
    )
    scripted_page.click("#send-button")
    scripted_page.wait_for_selector(".confirm-card", timeout=180_000)
    scripted_page.wait_for_timeout(600)

    focused = scripted_page.evaluate("() => document.activeElement && document.activeElement.className")
    assert focused == "confirm-heading", f"focus went to {focused!r}, not to the decision"

    in_view = scripted_page.eval_on_selector(
        ".confirm-heading", "e => { const b = e.getBoundingClientRect(); return b.top >= 0 && b.bottom <= 900; }"
    )
    assert in_view, "the decision is focused but off screen"


# -- keyboard reachability of the two controls that only exist sometimes ---------------------


@pytest.mark.parametrize("scripted_server", ["fault_ambiguous.json"], indirect=True)
def test_stop_and_try_again_are_reachable_from_the_keyboard(scripted_page, scripted_server):
    """The brief's third keyboard requirement, and the two controls it is hardest to satisfy for.

    **Stop** exists only while a turn is running, and starting one disables the composer (which
    blurs it to `<body>`) and hides the button that was just pressed — so a keyboard reader had no
    position at all for the length of the turn. **Try again** exists only on a failed turn, and a
    failed turn is the moment a reader most needs it. Both are now real stops: Stop takes focus when
    it appears, and the retry button is in the tab order of the turn that failed.
    """
    scripted_page.goto(f"{scripted_server}/", wait_until="networkidle")

    # The in-flight state, held open by never answering the POST. Sleeping inside the handler
    # instead would block the sync driver, so every assertion below it would run *after* the turn
    # had already finished — which is how the first draft of this test passed nothing at all.
    held: list[object] = []

    def hold(route):
        held.append(route)

    scripted_page.route("**/chat", hold)
    scripted_page.fill("#message", "Can I take some time off soon?")
    scripted_page.click("#send-button")
    scripted_page.wait_for_timeout(600)

    assert held, "the composer did not send"
    assert scripted_page.eval_on_selector("#stop-button", "e => !e.hidden"), "Stop replaces Send while busy"
    assert scripted_page.evaluate("() => document.activeElement && document.activeElement.id") == "stop-button", (
        "a running turn left the keyboard with no position"
    )

    # Stop is client-side and gives the composer back, which is the other half of the contract.
    scripted_page.click("#stop-button")
    scripted_page.wait_for_timeout(300)
    assert scripted_page.evaluate("() => document.activeElement && document.activeElement.id") == "message"

    # Nothing reached the server, so the one-entry script is still unspent: a reload starts clean,
    # the first question is answered with a clarification and the second exhausts the script into
    # the graceful error turn that carries **Try again**.
    scripted_page.unroute("**/chat")
    scripted_page.goto(f"{scripted_server}/", wait_until="networkidle")
    scripted_page.fill("#message", "Can I take some time off soon?")
    scripted_page.click("#send-button")
    scripted_page.wait_for_selector("#messages .turn", timeout=180_000)
    scripted_page.wait_for_timeout(800)

    scripted_page.fill("#message", "And what about carrying unused days into next year?")
    scripted_page.click("#send-button")
    scripted_page.wait_for_selector(".button-retry", timeout=180_000)
    scripted_page.wait_for_timeout(500)

    reachable = scripted_page.evaluate(
        "() => { const button = document.querySelector('.button-retry');"
        " button.focus();"
        " const style = getComputedStyle(button);"
        " return {focused: document.activeElement === button, ring: style.boxShadow,"
        "         hidden: button.offsetParent === null}; }"
    )
    assert reachable["focused"] and not reachable["hidden"], f"Try again is not reachable: {reachable}"
