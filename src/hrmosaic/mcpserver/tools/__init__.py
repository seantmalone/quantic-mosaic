"""The nine tools of spec §8.4, one module each, registered in the order the spec lists them.

Names match the requirement's enumerated list exactly (R5.3) plus `list_policy_documents`, which is
ours and deliberately extra, so `tests/contract/test_tools_match_spec.py` is a literal string
comparison against a live `tools/list`.

Tools 1–4 read the RAG index, 5–7 read the committed mock datasets, 8–9 perform gated mock writes.
"""

from hrmosaic.mcpserver.tools import (
    check_policy_compliance,
    check_pto_balance,
    create_mock_hr_ticket,
    draft_hr_email,
    get_policy_section,
    list_policy_documents,
    lookup_benefits_status,
    lookup_employee_profile,
    search_policy_documents,
)

#: In §8.4 order; `tools/list` is sorted by the client anyway (§8.2 step 2).
REGISTRARS = (
    search_policy_documents.register,
    get_policy_section.register,
    list_policy_documents.register,
    check_policy_compliance.register,
    lookup_employee_profile.register,
    check_pto_balance.register,
    lookup_benefits_status.register,
    create_mock_hr_ticket.register,
    draft_hr_email.register,
)

#: The eight names the requirement itself enumerates, plus ours.
TOOL_NAMES = (
    "search_policy_documents",
    "get_policy_section",
    "list_policy_documents",
    "check_policy_compliance",
    "lookup_employee_profile",
    "check_pto_balance",
    "lookup_benefits_status",
    "create_mock_hr_ticket",
    "draft_hr_email",
)

__all__ = ["REGISTRARS", "TOOL_NAMES"]
