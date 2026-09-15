"""`agent/outcome.py` — the post-synthesis outcome-consistency step (spec §7.4, P22).

The live demo-2 failure this exists for: the confirmation was consumed, `create_mock_hr_ticket`
returned `{"status": "created", "ticket_id": "MOCK-HR-000002", …}`, the synthesis prompt carried
that result verbatim — and the answer still ended *"I cannot open PTO requests on your behalf. You
must submit the request directly in MosaicOne…"* and never named the ticket.

So the outcome of a performed write is no longer left to the model. It is read out of the tool
result and stated first, deterministically, in a `performed` block that is the turn's **one**
account of the write: a model block of any type that names the id is the model's account of it and
goes, and so does an escalation denying the very action the result shows was performed (P29).

This is **not** a guardrail: it emits no `guardrail` span and carries no G-number (§7.4).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from hrmosaic.agent import outcome
from hrmosaic.agent.orchestrator import _ToolEnvelope

TICKET = {
    "status": "created",
    "ticket_id": "MOCK-HR-000002",
    "queue": "hr-timeoff",
    "priority": "normal",
    "created_at": "2026-09-11T14:33:07Z",
    "employee_id": "E1042",
    "mock": True,
}
DRAFT = {
    "status": "drafted",
    "draft_id": "MOCK-EMAIL-000001",
    "to_role": "manager",
    "to_name": "Priya Raman",
    "subject": "PTO request for 15-17 September",
    "sent": False,
    "mock": True,
}
REJECTED = {
    "status": "confirmation_required",
    "code": "CONFIRMATION_REQUIRED",
    "action": "create_mock_hr_ticket",
    "human_summary": 'Open an HR ticket in hr-timeoff for E1042: "PTO 15–17 Sep".',
    "arguments_preview": {"employee_id": "E1042", "queue": "hr-timeoff"},
}

POLICY_BLOCK = {
    "type": "policy_fact",
    "text": "PTO requests must be submitted at least 5 business days in advance.",
    "citations": ["c_16186f87d12c1302"],
}
DENIAL_BLOCK = {
    "type": "escalation",
    "text": (
        "I cannot open PTO requests in MosaicOne on your behalf. You must submit the request "
        "yourself in MosaicOne so your manager can record written approval."
    ),
    "citations": [],
}


def envelopes(*results) -> list[_ToolEnvelope]:
    names = {"created": "create_mock_hr_ticket", "drafted": "draft_hr_email"}
    return [
        _ToolEnvelope(
            name=names.get(str(body.get("status")), "create_mock_hr_ticket"),
            result_json=json.dumps(body, ensure_ascii=False),
        )
        for body in results
    ]


def test_a_created_ticket_is_stated_first_with_its_reference():
    """One sentence, rewritten at UX W2 (chat-production-ux-11, demo-and-grader-controls-15).

    It used to read *"Done: HR ticket MOCK-HR-000002 was opened in queue hr-timeoff (priority
    normal) — this is a mock ticket, nothing was sent outside this app."*: a routing slug, an enum
    and a disclosure about the demo, in the one sentence that tells a person their request went
    through. All three are still recorded — `queue` and `priority` on the `tool_call` span and in
    `mock_writes`, the *"writes are simulated"* line once in the demo panel (P15).
    """
    result = outcome.apply([POLICY_BLOCK], envelopes(TICKET))

    assert result.changed
    first = result.blocks[0]
    # Its own type since UX W6 (JX-R1 = cpux-re-1): a completed, irreversible write filed under
    # "What I suggest you do" and footnoted "Suggestions are guidance, not company policy" is the
    # badge W2 deleted, restored as a heading. It is neither policy nor a suggestion.
    assert first["type"] == "performed", "a write that happened is not advice"
    assert first["citations"] == [], "a tool result has no chunk_id to cite"
    # The queue's human name, through the same lookup the confirmation card uses (cpux-re-2).
    assert first["text"] == (
        "Done — your request is with the HR Time Off team. Reference MOCK-HR-000002. "
        "Your manager's written approval is the next step."
    )
    assert "hr-timeoff" not in first["text"] and "priority" not in first["text"]
    assert result.blocks[1:] == [POLICY_BLOCK], "the model's own blocks follow, untouched"


def test_a_drafted_email_is_stated_first_with_its_id():
    result = outcome.apply([POLICY_BLOCK], envelopes(DRAFT))

    assert result.blocks[0]["text"] == ("Done — the email draft is ready for Priya Raman. Reference MOCK-EMAIL-000001.")


def test_the_models_own_account_of_the_write_is_replaced_by_the_statement():
    """**P29**: the guard was right about *one account* and wrong about which one.

    This block used to survive as the account, because it names the id — so a created ticket was
    reported in whatever type the model had chosen for it, which on the live 2026-09-15 turn was a
    `recommendation` under *"What I suggest you do"* (JX-R1 = cpux-re-1). Only the tool result can
    attest a write, so the model's sentence goes and the `performed` statement takes its place.
    """
    stated = {
        "type": "recommendation",
        "text": "Your request is filed as MOCK-HR-000002 in the hr-timeoff queue.",
        "citations": [],
    }

    result = outcome.apply([stated], envelopes(TICKET))

    assert [block["type"] for block in result.blocks] == ["performed"]
    assert result.blocks[0]["text"] == (
        "Done — your request is with the HR Time Off team. Reference MOCK-HR-000002. "
        "Your manager's written approval is the next step."
    )
    assert result.replaced == [0], "the model's own block index, before the statement is inserted"
    assert result.stated and result.changed
    assert "hr-timeoff" not in " ".join(block["text"] for block in result.blocks), "the slug left with it"


def test_an_escalation_denying_the_performed_write_is_dropped_under_the_statement():
    """**One account of the write per turn** (UX W6, JX-R1 = cpux-re-1).

    The denial is what the statement above it was in the way of, so where the statement runs the
    denial simply goes. Replacing it with a reassuring line instead printed *"Done — your request
    is with HR"* and *"That is already taken care of — there is nothing further for you to file"*
    two bullets apart, which is the answer saying the same thing twice in two voices.
    """
    result = outcome.apply([POLICY_BLOCK, DENIAL_BLOCK], envelopes(TICKET))

    assert [block["type"] for block in result.blocks] == ["performed", "policy_fact"]
    assert result.blocks[0]["text"] == (
        "Done — your request is with the HR Time Off team. Reference MOCK-HR-000002. "
        "Your manager's written approval is the next step."
    )
    assert "cannot" not in " ".join(block["text"] for block in result.blocks).lower()
    assert result.replaced == [1], "the model's block index, before the outcome block is inserted"


def test_the_models_account_and_its_denial_both_go_under_the_one_statement():
    """An answer that both claims the ticket and denies it keeps neither sentence (P29)."""
    stated = {"type": "recommendation", "text": "Ticket MOCK-HR-000002 is open.", "citations": []}

    result = outcome.apply([stated, DENIAL_BLOCK], envelopes(TICKET))

    assert [block["type"] for block in result.blocks] == ["performed"], "one account, from the tool result"
    assert result.stated
    assert result.replaced == [0, 1], "both of the model's own block indexes"


def test_a_model_block_typed_performed_that_names_the_id_is_replaced_not_duplicated():
    """The demotion and the removal meet on one block: it leaves exactly one `performed` block."""
    claimed = {"type": "performed", "text": "I have opened ticket MOCK-HR-000002 for you.", "citations": []}

    result = outcome.apply([claimed, POLICY_BLOCK], envelopes(TICKET))

    assert [block["type"] for block in result.blocks] == ["performed", "policy_fact"]
    assert result.blocks[0]["text"] == (
        "Done — your request is with the HR Time Off team. Reference MOCK-HR-000002. "
        "Your manager's written approval is the next step."
    )
    assert "I have opened" not in " ".join(block["text"] for block in result.blocks)
    assert result.replaced == [0]


def test_a_model_that_types_a_block_performed_is_demoted_to_advice():
    """`performed` asserts the outcome of a call the model has not been shown the result of. Only
    this step, reading the tool envelope, may make that claim (UX W6)."""
    claimed = {"type": "performed", "text": "I have filed your request.", "citations": []}

    result = outcome.apply([claimed], [])

    assert result.blocks == [{**claimed, "type": "recommendation"}]
    assert not result.changed


def test_an_escalation_about_something_else_survives_the_write():
    """G5's contact is not collateral: only a denial of the performed action is replaced."""
    sensitive = {
        "type": "escalation",
        "text": (
            "This raises a potential discrimination concern, which I will not handle here. "
            "Contact People Operations at people-ops@mosaicrobotics.example."
        ),
        "citations": [],
    }

    result = outcome.apply([sensitive], envelopes(TICKET))

    assert result.blocks[1] == sensitive
    assert result.replaced == []


