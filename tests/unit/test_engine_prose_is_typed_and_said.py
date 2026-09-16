"""Block typing, and the rows nobody could check (W10, rulings 5 and 6).

`_turn.html` groups every `recommendation` under *"What I suggest you do"* and footnotes the group
*"Suggestions are guidance, not company policy"*, so the type a sentence carries is a claim about
where it came from. Five of the sixteen recorded demo paths mis-typed one:

* scenarios 03, 13 and 16 filed a **mandatory step from `rules.yml`** — *"Submit the request in
  MosaicOne so the manager can approve it in writing"* — under the not-company-policy footnote;
* scenario 15 shipped the **engine's own reason** there, as though a verdict about the reader's
  request were a suggestion.

And four of them (01, 03, 07, 09) simply **left out** a `not_stated` row, so a reader was told their
request was in order on a row nobody had checked. **Every** such row gets its line — settled in the
W10 fix round, because all four of those scenarios turn on `manual` rows, which publish
`blocking: false` by construction, so a blocking-only reading would have said nothing on any of
them. Blocking rows come first: the row that can stop the request is the one the reader needs
first, and the order is the only thing separating the two classes on the page.

The citation a retyped step carries is the row it restates, and nothing else. The first version
cited `citations[0]` — the verdict's **first** evidence chunk, which on every `pto_request` turn is
the notice requirement — so a sentence about written manager approval was served under a citation to
a passage about five business days' notice.
"""

from __future__ import annotations

import json

from hrmosaic.agent import compliance as compliance_restatement


class _Envelope:
    def __init__(self, name: str, body: dict) -> None:
        self.name = name
        self.result_json = json.dumps(body)


VERDICT = {
    "scenario": "pto_request",
    "verdict": "conditional",
    "requirements": [
        {
            "id": "pto.request.notice",
            "text": "PTO requests must be submitted at least 5 business days in advance.",
            "label": "notice before the first day off, in business days",
            "status": "met",
            "met": True,
            "blocking": False,
            "reason": "computed.notice_business_days is 8; the policy value is 5 (gte).",
            "fact_key": "pto.notice.standard_days",
            "evidence": {"chunk_id": "c_notice", "doc_id": "pto-and-holidays", "heading_path": "Notice"},
        },
        {
            "id": "pto.request.manager_approval",
            "text": "Every PTO request needs written manager approval in MosaicOne.",
            "label": "written manager approval in MosaicOne",
            "status": "not_stated",
            "met": False,
            # `manual` in `corpus/rules.yml`, so the engine publishes `blocking: false` — which is
            # why no line is said for it since the W10 fix round.
            "blocking": False,
            "reason": "Not verifiable from the synthetic record; confirm before proceeding.",
            "fact_key": "pto.approval.manager_required",
            "evidence": {"chunk_id": "c_approval", "doc_id": "pto-and-holidays", "heading_path": "Approval Chain"},
        },
        {
            "id": "pto.request.balance",
            "text": "The requested days must be covered by the balance accrued at the snapshot.",
            "label": "PTO balance, in days",
            "status": "not_stated",
            "met": False,
            "blocking": True,
            "reason": "Not stated: parameters.days was not supplied.",
            "fact_key": "pto.accrual.ft_3y_plus",
            "evidence": {"chunk_id": "c_balance", "doc_id": "pto-and-holidays", "heading_path": "Accrual"},
        },
    ],
    "next_steps": ["Submit the request in MosaicOne so the manager can approve it in writing."],
    "citations": [{"chunk_id": "c_notice", "doc_id": "pto-and-holidays", "heading_path": "Notice"}],
}


def envelope() -> _Envelope:
    return _Envelope("check_policy_compliance", VERDICT)


# -- ruling 5 ---------------------------------------------------------------------------


def test_a_mandatory_step_from_the_rules_is_a_cited_policy_fact():
    block = {
        "type": "recommendation",
        "text": "Submit the request in MosaicOne so the manager can approve it in writing.",
        "citations": [],
    }
    result = compliance_restatement.apply([block], [envelope()])
    assert result.blocks[0]["type"] == "policy_fact"
    # **The row it restates**, not the verdict's first chunk. `{request, manager, mosaicone}` is
    # three content words shared with `pto.request.manager_approval` and none with the notice row.
    assert result.blocks[0]["citations"] == ["c_approval"]
    assert (0, "policy_fact") in result.retyped


