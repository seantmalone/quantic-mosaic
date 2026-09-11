"""`web/api.py`'s `rate_limit_key()` — which hop §17's per-IP limiter actually counts against.

The deployed image runs uvicorn with `--forwarded-allow-ips='*'` so the scheme is right behind
Render's TLS-terminating edge. `'*'` sets uvicorn's `always_trust`, and in that mode
`_TrustedHosts.get_trusted_client_address` returns the **first** `X-Forwarded-For` entry — which is
whatever the caller sent, because each proxy *appends*. A limiter keyed on `request.client.host`
would therefore hand every caller a bucket selector: rotate the header, get a fresh 30-per-minute
budget, for ever. That is worse than the single shared bucket the flags were added to remove, and
§14 names this limit as a denial-of-service control.

`rate_limit_key()` takes the last entry instead — the one the edge itself appended — and falls back
to `request.client.host` when no such header arrives at all, which is every non-container run mode.
"""

from __future__ import annotations

from starlette.requests import Request

from hrmosaic.web.api import rate_limit_key


def _request(*forwarded_for: str, client: tuple[str, int] | None = ("10.9.9.9", 51000)) -> Request:
    """A bare ASGI scope: one `x-forwarded-for` header per argument, as a real chain arrives."""
    headers = [(b"x-forwarded-for", value.encode("latin1")) for value in forwarded_for]
    scope = {"type": "http", "method": "GET", "path": "/chat", "headers": headers, "client": client}
    return Request(scope)


def test_with_no_forwarded_header_the_key_is_the_transport_peer():
    """`make run`, `make demo1` and every test server pass no proxy flags: nothing changes there."""
    assert rate_limit_key(_request()) == "10.9.9.9"


def test_the_key_is_the_last_hop_not_the_first():
    """Behind an appending edge the last entry is the edge's own observation of the caller."""
    assert rate_limit_key(_request("203.0.113.7, 198.51.100.4")) == "198.51.100.4"


def test_a_forged_prefix_cannot_move_the_key():
    """Two callers who forge different prefixes but share an edge share one bucket."""
    first = rate_limit_key(_request("1.1.1.1, 198.51.100.4"))
    second = rate_limit_key(_request("2.2.2.2, 3.3.3.3, 198.51.100.4"))
    assert first == second == "198.51.100.4"


def test_two_genuinely_different_visitors_still_get_different_keys():
    """The point of the P20 flags: per-visitor buckets, not one bucket behind the edge."""
    assert rate_limit_key(_request("198.51.100.4")) != rate_limit_key(_request("198.51.100.5"))


def test_repeated_header_lines_are_one_chain():
    """HTTP allows the chain to arrive split across header lines; uvicorn joins them, so do we."""
    assert rate_limit_key(_request("203.0.113.7", "198.51.100.4")) == "198.51.100.4"


def test_padding_and_empty_entries_are_ignored():
    """`a, b, ` is a three-entry chain with a hole in it; the hole is not the client address."""
    assert rate_limit_key(_request("  203.0.113.7 ,  198.51.100.4 , ")) == "198.51.100.4"


def test_an_entirely_empty_header_falls_back_to_the_peer():
    """A header present but carrying nothing must not key everyone onto one empty-string bucket."""
    assert rate_limit_key(_request(" , ")) == "10.9.9.9"


def test_a_request_with_no_client_at_all_keys_on_a_constant():
    """ASGI allows `client` to be absent (a unix socket); there is nothing better than one bucket."""
    assert rate_limit_key(_request(client=None)) == "unknown"
