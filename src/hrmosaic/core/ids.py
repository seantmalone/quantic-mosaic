"""Identifiers, and the one constant seed (§10.1, §12.3, §13.6).

Every id is minted from `secrets`, never from a seeded PRNG, so two interpreter runs can never
collide in a store that outlives both. `SEED` is a **module constant** — §12.3 states there is
deliberately no `SEED` environment variable — consumed only by `evaluation/**` and by the mock
data generator, which need reproducibility while ids never do.
"""

from __future__ import annotations

import hashlib
import secrets

#: The one deterministic seed in the project (§13.6). Not an environment variable, by design.
SEED = 1729


def new_session_id() -> str:
    """32-hex — `sessions.id`, which doubles as the root trace id."""
    return secrets.token_hex(16)


def new_turn_id() -> str:
    """32-hex — `turns.id`. The chat UI may supply its own, in the same shape (§11.1)."""
    return secrets.token_hex(16)


def new_span_id() -> str:
    """16-hex — `spans.id`, OTel-shaped."""
    return secrets.token_hex(8)


def user_agent_hash(user_agent: str | None) -> str | None:
    """`sha256[:16]` of a User-Agent. Raw UAs and IPs are never stored (§10.4)."""
    if not user_agent:
        return None
    return hashlib.sha256(user_agent.encode("utf-8")).hexdigest()[:16]