def test_a_write_that_was_only_proposed_states_nothing():
    """The gated attempt returns `CONFIRMATION_REQUIRED` and writes nothing (§8.6)."""
    result = outcome.apply([POLICY_BLOCK, DENIAL_BLOCK], envelopes(REJECTED))

    assert result.blocks == [POLICY_BLOCK, DENIAL_BLOCK]
    assert not result.changed
    assert outcome.performed_write(envelopes(REJECTED)) is None


def test_a_turn_with_no_write_at_all_is_untouched():
    balance = _ToolEnvelope(name="check_pto_balance", result_json='{"remaining_days": 13.5}')

    result = outcome.apply([POLICY_BLOCK, DENIAL_BLOCK], [balance])

    assert result.blocks == [POLICY_BLOCK, DENIAL_BLOCK]
    assert not result.changed


def test_an_unreadable_write_envelope_is_ignored_rather_than_raising():
    broken = _ToolEnvelope(name="create_mock_hr_ticket", result_json="not json at all")

    assert outcome.performed_write([broken]) is None
    assert outcome.apply([POLICY_BLOCK], [broken]).blocks == [POLICY_BLOCK]


def test_the_last_performed_write_of_the_turn_is_the_one_reported():
    second = {**TICKET, "ticket_id": "MOCK-HR-000003", "queue": "hr-general"}

    result = outcome.apply([POLICY_BLOCK], envelopes(TICKET, second))

    assert "MOCK-HR-000003" in result.blocks[0]["text"]


