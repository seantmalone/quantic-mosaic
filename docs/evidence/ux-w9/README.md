# UX W9 — before/after for the two Criticals of re-audit #4

Before-shots are the re-audit's own captures of the tree at `133e853`; after-shots are the W9
tree, captured the same way (`LLM_PROVIDER=stub`, `MOCK_TODAY=2026-09-01`, persona E1042).

## CPUX4-01 — the conversation owns the first viewport (P11)

| viewport | before | after |
|---|---|---|
| 1440×900, at rest | `before-chat-rest-1440x900.png` — `#transcript` pinned at its 18rem floor (288 px of a 900 px window) holding 425 px of empty state; the fourth starter and the policy link under the composer | `after-chat-rest-1440x900.png` — the transcript is the viewport less the masthead and the composer; all four starters and the policy link inside its box; the Demo & grader panel below the fold |
| 1280×800, at rest | `before-chat-rest-1280x800.png` — the same 288 px letterbox | `after-chat-rest-1280x800.png` |
| 1440×900, after demo 1 | — | `after-chat-answer-1440x900.png` — the answer read through a transcript ≥ 60 % of the viewport, the composer at the viewport's bottom edge |

Cause and fix: `.transcript { flex: 1 1 auto; min-height: 18rem }` made the floor the ceiling
while `body.chat` shared its `100dvh` with the always-expanded panel. `.conversation` now has a
definite height (`100dvh` less the measured masthead `--chrome-h` and the layout's top padding),
the transcript inside it is `min-height: 0`, and the page scrolls to the panel. Guards:
`test_p8_the_panel_is_always_expanded_and_the_conversation_keeps_its_floor` (empty state inside
the transcript's own box, transcript ≥ 60 % of the viewport, composer hittable — at 1440 and 1280)
and `test_p11_the_composer_stays_reachable_and_the_newest_message_stays_in_view` (both desktop
viewports on three turns). Both were red against HEAD's `app.css` and green against W9's.

## A11Y4-01 — an opened payload spans the row (P7)

| viewport | before | after |
|---|---|---|
| 1440×900, session waterfall | `before-dashboard-session-1440x900.png` (the page) and `before-waterfall-open-payload-1440.png` — an opened payload 35 px wide in a 352 px scroll box | `after-dashboard-session-1440x900.png` and `after-waterfall-open-payload-1440.png` — the opened `mcp_discovery` payload 1,358 px wide, the full row, on the row below its span; closed payloads still cost no row |

Cause and fix: with `details.span-payload { display: contents }`, Chrome's `::details-content`
box is the grid item, and auto-placement put it in the 35 px chevron track. It is now placed
explicitly (`grid-column: 1 / -1; grid-row: 2`, row 3 under 70rem) and has no box while closed.
Guard: `test_an_opened_payload_spans_the_row_and_closed_ones_still_cost_none` at 1440 and 1280
(`pre.clientWidth ≥ 60 %` of the row, no vertical scroller inside a box under 200 px, the closed
page height unchanged) — red against HEAD's `app.css`, green against W9's.
