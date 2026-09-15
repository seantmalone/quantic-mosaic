"""Every class a template paints with has a rule in the one stylesheet (UX W2 review, fix round 1).

The app ships **one** stylesheet, shared by the chat surface and the eleven dashboard pages, and the
UX remediation plan rewrites it a wave at a time. W2 swept the chat half: the rail, the trace panel
and the citation *chips* went, and with them `.citation-chips` / `.citation-chip` — which chat no
longer renders, but `dashboard/session_detail.html` still does. The sweep's own orphan check only
read the two chat templates, so the dashboard's cited chunks quietly regressed to a default bulleted
list of plain links on a page W2 was not scoped to touch. Nothing failed.

This is that check, over **every** template, run on every commit. It is deliberately one-directional
— a class with no rule is a defect, a rule with no class is only dead weight — and it carries an
explicit allowlist of the classes that are *meant* to be unstyled, so adding one is a decision
somebody writes down rather than a silence.
"""

from __future__ import annotations

import re
from pathlib import Path

from hrmosaic.web.api import PACKAGE_DIR

TEMPLATES = PACKAGE_DIR / "templates"
STYLESHEETS = (PACKAGE_DIR / "static" / "app.css", PACKAGE_DIR / "static" / "brand" / "brand.css")

#: Classes that carry no paint on purpose: hooks for scripts, for tests, or names that exist only to
#: say what an element *is*. Each one is a deliberate no-op, not a missing rule.
UNSTYLED_BY_DESIGN = {
    # `_turn.html` names each answer block by its type so a grader reading the HTML can see which
    # guardrail produced it. The paint is on `.answer-block` and `.answer-text`.
    "answer-block-policy_fact",
    "answer-block-recommendation",
    "answer-block-escalation",
    # Structural hooks with no appearance of their own.
    "source",  # the `<li>` around a `.source-details`
    "source-link",  # "Open the full policy" — an ordinary link, deliberately
    "wordmark",  # the masthead lockup is sized by the `<img>` rules on `.masthead h1 img`
    "tab-panel",  # the eval pages' panels; the tabs beside them are painted
    # JavaScript hooks.
    "demo-button",  # painted by `.button`; the class is what the busy switch queries
    "kind-toggle",  # the span-kind checkboxes on the session page
}

#: `class="pill pill-{{ turn.outcome }}"` — the literal half of a computed class. A prefix is
#: satisfied by any rule that starts with it, which is how `.pill-error` and friends are found.
PREFIX = re.compile(r"^[a-z][a-z0-9-]*-$")


def _classes_by_template() -> dict[str, set[str]]:
    used: dict[str, set[str]] = {}
    for template in sorted(TEMPLATES.rglob("*.html")):
        for attribute in re.findall(r'class="([^"]*)"', template.read_text(encoding="utf-8")):
            # A Jinja expression inside the attribute contributes no literal class of its own.
            for name in re.sub(r"\{[{%].*?[%}]\}", " ", attribute).split():
                used.setdefault(name, set()).add(str(template.relative_to(TEMPLATES)))
    return used


def _ruled() -> set[str]:
    return {name for sheet in STYLESHEETS for name in re.findall(r"\.([A-Za-z][A-Za-z0-9_-]*)", _selectors_only(sheet))}


def _selectors_only(sheet: Path) -> str:
    """The stylesheet with its declaration blocks removed, so a `url(.foo)` cannot count as a rule."""
    return re.sub(r"\{[^{}]*\}", " ", sheet.read_text(encoding="utf-8"))


def test_every_class_a_template_paints_with_has_a_rule():
    ruled, orphans = _ruled(), {}
    for name, templates in _classes_by_template().items():
        if name in UNSTYLED_BY_DESIGN:
            continue
        if PREFIX.match(name):
            if not any(rule.startswith(name) for rule in ruled):
                orphans[name] = sorted(templates)
            continue
        if name not in ruled:
            orphans[name] = sorted(templates)

    assert not orphans, (
        "these classes are rendered but no longer styled — a wave's deletions reached a consumer "
        f"it was not scoped to touch: {orphans}"
    )


def test_the_dashboards_citation_chips_are_painted():
    """The regression this file was written for, named so its failure reads as itself."""
    ruled = _ruled()
    detail = (TEMPLATES / "dashboard" / "session_detail.html").read_text(encoding="utf-8")
    assert 'class="citation-chips"' in detail and 'class="citation-chip"' in detail
    assert {"citation-chips", "citation-chip"} <= ruled


def test_the_allowlist_is_still_about_classes_that_exist():
    """An allowlist entry for a class no template renders any more is stale; drop it."""
    used = set(_classes_by_template())
    assert UNSTYLED_BY_DESIGN <= used, f"stale allowlist entries: {sorted(UNSTYLED_BY_DESIGN - used)}"