def test_the_step_has_a_name_and_it_is_not_a_guardrail_number():
    assert outcome.STEP_NAME == "outcome_consistency"
    assert not outcome.STEP_NAME.startswith("G")


def test_an_escalation_denying_a_performed_draft_points_at_the_draft():
    denial = {
        "type": "escalation",
        "text": "I cannot send email on your behalf. Write to your manager yourself.",
        "citations": [],
    }

    result = outcome.apply([denial], envelopes(DRAFT))

    assert [block["type"] for block in result.blocks] == ["performed"]
    assert "MOCK-EMAIL-000001" in result.blocks[0]["text"]
    assert "cannot" not in result.blocks[0]["text"].lower()


def test_a_result_missing_its_queue_says_exactly_what_a_full_one_says():
    """The sentence is the reference, so a thinner result makes no difference to the reader."""
    thin = {"status": "created", "ticket_id": "MOCK-HR-000009"}

    result = outcome.apply([POLICY_BLOCK], envelopes(thin))

    # The unnamed fallback is a department and takes no article; a named team does.
    assert result.blocks[0]["text"] == "Done — your request is with HR. Reference MOCK-HR-000009."


def test_a_success_status_with_no_id_is_not_a_write_to_report():
    """The sentence is the id; a body without one is nothing to state."""
    idless = _ToolEnvelope(name="create_mock_hr_ticket", result_json='{"status": "created"}')

    assert outcome.performed_write([idless]) is None


# --------------------------------------------------------------------------------------
# `next_steps` — the same contradiction, one line further down the same answer
# --------------------------------------------------------------------------------------

#: Exactly what the recorded demo-2 synthesis emits (`tests/fixtures/llm_scripts/demo_task_2.json`).
DEMO_2_STEPS = [
    "Log into MosaicOne and submit your PTO request for 15–17 September 2026.",
    "Your manager will receive the request and must approve it in writing within MosaicOne.",
    "Once approved, the three days will be deducted from your PTO balance.",
]


def test_a_next_step_telling_the_reader_to_file_the_request_is_dropped():
    """The twin of the escalation case: `render_answer` puts next steps in the same answer."""
    result = outcome.apply([POLICY_BLOCK], envelopes(TICKET), next_steps=DEMO_2_STEPS)

    assert result.next_steps == DEMO_2_STEPS[1:], "only the directive to go and file it goes"
    assert result.dropped == [0], "the model's own next_steps index"
    assert result.changed


def test_a_next_step_that_is_not_aimed_at_the_reader_survives():
    """A statement about someone else carries the object and no imperative at the reader."""
    steps = [
        "Watch for your manager's approval in MosaicOne.",
        "Dana Whitfield approves request MOCK-HR-000123 in hr-timeoff.",
        "Your manager will receive the request and must approve it in writing.",
    ]

    result = outcome.apply([POLICY_BLOCK], envelopes(TICKET), next_steps=steps)

    assert result.next_steps == steps
    assert result.dropped == []


