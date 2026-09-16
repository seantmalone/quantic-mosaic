# UX W8 fix round — before and after, for the four Criticals of re-audit #3

Four pairs. Each pair is the same screen id at the same viewport.

* **before** — re-audit #3's own capture set, the screens its auditors judged on 2026-09-16
  (`make ux-capture` on `16217b7`, LOCAL, `LLM_PROVIDER=stub`, **no `MOCK_TODAY`** — which is
  itself C3's defect).
* **after** — `make ux-capture` on this fix round's head, same harness, the five scripted servers
  (a fifth, `write_blocked.json`, photographs C02's refusal branch on purpose), `MOCK_TODAY`
  pinned to the stubs' submission date. No live model call was made and `.env` was never read.

| Finding | before → after | what changed |
|---|---|---|
| **C1 · CPUX3-01 = a11y-r3-1** — on a phone every turn landed the reader on the demo controls: `stickToBottom()` scrolled the *document* to its end, which under the always-expanded panel is ~700px below the answer; the composer's textarea sat under the masthead | `c1-chat-answer-390-before.png` → `c1-chat-answer-390-after.png` | "the bottom" is the newest turn's end, kept just above the sticky composer; `atBottom()` and `#jump-latest` track the turn, not the scroller; the guard requires the turn's end inside the viewport, above the composer, and the textarea under its own centre — at 390 after a turn, after a `/?session=` reload and after a resize |
| **C2 · JX3-01 = CPUX3-02 = npo4-04** — *"Your notice business days is 0"*: a `rules.yml` subject key with its underscores swapped for spaces, on every finished PTO turn | `c2-c3-chat-after-confirm-1440-before.png` → `c2-c3-chat-after-confirm-1440-after.png` | every requirement carries a reader `label` (34 of them, build-checked); the restatement is built from the label and the row's values in words; the 21 key-shaped leaves joined the chat denylist |
| **C3 · JX3-02 = dgc-r3-6** — a filed ticket narrated beside the notice rule it broke, because the capture's servers had no `MOCK_TODAY` and the recorded 15 September request was scored against the wall clock | same pair as C2 | `MOCK_TODAY=2026-09-01` wherever the stubs replay (Makefile, `ux_capture.py`, the ux server fixture, CI); the recorded 8 business days are met; a contract test pins the stub's verdict and the absence of an unmet-notice sentence; the refusal branch has its own screen (`chat-write-blocked`) |
| **C4 · DR3-01** — the desktop session waterfall painted three bands per span (4,372px at 1440) because `.span-row` placed columns but not rows | `c4-dashboard-session-1440-before.png` → `c4-dashboard-session-1440-after.png` | rows declared as well as columns; one `li` per span; the page is under 3,400px at 1440 and under 5,000px at 390, and the chevron sits on its own row |

The "after" files are the fold captures (`*.fold.png`) of the same screen ids; the full-page and
sidecar files live in the capture directory the round's report names.
