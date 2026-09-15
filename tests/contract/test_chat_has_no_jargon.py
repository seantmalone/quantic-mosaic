"""**P2 and P13**: no internal identifier, and no infrastructure vocabulary, anywhere in chat.

The permanent guard for a whole class of defect. `docs/superpowers/plans/2026-09-14-ux-remediation-plan.md`
§1 states both principles with a mechanical detection rule, and this file is that rule, run over the
**rendered** chat surface in every turn state the app can reach:

| state | script |
|---|---|
| at rest, and a cited multi-document answer | `demo_task_1` |
| the confirmation card, and the confirmed resume | `demo_task_2` |
| a refusal (G1's evidence gate) | `out_of_corpus_tuition` |
| a clarification, and the graceful error turn | `fault_ambiguous` |

Three denylists, because the audiences differ:

* **`MARKUP_FORBIDDEN`** runs over the HTML a browser is sent, minus `<script>` blocks and HTML
  comments (source a reader never sees) and minus `href` values — the reader route `/policy/{doc_id}#{chunk_id}`
  carries a chunk id *by design*, as the address of a passage, and W1 shipped it on purpose.
* **`TEXT_FORBIDDEN`** runs over what the page actually says — tags stripped, entities resolved —
  because `<span>` is markup and "span" is jargon, and only one of the two is a defect.
* **`COPY_FORBIDDEN`** is **P13** proper, and runs over the app's *own* words — the chat page with
  no turn on it, and every user-facing sentence `g1`, the orchestrator and `web/api` write. It
  cannot run over a rendered answer: a cited policy passage is allowed to say what the policy says.

Every value these patterns forbid still exists, unrounded, on the dashboard and in `/api/*` (P15).
"""

from __future__ import annotations

import html as html_module
import re

import pytest

pytestmark = pytest.mark.anyio

HTMX = {"HX-Request": "true"}

#: One question per stub script, and what the turn it produces is for.
CASES = (
    ("demo_task_1.json", "I want to work from Berlin from 3 November to 14 December 2026 — can I?", "answered"),
    (
        "demo_task_2.json",
        "Can I take three days of PTO from Tuesday 15 September to Thursday 17 September 2026 "
        "— and can you open the request for me?",
        "awaiting_confirmation",
    ),
    (
        "out_of_corpus_tuition.json",
        "What is Mosaic's tuition reimbursement cap for a part-time master's degree, and how many "
        "years of service do I need to qualify?",
        "refused",
    ),
    ("fault_ambiguous.json", "Can I take some time off soon?", "clarify"),
)

#: **P2**, over the markup. Span kinds, guardrail ids, provider:model, token arithmetic, similarity
#: scores, chunk ids and raw JSON — each of these was on the chat page before UX W2, and each of
#: them is a thing only a grader reading a trace can use.
MARKUP_FORBIDDEN = (
    # **The employee id.** The re-audit found `E1007` fifteen times on one answered turn, in prose
    # about a person — *"your director (Dana, E1007)"*. `api.without_employee_ids()`, the `no_ids`
    # filter and `synthesize.j2` rule 6c are the mechanism that keeps it off the page; this is the
    # invariant, and it is what makes the regression fail something (UX W6, npo2-02). The rule runs
    # over the markup, not the text, because an id can arrive as an attribute as easily as a
    # sentence — and the demo panel, whose persona control names ids on purpose, is already cut.
    r"\bE1[0-9]{3}\b",
    r"data-chunk-id",
    r"\bc_[0-9a-f]{8}",
    r"stub:stub",
    r"\bG[1-6]_",
    r"→\s*\d+\s*tok",
    r"top dense",
    r"best match [0-9]",
    r"max dense score",
    r"evidence-gate score",  # G1's reason since UX W4 — the span's words, never the reader's
    r"verdict=",
    r"purpose=",
    r"intent=",
    r"catalog_reopened",
    r"chunk_id",
    r"\{&#34;|\{\"",
    r"class=\"badge",
    r"trace-panel",
    r"span-rail",
)

#: **P2**, over what the page says, plus the protocol words of **P13** that cannot occur in a
#: quoted policy passage. `queue`/`priority` are covered by the snake_case rule and `hr-timeoff` by
#: the slug one; `copilot` is the assistant naming itself in the third person.
#:
#: Two P13 words are deliberately **not** here — *"audit trail"* and *"deployment"*. Both are
#: ordinary HR English that this corpus itself uses (*"the approval must be recorded against the
#: request so the audit trail is complete"*, from the PTO policy demo 2 quotes), and a rule that
#: forbade a cited passage from saying what the policy says would be the wrong rule. They are
#: checked where the principle actually points — the app's **own** copy — by the test below.
TEXT_FORBIDDEN = (
    r"\bspans?\b",
    r"\btraces?\b",
    r"\b[a-z]+_[a-z]+\b",
    r"\b\d+\s*ms\b",
    r"\bMCP\b",
    r"\bBearer\b",
    r"tokenized",
    r"/health",
    r"/ready",
    r"eval runner",
    r"copilot",
    r"\bhr-[a-z]+\b",
)

#: **P13**, over the app's own words: the chat chrome and every user-facing string the agent
#: writes. Infrastructure, protocol and deployment vocabulary has no place in either.
COPY_FORBIDDEN = (
    r"\bMCP\b",
    r"\bBearer\b",
    r"\bcookie\b",
    r"tokenized",
    r"/health",
    r"/ready",
    r"audit trail",
    r"deployment",
    r"eval runner",
    r"copilot",
    r"\bspans?\b",
    r"\btraces?\b",
)