def test_a_next_step_that_names_the_ticket_survives_even_in_the_imperative():
    """It is talking about the ticket that exists, not asking for a second one."""
    steps = ["Open MOCK-HR-000002 in the mock-action log if you want to see the request."]

    result = outcome.apply([POLICY_BLOCK], envelopes(TICKET), next_steps=steps)

    assert result.next_steps == steps
    assert result.dropped == []


def test_an_imperative_about_something_else_survives_the_write():
    """An imperative verb is not enough: the object has to be the thing the tool made."""
    steps = [
        "Open the PTO & Holidays Policy and read section 4 before your manager replies.",
        "Please submit your expense report separately in the finance portal.",
    ]

    result = outcome.apply([POLICY_BLOCK], envelopes(TICKET), next_steps=steps)

    assert result.next_steps == steps
    assert result.dropped == []


def test_politeness_in_front_of_the_verb_does_not_hide_the_directive():
    steps = [
        "Please submit the PTO request in MosaicOne yourself.",
        "You need to file a ticket for the three days.",
        "Make sure to open a request with HR.",
    ]

    result = outcome.apply([POLICY_BLOCK], envelopes(TICKET), next_steps=steps)

    assert result.next_steps == []
    assert result.dropped == [0, 1, 2]


def test_a_next_step_telling_the_reader_to_write_the_email_is_dropped():
    steps = [
        "Send the email to your manager yourself once you have checked the dates.",
        "Your manager usually replies within two business days.",
    ]

    result = outcome.apply([POLICY_BLOCK], envelopes(DRAFT), next_steps=steps)

    assert result.next_steps == steps[1:]
    assert result.dropped == [0]


def test_next_steps_are_untouched_when_nothing_was_performed():
    """No write, no contradiction: the gated attempt leaves the model's advice alone."""
    for turn_envelopes in (envelopes(REJECTED), [_ToolEnvelope(name="check_pto_balance", result_json="{}")]):
        result = outcome.apply([POLICY_BLOCK], turn_envelopes, next_steps=DEMO_2_STEPS)

        assert result.next_steps == DEMO_2_STEPS
        assert result.dropped == []
        assert not result.changed


def test_next_steps_default_to_nothing_when_the_caller_passes_none():
    """`apply` is called for the blocks alone in the unit tests above; that stays legal."""
    assert outcome.apply([POLICY_BLOCK], envelopes(TICKET)).next_steps == []


def test_directs_needs_both_halves_for_the_tool_that_performed_the_write():
    """The matrix the two word lists encode, stated once."""
    assert outcome.directs("Submit your PTO request in MosaicOne.", "create_mock_hr_ticket")
    assert not outcome.directs("Submit your PTO request in MosaicOne.", "draft_hr_email")
    assert not outcome.directs("The request was submitted for you.", "create_mock_hr_ticket")
    assert not outcome.directs("Open the policy document.", "create_mock_hr_ticket")
    assert not outcome.directs("Submit your PTO request.", "check_pto_balance"), (
        "a read-only tool performs nothing, so no advice can contradict it"
    )


# --------------------------------------------------------------------------------------
# The live turn of 2026-09-15 — the defect the one-account rule was wrong about
# --------------------------------------------------------------------------------------

#: The confirmed write's own result, verbatim from `docs/evidence/demo-task-2-live-2026-09-15-
#: session.json` (the `create_mock_hr_ticket` `tool_call` span that followed the confirmation).
LIVE_TICKET = {
    "status": "created",
    "ticket_id": "MOCK-HR-000007",
    "queue": "hr-timeoff",
    "priority": "normal",
    "created_at": "2026-09-15T18:34:30Z",
    "employee_id": "E1042",
    "mock": True,
    "url": "/dashboard/safety#MOCK-HR-000007",
}

