# Pre-submission checklist — Mosaic HR Copilot

One line per requirement that **cannot** be verified by a test, because a human has to perform or
confirm it. Everything else in this project is asserted by the suite; the **ten id lines** below —
seven `DEMO.*` and three `SUB.*` — plus the un-numbered boxes on either side of them are what is
left.

Tick each box only after the thing itself is done — not after it is planned.
`tests/contract/test_docs_completeness.py` asserts this file exists and carries exactly one line
per id; it deliberately does **not** assert that a box is ticked, because a test that could tick
its own box would prove nothing.

**The independent assessment.** An independent, read-only grading pass against
`docs/project-requirements.md` was run on 2026-09-11 and is committed verbatim as
[`docs/evidence/grade-card-2026-09-11.md`](evidence/grade-card-2026-09-11.md). Its §4 is a
checklist of what the recording has to show for the demo requirements to hold, and its §6 lists the
things a grader is most likely to trip over. Read both before the take. The defects it found were
fixed in the P23 commits; the two it names as outside the repository — the video link and the
dashboard submission — are the `DEMO.1` and `SUB.1` boxes below.

---

## Before recording

- [x] Gates 2, 3 and 4 of `NEEDS-FROM-USER.md` are satisfied and `scripts/smoke_deployed.py`
      passes against the live URL. — **done 2026-09-10** (`NEEDS-FROM-USER.md`'s Discharged table).
- [x] The published `target: deployed` evaluation run is committed, `evaluation/results/latest.json`
      names it, and `python scripts/paste_eval_numbers.py` has refreshed
      `design-and-evaluation.md`'s results table from it. — **done 2026-09-11**,
      `r_1789086979_baseline`.
- [x] `README.md`'s `Deployed:` line carries the real tokenized `?access=` link, and
      `grep -c 'TBD-before-submission' README.md` is `0`. — **done 2026-09-10**.
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
- [x] **SUB.3** — the repository is shared with the GitHub account **`quantic-grader`**, and the
      invitation has been **accepted**: `gh api
      repos/seantmalone/quantic-mosaic/collaborators/quantic-grader/permission` returns
      `{"permission":"read", …,"role_name":"read"}` and `gh api
      repos/seantmalone/quantic-mosaic/invitations` returns `[]` — nothing still pending, which is
      what distinguishes an accepted invite from a sent one. Re-verified 2026-09-11.

## After submitting

- [ ] Rotate `APP_ACCESS_TOKEN` once grading is complete — delete it from the Render service and
      re-run `RENDER_API_KEY=… python scripts/provision_render.py`, which mints a new one only
      when the service carries none. Do **not** do this while a grader might still be holding the
      link.
- [ ] Delete the `ci-red-evidence` branch if it still exists (the screenshot is committed; the
      branch is not needed).
- [ ] Delete `data/runtime/provision_turso.json` if provisioning left it behind.
