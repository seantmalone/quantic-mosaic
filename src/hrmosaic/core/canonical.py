"""The one canonical serialisation of a proposed tool-argument set (spec §8.6 step 5).

It lives in `core/` because two packages on opposite sides of the §4.2 dependency line need the
*same bytes*: `mcpserver/confirm.py` mints and compares them at the confirmation gate, and
`evaluation/deterministic.py` re-computes them to check clause 2 of §13.4 (a confirmed write whose
arguments differ from the ones the human approved). A second implementation of this function would
be a silent way for a mismatched replay to pass, so there is exactly one — and `evaluation/` reaches
it through `core/`, never by importing `hrmosaic.mcpserver`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

#: The argument every write tool accepts and no schema requires; never part of what is compared.
TOKEN_ARGUMENT = "confirmation_token"


def canonical_arguments(arguments: Mapping[str, Any]) -> str:
    """Serialise `arguments` the one way both sides of a confirmation agree on.

    `confirmation_token` is excluded, keys are sorted and separators are tight, so the bytes minted
    at Confirm time and the bytes computed from the resumed call are comparable without either side
    knowing how the other built its dict.
    """
    body = {key: value for key, value in arguments.items() if key != TOKEN_ARGUMENT}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