def test_a_step_no_single_row_supports_stays_the_readers_record():
    """*"Move the requested dates or ask the manager to record a notice waiver with a reason."*
    restates no one requirement — it is the engine's advice about two of them — so it is not given a
    policy citation to whichever row happens to come first."""
    verdict = {
        **VERDICT,
        "next_steps": ["Move the requested dates or ask the manager to record a notice waiver with a reason."],
    }
    block = {
        "type": "recommendation",
        "text": "Move the requested dates or ask the manager to record a notice waiver with a reason.",
        "citations": [],
    }
    result = compliance_restatement.apply([block], [_Envelope("check_policy_compliance", verdict)])
    assert result.blocks[0]["type"] == compliance_restatement.RECORD
    assert result.blocks[0]["citations"] == []


def test_a_row_whose_evidence_did_not_resolve_can_support_nothing():
    uncited = {**VERDICT, "requirements": [{**row, "evidence": None} for row in VERDICT["requirements"]]}
    rows = compliance_restatement.rows([_Envelope("check_policy_compliance", uncited)])
    assert compliance_restatement.supporting_row(VERDICT["next_steps"][0], rows) is None


def test_a_restated_engine_reason_is_the_readers_record_not_advice():
    block = {"type": "recommendation", "text": "Your request does not meet the notice rule.", "citations": []}
    result = compliance_restatement.apply([block], [envelope()])
    assert result.blocks[0]["type"] == compliance_restatement.RECORD
    assert result.blocks[0]["text"].startswith("Your notice before the first day off")


def test_a_block_the_step_did_not_touch_keeps_its_type():
    block = {"type": "recommendation", "text": "Book your flights once it is approved.", "citations": []}
    result = compliance_restatement.apply([block], [envelope()])
    assert result.blocks[0]["type"] == "recommendation", "model-originated advice is advice"


def test_a_cited_policy_fact_is_never_retyped():
    block = {"type": "policy_fact", "text": "Notice is five business days.", "citations": ["c_notice"]}
    result = compliance_restatement.apply([block], [envelope()])
    assert result.blocks[0]["type"] == "policy_fact" and not result.retyped


# -- ruling 6 ---------------------------------------------------------------------------


BALANCE_LINE = "PTO balance, in days: not verified from your record — confirm before you proceed."
APPROVAL_LINE = "Written manager approval in MosaicOne: not verified from your record — confirm before you proceed."


def test_every_not_stated_row_is_said_in_one_explicit_line_blocking_first():
    """Both rows, and the blocking one first. The verdict lists `manager_approval` (a `manual`
    check, non-blocking) **before** `balance` (blocking); the lines come back the other way."""
    result = compliance_restatement.apply([], [envelope()])

    assert result.unchecked == [BALANCE_LINE, APPROVAL_LINE]
    assert result.blocks[-1]["type"] == compliance_restatement.RECORD


def test_a_manual_row_is_said_too_and_comes_after_the_blocking_ones():
    """`pto.request.manager_approval` is a `manual` check and therefore `not_stated` on every PTO
    turn — and scenarios 03, 07 and 09 are exactly that row going unsaid."""
    rows = compliance_restatement.rows([envelope()])
    manual = next(row for row in rows if row.id == "pto.request.manager_approval")
    assert (manual.status, manual.blocking) == ("not_stated", False)

    lines = compliance_restatement.not_stated_lines(rows)
    assert lines.index(APPROVAL_LINE) > lines.index(BALANCE_LINE)


def test_the_engine_order_is_kept_inside_each_class():
    """Two blocking rows stay in the order the engine evaluated them."""
    rows = [
        compliance_restatement.Row(id="a", text="", status="not_stated", reason="", label="first", blocking=True),
        compliance_restatement.Row(id="b", text="", status="not_stated", reason="", label="second", blocking=True),
        compliance_restatement.Row(id="c", text="", status="not_stated", reason="", label="third", blocking=False),
        compliance_restatement.Row(id="d", text="", status="met", reason="", label="fourth", blocking=True),
    ]
    assert [line.split(":")[0] for line in compliance_restatement.not_stated_lines(rows)] == [
        "First",
        "Second",
        "Third",
    ]


def test_a_line_the_answer_already_carries_is_not_said_twice():
    block = {"type": "record", "text": f"{BALANCE_LINE} {APPROVAL_LINE}", "citations": []}
    result = compliance_restatement.apply([block], [envelope()])
    assert result.unchecked == [] and len(result.blocks) == 1


def test_a_met_row_says_nothing_extra():
    met_only = {**VERDICT, "requirements": VERDICT["requirements"][:1]}
    result = compliance_restatement.apply([], [_Envelope("check_policy_compliance", met_only)])
    assert result.unchecked == [] and result.blocks == []
