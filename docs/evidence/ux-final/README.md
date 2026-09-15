# The final screen set

Every surface the product has, at the end of the five-wave UX remediation
(`docs/superpowers/plans/2026-09-14-ux-remediation-plan.md`), photographed by `make ux-capture`
against four stub servers on loopback — `LLM_PROVIDER=stub`, no live model call, no request to the
deployed URL, one shared trace store so the dashboard shows all four conversations.

This directory is the **set the report and the README cite**. The whole capture is 69 screen ids ×
3 viewports, with the `.txt` DOM dumps, `.numbers.json` and `.overflow.json` the original audit
measured, and it is one command away in the git-ignored `.ux-capture/`.

| Suffix | What it is |
|---|---|
| `-1440.png` | the screen **at the fold** at 1440×900, which is the comparison a reader makes |
| `-390.png` | the same screen at 390×844 — the phone |
| `-dark-1440.png` | the same screen at 1440×900 with `prefers-color-scheme: dark` emulated |

`body_horizontal_scroll` is **false on every one of the 69 ids at all three viewports** — the number
`make ux-capture` prints at the end of its own run, and the last line of the W5 report.

## Chat — the production surface

| Screen | What it shows |
|---|---|
| `chat-rest-1440.png` | the empty conversation: a greeting by name, one line saying what the assistant answers from, four starter questions, a sticky composer. No rail, no badges, no ids |
| `chat-answer-1440.png` | a cited multi-document answer — policy facts as prose, suggestions grouped once under their own heading with one footnote, the snapshot note, and the always-visible **Sources (6)** strip |
| `zoom-sources-1440.png` | the sources strip with every reference expanded: document title · section, the quoted passage, and *"Open the full policy"* into the reader route |
| `chat-confirm-card-1440.png`, `zoom-confirm-card-1440.png` | the confirmation gate before a write: the fields a person needs, the queue's human name, *"Nothing is written until you choose."* Since W5 this card's heading is also where focus lands |
| `chat-refusal-1440.png` | an out-of-corpus question refused in plain language, naming five example policies and linking the library |
| `chat-clarify-1440.png` | an ambiguous question answered with a question, and two quick replies that prefill the composer |
| `chat-error-degraded-1440.png` | a turn that failed mid-flight, with the question it failed on and a **Try again** |
| `demo-panel-1440.png` | the *Demo & grader controls* panel, opened. It ships collapsed, so this screen opens it |
| `chat-rest-390.png`, `chat-answer-390.png` | the phone: one column, the composer on the bottom edge, all four starters inside the transcript |

## Reader, key page and refusals

| Screen | What it shows |
|---|---|
| `policy-reader-1440.png` | where a citation goes — the policy as a document, not a chunk inspector |
| `access-key-page-1440.png` | pre-auth: product name, one sentence, one field, one button |
| `refused-page-1440.png` | an HTML refusal is a themed page with the masthead and a route back, never a bare JSON body |

## Dashboard — the technical record

`dashboard-overview`, `-sessions`, `-session-demo1`, `-turns`, `-llm`, `-retrieval`, `-tools`,
`-safety`, `-mcp`, `-corpus`, `-corpus-doc`, `-evals`, `-eval-run`, each `-1440.png`: the shared
masthead and grouped page nav, a title with a one-line lede, human columns first with ids as
8-character chips, every number through one formatter, wide tables scrolling inside their own box.
`dashboard-overview-390.png`, `dashboard-session-demo1-390.png` and `dashboard-turns-390.png` are the
phone: a 13-column table becomes a stack of cards, the eleven-item page nav becomes one row that
scrolls inside itself, and the span waterfall keeps its per-step durations.

## Both colour schemes

`brand.css` has shipped a whole dark palette since W2 and no screen of the audit had ever been taken
in it. The `-dark-1440.png` files are the second pass `make ux-capture` now runs with
`color_scheme="dark"`: the key page, chat at rest, the answered conversation, the demo panel, and
the overview, session, guardrails, evaluations and run pages. The dark pass asks **no new question**
— the four servers share one trace store, so `/?session=<id>` rehydrates the conversation the light
pass produced.

Contrast in both schemes is measured rather than eyeballed:
`tests/contract/test_brand_contrast.py` recomputes every `docs/brand.md` §3 pair from the shipped
tokens, and `tests/ux/test_accessibility.py` measures the colours the browser actually resolved on
these very pages.