#: …and the six `answer_blocks` the same turn stored, in order. The last one is the model's own
#: account of the write, which the old guard read as *the* account and left filed under
#: "What I suggest you do" with "Suggestions are guidance, not company policy" beneath it.
LIVE_BLOCKS = [
    {
        "type": "policy_fact",
        "text": "PTO requests must be submitted at least 5 business days in advance.",
        "citations": ["c_16186f87d12c1302"],
    },
    {
        "type": "policy_fact",
        "text": "Full-time employees with three or more years of service accrue 1.50 days of PTO per month.",
        "citations": ["c_e178629918c7cd96"],
    },
    {
        "type": "policy_fact",
        "text": "Every PTO request requires written approval from the employee's direct manager in MosaicOne.",
        "citations": ["c_d57a7964d974ba44"],
    },
    {
        "type": "policy_fact",
        "text": "PTO requests of any length are approved by the employee's direct manager.",
        "citations": ["c_9948839107acfaaf"],
    },
    {
        "type": "recommendation",
        "text": (
            "Your PTO balance as of 1 September 2026 is 13.5 days remaining, which covers your "
            "three-day request. You have 8 business days of notice, which exceeds the 5-day "
            "requirement. Submit the request in MosaicOne for Dana's written approval."
        ),
        "citations": [],
    },
    {
        "type": "recommendation",
        "text": "HR ticket MOCK-HR-000007 has been created to track your time-off request.",
        "citations": [],
    },
]

#: The one next step the same turn kept. It names nothing the tool did and is not aimed at the
#: reader, so it survives — as it did live.
LIVE_STEPS = ["Dana will review and approve in writing"]


def test_the_live_turn_reports_the_write_in_the_performed_block_and_not_as_advice():
    """`docs/evidence/demo-task-2-live-2026-09-15-session.json`, turn 1, through the fixed step.

    What the page painted on the live path: four policy facts, a recommendation, and *"HR ticket
    MOCK-HR-000007 has been created to track your time-off request."* — a completed, irreversible
    write printed under *"What I suggest you do"* and footnoted *"Suggestions are guidance, not
    company policy"*, with no `performed` block anywhere in the turn (JX-R1 = cpux-re-1).
    """
    balance = _ToolEnvelope(name="check_pto_balance", result_json='{"remaining_days": 13.5, "as_of": "2026-09-01"}')
    result = outcome.apply(LIVE_BLOCKS, [*envelopes(LIVE_TICKET), balance], next_steps=LIVE_STEPS)

    assert result.blocks[0] == {
        "type": "performed",
        "text": (
            "Done — your request is with the HR Time Off team. Reference MOCK-HR-000007. "
            "Your manager's written approval is the next step."
        ),
        "citations": [],
    }
    assert result.blocks[1:5] == LIVE_BLOCKS[:4], "the four policy facts survive, in order and untouched"
    # Since UX W7 (Addendum 3, JX2-05) the fifth block loses its one directive sentence — *"Submit
    # the request in MosaicOne for Dana's written approval."* — and what is left, the reader's own
    # balance and notice, is typed as their record rather than filed as advice.
    assert result.blocks[5] == {
        "type": "record",
        "text": (
            "Your PTO balance as of 1 September 2026 is 13.5 days remaining, which covers your "
            "three-day request. You have 8 business days of notice, which exceeds the 5-day requirement."
        ),
        "citations": [],
    }
    assert result.trimmed == [(4, "Submit the request in MosaicOne for Dana's written approval.")]
    assert result.retyped == [4] and result.emptied == []
    assert "has been created" not in " ".join(block["text"] for block in result.blocks[1:])
    assert [block["type"] for block in result.blocks].count("performed") == 1
    assert result.replaced == [5] and result.stated
    assert result.next_steps == LIVE_STEPS and result.dropped == []


# --------------------------------------------------------------------------------------
# UX W7, Addendum 3 — no *sentence* tells the reader to file the request the write filed
# --------------------------------------------------------------------------------------

#: The exact resumed turn the owner saw live on 2026-09-15 at 20:04Z, verbatim: the six blocks the
#: page painted and the three envelopes the synthesis carried (`tests/fixtures/live_turns/`).
CONFIRMED = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "live_turns" / "demo2_confirm_2026-09-15.json").read_text(
        encoding="utf-8"
    )
)
CONFIRMED_BLOCKS: list[dict] = CONFIRMED["answer_blocks"]
CONFIRMED_ENVELOPES = [_ToolEnvelope(name=e["name"], result_json=e["result_json"]) for e in CONFIRMED["envelopes"]]

#: What the owner read: the lede says the request is filed; the suggestion says to file it.
DIRECTIVE = re.compile(r"\b(submit|file|raise|log|open|enter)\b.{0,40}\brequest", re.IGNORECASE)