#: The demo panel is quarantined scaffolding, labelled as such, and W3 owns it. It is the one
#: region of the page this guard skips — a grader control may say grader things.
DEMO_PANEL = re.compile(r'<section class="demo-panel".*?</section>', re.S)


def _chat_markup(page: str) -> str:
    """The chat surface as a browser is sent it, minus what a reader can never read."""
    body = re.sub(r"<head\b.*?</head>", "", page, flags=re.S)
    body = DEMO_PANEL.sub("", body)
    body = re.sub(r"<script\b.*?</script>", "", body, flags=re.S)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    return re.sub(r'href="[^"]*"', 'href=""', body)


def _visible_text(page: str) -> str:
    """What the page says: tags stripped, entities resolved."""
    return html_module.unescape(re.sub(r"<[^>]+>", " ", _chat_markup(page)))


def _assert_clean(page: str, *, where: str) -> None:
    markup, text = _chat_markup(page), _visible_text(page)
    for pattern in MARKUP_FORBIDDEN:
        found = re.findall(pattern, markup)
        assert not found, f"{where}: the markup carries {pattern!r} — {found[:3]}"
    for pattern in TEXT_FORBIDDEN:
        found = re.findall(pattern, text, flags=re.I)
        assert not found, f"{where}: the page says {pattern!r} — {found[:3]}"


async def test_the_chat_page_at_rest_says_nothing_technical(web):
    async with web() as client:
        page = (await client.get("/")).text

    _assert_clean(page, where="GET / at rest")


@pytest.mark.parametrize("script,question,state", CASES, ids=[state for _, _, state in CASES])
async def test_no_turn_state_leaks_an_identifier_or_a_protocol_word(web, script, question, state):
    async with web(script) as client:
        fragment = (await client.post("/chat", json={"message": question}, headers=HTMX)).text

    _assert_clean(fragment, where=f"a {state} turn from {script}")


async def test_the_confirmed_resume_and_the_card_it_replaces_are_both_clean(web):
    """The write path: the card's fields, then the answer that reports the write (§8.6)."""
    async with web("demo_task_2.json") as client:
        card = await client.post("/chat", json={"message": CASES[1][1]}, headers=HTMX)
        ids = re.search(r'data-session-id="([0-9a-f]+)" *\n? *data-turn-id="([0-9a-f]+)"', card.text)
        assert ids, card.text[:400]
        done = await client.post(
            "/chat/confirm",
            json={"session_id": ids.group(1), "turn_id": ids.group(2), "decision": "confirmed"},
            headers=HTMX,
        )

    assert done.status_code == 200, done.text
    _assert_clean(card.text, where="the confirmation card")
    _assert_clean(done.text, where="the confirmed resume")
    assert "Goes to" in card.text and "HR Time Off team" in card.text, "the queue's human name, not its slug"


async def test_a_failed_turn_is_clean_and_carries_the_question_to_retry(web):
    """`fault_ambiguous` holds one scripted reply; the second question exhausts it (§12.3)."""
    async with web("fault_ambiguous.json") as client:
        await client.post("/chat", json={"message": CASES[3][1]}, headers=HTMX)
        failed = await client.post(
            "/chat", json={"message": "And what about carrying unused days into next year?"}, headers=HTMX
        )

    assert failed.status_code == 200
    assert 'data-outcome="error"' in failed.text
    _assert_clean(failed.text, where="the failed turn")
    assert "And what about carrying unused days into next year?" in failed.text
    assert "Try again" in failed.text, "a failed turn offers a retry (chat-production-ux-20)"


async def test_the_apps_own_copy_and_every_agent_written_string_use_plain_language(web):
    """**P13**, where the principle points: the chrome, and the strings the agent authors.

    The rendered denylist above cannot judge a quoted policy passage — the corpus is allowed to say
    *"audit trail"*, because that is what the PTO policy says. This one judges the app: the chat
    page with no turn on it, and every user-facing sentence `g1`, the orchestrator and `web/api`
    write themselves.
    """
    from hrmosaic.agent import orchestrator
    from hrmosaic.agent.guardrails import g1
    from hrmosaic.web import api

    async with web() as client:
        chrome = _visible_text((await client.get("/")).text)

    written = [
        g1.USER_REFUSAL,
        *g1.refusal(g1.OUT_OF_SCOPE).next_steps,
        *orchestrator.CLARIFY_QUESTIONS.values(),
        orchestrator.CLARIFY_FALLBACK,
        *(chip for chips in orchestrator.CLARIFY_CHIPS.values() for chip in chips),
        *orchestrator.CLARIFY_FALLBACK_CHIPS,
        orchestrator.WRITE_FAILED_NOTE,
        api.INTERNAL_ERROR_TEXT,
        api.INTERNAL_ESCALATION_TEXT,
        api.SUGGESTION_FOOTNOTE,
        api.FOREIGN_SESSION_NOTICE,
        *api.BLOCK_HEADINGS.values(),
        *api.DECISION_LINES.values(),
        *api.STARTER_PROMPTS,
        # The five sentences the one live region announces a finished turn with (UX W3). They are
        # the app talking about itself out loud, which is exactly where P13 points.
        *api.TURN_ANNOUNCEMENTS.values(),
        api.TURN_ANNOUNCEMENT_FALLBACK,
    ]
    for subject, where in [(chrome, "the chat page at rest"), (" ".join(written), "the agent's own copy")]:
        for pattern in COPY_FORBIDDEN:
            found = re.findall(pattern, subject, flags=re.I)
            assert not found, f"{where} says {pattern!r} — {found[:3]}"
