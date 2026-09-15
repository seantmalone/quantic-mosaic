"""Who actually approves this — the approval chain, resolved to people (spec §8.4; W8, C06).

`corpus/rules.yml` names approval **roles** ("Direct manager", "Director", "Tax & Legal"). A role is
not an answer: the live build told E1007 Dana Whitfield — *Director, Engineering* — that her trip
"requires approval from your director", and told every other persona to ask "your manager" without
ever naming one, because nothing between the rules engine and the written answer had looked the
person up.

Two rules, both from `corpus/manager-approval-matrix.md`:

* **A role resolves against the reader's own management chain.** "Direct manager" is the first
  person up the chain; "Director" and "VP" are the first person up it whose title says so. A role
  nobody in the chain holds — Tax & Legal, Finance, People Operations — is a team and stays a team.
* **Nobody approves their own request.** *"Nobody approves their own request, and nobody approves a
  request from a person who approves theirs. Where the matrix would produce that outcome, the
  request routes one level higher automatically."* So when the reader's **own** title is the role
  the request needs, the approver is the next person above them, and the entry says why.

Resolved at the tool boundary — `check_policy_compliance` and `lookup_employee_profile` — because
that is where `mock_data/org_manager_map.json` and `mock_data/employees.json` are already open, and
because a name in the envelope is a name the synthesis prompt can quote and the deterministic
backstop can put back when the model writes "your director" anyway.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

#: The sentence `manager-approval-matrix.md` states the routing rule in, verbatim, so a reader who
#: asks why an approval went one level up is given the policy's own words.
SELF_APPROVAL_SENTENCE = (
    "Nobody approves their own request, and nobody approves a request from a person who approves "
    "theirs. Where the matrix would produce that outcome, the request routes one level higher "
    "automatically."
)

#: The role a person's own record can satisfy, and the title words that say they hold it. Matched
#: case-insensitively as substrings of the title, which is how the mock titles are written
#: ("Director, Engineering", "VP Engineering", "Chief Executive Officer").
TITLE_WORDS: dict[str, tuple[str, ...]] = {
    "director": ("director",),
    "vp": ("vp", "vice president", "chief"),
}

#: How far up a chain the resolver will walk before it gives up. The deepest mock chain is three.
MAX_DEPTH = 6


class Approver(BaseModel):
    """One approval role and the person who holds it for this reader, when there is one."""

    role: str
    employee_id: str | None = None
    name: str | None = None
    title: str | None = None
    #: True when the reader's own title is the role, so the approval routed one level up.
    self_approval_routed: bool = False
    #: The policy sentence behind that routing — present only when it happened.
    reason: str | None = None


def _kind(role: str) -> str | None:
    """Which resolver a role name asks for: `manager`, `director`, `vp`, or nothing."""
    lowered = role.casefold()
    if "manager" in lowered and "business partner" not in lowered:
        return "manager"
    if "director" in lowered:
        return "director"
    if "vice president" in lowered or lowered.split()[0] == "vp":
        return "vp"
    return None


def _holds(title: str | None, kind: str) -> bool:
    lowered = (title or "").casefold()
    return any(word in lowered for word in TITLE_WORDS.get(kind, ()))


def chain(
    employee_id: str,
    *,
    employees: Mapping[str, Mapping[str, Any]],
    managers: Mapping[str, str | None],
) -> list[dict[str, Any]]:
    """Everyone above `employee_id`, nearest first. Cycles and unknown ids simply end the walk."""
    walk: list[dict[str, Any]] = []
    seen = {employee_id}
    current = managers.get(employee_id)
    while current and current not in seen and len(walk) < MAX_DEPTH:
        record = employees.get(current)
        if record is None:
            break
        walk.append(dict(record))
        seen.add(current)
        current = managers.get(current)
    return walk


def resolve(
    role: str,
    *,
    actor_id: str,
    employees: Mapping[str, Mapping[str, Any]],
    managers: Mapping[str, str | None],
) -> Approver:
    """One role, resolved for one reader. A role no chain member holds comes back as a bare role."""
    kind = _kind(role)
    if kind is None:
        return Approver(role=role)
    above = chain(actor_id, employees=employees, managers=managers)
    actor = employees.get(actor_id)
    if kind != "manager" and _holds(actor.get("title") if actor else None, kind):
        # The reader IS the role. One level higher, and say so (manager-approval-matrix.md).
        if not above:
            return Approver(role=role, self_approval_routed=True, reason=SELF_APPROVAL_SENTENCE)
        return Approver(
            role=role,
            employee_id=str(above[0]["employee_id"]),
            name=str(above[0]["preferred_name"]),
            title=str(above[0]["title"]),
            self_approval_routed=True,
            reason=SELF_APPROVAL_SENTENCE,
        )
    if kind == "manager":
        holder = above[0] if above else None
    else:
        holder = next((row for row in above if _holds(row.get("title"), kind)), None)
    if holder is None:
        return Approver(role=role)
    return Approver(
        role=role,
        employee_id=str(holder["employee_id"]),
        name=str(holder["preferred_name"]),
        title=str(holder["title"]),
    )


def resolve_all(
    roles: Sequence[str],
    *,
    actor_id: str,
    employees: Mapping[str, Mapping[str, Any]],
    managers: Mapping[str, str | None],
) -> list[Approver]:
    """Every role of one scenario, in the order the rules file lists them, without repeats."""
    resolved: list[Approver] = []
    for role in roles:
        if any(entry.role == role for entry in resolved):
            continue
        resolved.append(resolve(role, actor_id=actor_id, employees=employees, managers=managers))
    return resolved


__all__ = [
    "MAX_DEPTH",
    "SELF_APPROVAL_SENTENCE",
    "TITLE_WORDS",
    "Approver",
    "chain",
    "resolve",
    "resolve_all",
]