def test_the_live_confirmed_turn_keeps_no_sentence_that_tells_the_reader_to_file_the_request():
    """*"Done — your request is with the HR Time Off team. Reference MOCK-HR-000009."* and then,
    under *"What I suggest you do"*: *"… Submit the request in MosaicOne so your manager can approve
    it in writing."* The step dropped a next STEP that directed the reader and never looked inside a
    block. It looks now: the directive sentence goes, the balance and notice sentences stay and are
    the reader's record, and the statement says what actually happens next."""
    result = outcome.apply(CONFIRMED_BLOCKS, CONFIRMED_ENVELOPES)

    assert result.blocks[0] == {
        "type": "performed",
        "text": (
            "Done — your request is with the HR Time Off team. Reference MOCK-HR-000009. "
            "Your manager's written approval is the next step."
        ),
        "citations": [],
    }
    assert result.blocks[1:5] == CONFIRMED_BLOCKS[1:5], "the four policy facts are untouched"
    assert result.blocks[5] == {
        "type": "record",
        "text": "You have 13.5 days remaining. Your three-day request is covered by your balance.",
        "citations": [],
    }
    assert len(result.blocks) == 6
    assert result.trimmed == [(5, "Submit the request in MosaicOne so your manager can approve it in writing.")]
    assert result.retyped == [5] and result.emptied == [] and result.replaced == [0]
    assert result.changed
    for block in result.blocks:
        assert not outcome.directs(block["text"], "create_mock_hr_ticket"), block
        assert not DIRECTIVE.search(block["text"]), block


def test_the_step_is_idempotent_on_the_live_turn():
    once = outcome.apply(CONFIRMED_BLOCKS, CONFIRMED_ENVELOPES)
    twice = outcome.apply(once.blocks, CONFIRMED_ENVELOPES, next_steps=once.next_steps)
    assert twice.blocks == once.blocks
    assert twice.trimmed == [] and twice.emptied == [] and twice.retyped == []


def test_a_recommendation_with_no_directive_in_it_is_untouched():
    advice = {
        "type": "recommendation",
        "text": "Your manager will receive the request and must approve it in writing.",
        "citations": [],
    }
    result = outcome.apply([advice], envelopes(TICKET))
    assert result.blocks[1] == advice
    assert result.trimmed == [] and result.retyped == []


def test_a_directive_sentence_that_names_the_ticket_is_kept():
    """It is talking about the request that exists, not asking for another."""
    block = {
        "type": "recommendation",
        "text": "Quote MOCK-HR-000002 if you contact HR. Submit the request in MosaicOne so it is on file.",
        "citations": [],
    }
    result = outcome.apply([block], envelopes(TICKET))
    # The block names the id, so it is the model's own account of the write and is replaced
    # whole (P29) — the id sentence is kept only in a block that is not that account.
    assert result.replaced == [0]

    quoting = {"type": "recommendation", "text": "Quote the reference if you contact HR.", "citations": []}
    directing = {
        "type": "recommendation",
        "text": "Quote the reference if you contact HR. Submit the request in MosaicOne so it is on file.",
        "citations": [],
    }
    result = outcome.apply([quoting, directing], envelopes(TICKET))
    assert result.blocks[1] == quoting
    assert result.blocks[2]["text"] == "Quote the reference if you contact HR."
    assert result.trimmed == [(1, "Submit the request in MosaicOne so it is on file.")]
    # "Quote …" opens with a directive verb, so what is left is still advice, not the record.
    assert result.blocks[2]["type"] == "recommendation" and result.retyped == []


def test_a_block_that_was_nothing_but_the_directive_is_dropped():
    only = {"type": "recommendation", "text": "Enter the request in MosaicOne for approval.", "citations": []}
    result = outcome.apply([POLICY_BLOCK, only], envelopes(TICKET))
    assert result.blocks == [result.blocks[0], POLICY_BLOCK]
    assert result.emptied == [1] and result.trimmed == [(1, "Enter the request in MosaicOne for approval.")]


def test_a_modal_lead_in_does_not_hide_the_directive():
    block = {
        "type": "recommendation",
        "text": "You have 13.5 days remaining. You could submit the request in MosaicOne today.",
        "citations": [],
    }
    balance = _ToolEnvelope(name="check_pto_balance", result_json='{"remaining_days": 13.5}')
    result = outcome.apply([block], [*envelopes(TICKET), balance])
    assert result.blocks[1] == {"type": "record", "text": "You have 13.5 days remaining.", "citations": []}


