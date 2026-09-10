# Pre-submission checklist — Mosaic HR Copilot

One line per requirement that **cannot** be verified by a test, because a human has to perform or
confirm it. Everything else in this project is asserted by the suite; these eight items and the
two submission steps are what is left.

Tick each box only after the thing itself is done — not after it is planned.
`tests/contract/test_docs_completeness.py` asserts this file exists and carries exactly one line
per id; it deliberately does **not** assert that a box is ticked, because a test that could tick
its own box would prove nothing.

---

## Before recording

- [ ] Gates 2, 3 and 4 of `NEEDS-FROM-USER.md` are satisfied and `scripts/smoke_deployed.py`
      passes against the live URL.
- [ ] The published `target: deployed` evaluation run is committed, `evaluation/results/latest.json`
      names it, and `python scripts/paste_eval_numbers.py` has refreshed
      `design-and-evaluation.md`'s results table from it.
- [ ] `README.md`'s `Deployed:` line carries the real tokenized `?access=` link, and
      `grep -c 'TBD-before-submission' README.md` is `0`.
- [ ] `<DEPLOY_URL>/health` returns 200 with `mcp.connected: true` and `tool_count: 9`, and the
      instance is warm (open it a minute before the take).
- [ ] `docs/demo-script.md` rehearsed end to end at least once, with a timer.
- [ ] Audio verified on a 20-second test clip.

## Demo video

- [ ] **DEMO.1** — a recorded screen-share of the **deployed** application, with screen capture
      and voiceover, the deployed URL visible in the browser address bar.
- [ ] **DEMO.2** — total length is between **7:00 and 10:00**. (The scripted plan totals 9:15.)
- [ ] **DEMO.3** — the presenter speaks throughout and is on camera for the **full** recording:
      full frame at the open, then a picture-in-picture overlay that is never cut away during any
      screen-share segment.
- [ ] **DEMO.4** — the government ID is shown, held legibly still for **≥ 3 seconds** at ~0:15 and
      framed large enough to read.
- [ ] **DEMO.5** — both agentic tasks are carried out **end to end, live, against the deployed
      URL**, from question to final cited answer/action, with no manual intervention.
- [ ] **DEMO.6** — for **each** task, all five elements are explained on camera: tool **names**,
      tool-call **arguments**, returned **outputs**, retrieved **citations**, and the **final
      answer or action**. Both per-task sub-checklists in `docs/demo-script.md` are fully ticked.
- [ ] **DEMO.7** — the walkthrough covers all four topics: **design** (0:45–1:30), **deployment**
      (6:15–7:00), **CI/CD** (7:00–7:40) and **evaluation results** (7:40–8:45).

## Submission

- [ ] **SUB.1** — both links submitted through the Quantic dashboard's *Submit Project* button:
      the recorded presentation and the GitHub repository. Both are pre-staged in the first
      20 lines of `README.md`, so this is a copy-paste.
- [ ] **SUB.2** — the deployed application URL is in `README.md` (the `Deployed:` line), and the
      link opens the app for someone who is not signed in anywhere.
- [ ] **SUB.3** — the repository is shared with the GitHub account **`quantic-grader`**. Claude
      Code sends the invite at P12 with
      `gh api -X PUT repos/seantmalone/quantic-mosaic/collaborators/quantic-grader` and reads back
      `…/collaborators/quantic-grader/permission`; confirm here that the invitation is showing as
      sent (or accepted) rather than assuming the API call was enough.

## After submitting

- [ ] Rotate `APP_ACCESS_TOKEN` once grading is complete — delete it from the Render service and
      re-run `RENDER_API_KEY=… python scripts/provision_render.py`, which mints a new one only
      when the service carries none. Do **not** do this while a grader might still be holding the
      link.
- [ ] Delete the `ci-red-evidence` branch if it still exists (the screenshot is committed; the
      branch is not needed).
- [ ] Delete `data/runtime/provision_turso.json` if provisioning left it behind.