def test_the_next_event_is_said_only_for_a_pto_ticket():
    benefits = {**TICKET, "queue": "hr-benefits", "ticket_id": "MOCK-HR-000003"}
    result = outcome.apply([POLICY_BLOCK], envelopes(benefits))
    assert result.blocks[0]["text"] == "Done — your request is with the HR Benefits team. Reference MOCK-HR-000003."


def test_sentences_split_where_a_reader_hears_a_full_stop():
    text = "You have 13.5 days left. See e.g. section 4. Submit the request in MosaicOne. Done!"
    assert outcome.sentences(text) == [
        "You have 13.5 days left.",
        "See e.g. section 4.",
        "Submit the request in MosaicOne.",
        "Done!",
    ]


# --------------------------------------------------------------------------------------
# UX W7, JX2-05 = cpux2-4 — the reader's own record is not advice, on any turn
# --------------------------------------------------------------------------------------

#: The demo-2 stub's own balance sentence, as `tests/fixtures/llm_scripts/demo_task_2.json` has it.
STUB_BALANCE = {
    "type": "recommendation",
    "text": (
        "You have 13.5 PTO days remaining, so a 3-day request is covered by your balance. Your request "
        "for 15–17 September meets the 5-business-day notice requirement (8 business days' notice)."
    ),
    "citations": [],
}
BALANCE = _ToolEnvelope(name="check_pto_balance", result_json='{"remaining_days": 13.5, "as_of": "2026-09-01"}')


def test_the_demo_2_balance_sentence_is_the_readers_record_not_advice():
    """Printed under *"What I suggest you do"* and disclaimed *"not company policy"*: a reader told
    their own balance is non-binding (JX2-05). No write on this turn; the rule is the number."""
    result = outcome.apply([POLICY_BLOCK, STUB_BALANCE], [BALANCE])
    assert result.blocks == [POLICY_BLOCK, {**STUB_BALANCE, "type": "record"}]
    assert result.retyped == [1] and result.changed and not result.stated


def test_a_genuine_recommendation_with_a_number_in_it_stays_advice():
    advice = {"type": "recommendation", "text": "File the request at least 21 days before 3 November.", "citations": []}
    notice = _ToolEnvelope(name="check_policy_compliance", result_json='{"computed": {"notice_days": 21}}')
    result = outcome.apply([advice], [notice])
    assert result.blocks == [advice] and result.retyped == []


def test_a_number_the_tools_did_not_return_makes_no_record():
    guess = {"type": "recommendation", "text": "Most people keep 5 days in reserve.", "citations": []}
    assert outcome.apply([guess], [BALANCE]).blocks == [guess]


def test_a_policy_claim_g3_demoted_is_never_retyped_as_the_record():
    """An uncited `policy_fact` G3 relabelled `recommendation` is a policy claim wearing the wrong
    label. It states the policy's number, which the compliance tool also returns."""
    claim = {
        "type": "recommendation",
        "text": "PTO requests must be submitted at least 5 business days in advance.",
        "citations": [],
    }
    rule = _ToolEnvelope(name="check_policy_compliance", result_json='{"policy": {"notice_days": 5}}')
    assert outcome.apply([claim], [rule], policy_claims=[0]).blocks == [claim]
    assert outcome.apply([claim], [rule]).blocks == [{**claim, "type": "record"}], (
        "…and without the exemption it would be"
    )


def test_a_search_envelope_and_a_boolean_are_not_the_readers_numbers():
    one = {"type": "recommendation", "text": "Only 1 approval is needed for this.", "citations": []}
    search = _ToolEnvelope(name="search_policy_documents", result_json='{"hits": [{"rank": 1, "dense_score": 0.7}]}')
    flag = _ToolEnvelope(name="check_policy_compliance", result_json='{"requirements": [{"met": true}]}')
    assert outcome.apply([one], [search, flag]).blocks == [one]
    assert outcome.envelope_numbers([search, flag]) == set()


def test_envelope_numbers_are_read_however_deep_they_sit():
    nested = _ToolEnvelope(
        name="lookup_employee_profile",
        result_json='{"tenure_months_at_as_of": 45, "history": [{"months": 12}], "as_of": "2026-09-01"}',
    )
    assert outcome.envelope_numbers([nested]) == {45.0, 12.0}
    assert outcome.numbers_in("45 months, 3-day, 13.5 days, v2.1, by 2026.") == {45.0, 3.0, 13.5, 2026.0}
