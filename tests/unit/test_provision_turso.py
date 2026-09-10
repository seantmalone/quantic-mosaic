"""`scripts/provision_turso.py` against a recorded Turso Platform API, never a live one (spec §14.6).

The script runs exactly once, with a platform token this repository has never held, against an API
whose free tier would happily create 100 databases if a loop went wrong. So every request it makes
is pinned here through an `httpx.MockTransport` that speaks the documented wire shapes — the
`{"database": {"DbId", "Hostname", "Name"}}` envelope of `POST /v1/organizations/{org}/databases`
and the `{"jwt": …}` of `POST …/auth/tokens` — and the assertions are about *what it sends*: the
right method, the right path, `Authorization: Bearer`, `expiration=never`,
`authorization=full-access`.

The second half covers the P1 carry-forward this script is the first thing in the project able to
answer: `TursoHTTPStore` has never met a live database, and nothing has ever asserted whether
foreign keys are enforced on the Hrana path. `parity_smoke()` is what asks, and the tests below fix
its verdicts — including the honest one, that an accepted foreign-key violation is a loud warning
rather than a failed provisioning run.
"""

from __future__ import annotations

import json

import httpx
import pytest

from hrmosaic.core.db import StoreError, TursoHTTPStore
from scripts import provision_turso

ORG = "seans-org"
DATABASE = "mosaic-hr"
HOSTNAME = "mosaic-hr-seans-org.turso.io"
TOKEN = "platform-token-not-a-real-one"
JWT = "database-jwt-not-a-real-one"


class RecordingApi:
    """The subset of the Platform API the script uses, plus a log of every request it received."""

    def __init__(self, *, database_exists: bool = False) -> None:
        self.database_exists = database_exists
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"error": "unauthorized"})
        if path == "/v1/organizations":
            return httpx.Response(200, json=[{"name": "Sean", "slug": ORG}])
        if path == f"/v1/organizations/{ORG}/databases" and request.method == "POST":
            if self.database_exists:
                return httpx.Response(409, json={"error": f"database with name {DATABASE} already exists"})
            self.database_exists = True
            return httpx.Response(200, json={"database": {"DbId": "db-1", "Hostname": HOSTNAME, "Name": DATABASE}})
        if path == f"/v1/organizations/{ORG}/databases/{DATABASE}" and request.method == "GET":
            if not self.database_exists:
                return httpx.Response(404, json={"error": "database not found"})
            return httpx.Response(200, json={"database": {"DbId": "db-1", "Hostname": HOSTNAME, "Name": DATABASE}})
        if path == f"/v1/organizations/{ORG}/databases/{DATABASE}/auth/tokens" and request.method == "POST":
            return httpx.Response(200, json={"jwt": JWT})
        return httpx.Response(404, json={"error": f"unrouted {request.method} {path}"})


def _client(api: RecordingApi) -> provision_turso.TursoClient:
    return provision_turso.TursoClient(TOKEN, transport=api.transport())


# --- provisioning -------------------------------------------------------------------------


def test_provision_creates_the_database_and_mints_a_scoped_token():
    api = RecordingApi()
    result = provision_turso.provision(_client(api), organization=None, name=DATABASE)

    assert result.created is True
    assert result.organization == ORG
    assert result.hostname == HOSTNAME
    assert result.database_url == f"libsql://{HOSTNAME}"
    assert result.auth_token == JWT

    paths = [(request.method, request.url.path) for request in api.requests]
    assert ("POST", f"/v1/organizations/{ORG}/databases") in paths
    assert ("POST", f"/v1/organizations/{ORG}/databases/{DATABASE}/auth/tokens") in paths


def test_provision_discovers_the_organization_when_none_is_given():
    api = RecordingApi()
    provision_turso.provision(_client(api), organization=None, name=DATABASE)
    assert api.requests[0].url.path == "/v1/organizations"


def test_provision_creates_the_database_in_the_named_group():
    api = RecordingApi()
    provision_turso.provision(_client(api), organization=ORG, name=DATABASE, group="default")
    create = next(r for r in api.requests if r.method == "POST" and r.url.path.endswith("/databases"))
    assert json.loads(create.content) == {"name": DATABASE, "group": "default"}


def test_provision_is_idempotent_when_the_database_already_exists():
    """Re-running provisioning must mint a fresh token, never fail on the 409 and never delete."""
    api = RecordingApi(database_exists=True)
    result = provision_turso.provision(_client(api), organization=ORG, name=DATABASE)

    assert result.created is False
    assert result.auth_token == JWT
    assert not any(request.method == "DELETE" for request in api.requests)


def test_the_minted_token_is_non_expiring_and_full_access():
    """The instance must keep writing audit rows months after provisioning, and it writes (§10.1)."""
    api = RecordingApi()
    provision_turso.provision(_client(api), organization=ORG, name=DATABASE)
    mint = next(r for r in api.requests if r.url.path.endswith("/auth/tokens"))
    assert dict(mint.url.params) == {"expiration": "never", "authorization": "full-access"}


def test_a_platform_api_error_is_reported_not_swallowed():
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "turso is having a day"})

    client = provision_turso.TursoClient(TOKEN, transport=httpx.MockTransport(refuse))
    with pytest.raises(provision_turso.TursoApiError) as raised:
        provision_turso.provision(client, organization=ORG, name=DATABASE)
    assert "500" in str(raised.value)


# --- the parity smoke (P1 carry-forward) --------------------------------------------------


def _rows(columns: list[str], rows: list[list]) -> dict:
    return {
        "cols": [{"name": name} for name in columns],
        "rows": [[{"type": "integer", "value": str(cell)} for cell in row] for row in rows],
        "affected_row_count": 0,
    }


def test_parity_smoke_is_clean_when_the_round_trip_and_foreign_keys_both_work():
    """The happy path: `SELECT 1` returns 1 and an orphan child row is rejected."""

    def handle(request: httpx.Request) -> httpx.Response:
        statement = json.loads(request.content)["requests"][0]
        sql = statement.get("stmt", {}).get("sql", "")
        if sql.lstrip().upper().startswith("INSERT"):
            return httpx.Response(200, json={"results": [{"type": "error", "error": {"message": "FOREIGN KEY"}}]})
        if "foreign_keys" in sql:
            payload = _rows(["foreign_keys"], [[1]])
        else:
            payload = _rows(["1"], [[1]])
        return httpx.Response(
            200, json={"results": [{"type": "ok", "response": {"type": "execute", "result": payload}}]}
        )

    store = TursoHTTPStore("libsql://x.turso.io", "t", transport=httpx.MockTransport(handle))
    report = provision_turso.parity_smoke(store)
    assert report.problems == []
    assert report.warnings == []
    assert report.foreign_keys_enforced is True


def test_parity_smoke_warns_but_does_not_fail_when_foreign_keys_are_not_enforced():
    """P1's carry-forward, answered honestly: the app writes parent-first, so this is a warning."""

    def handle(request: httpx.Request) -> httpx.Response:
        statement = json.loads(request.content)["requests"][0]
        sql = statement.get("stmt", {}).get("sql", "")
        if sql.lstrip().upper().startswith(("INSERT", "DELETE")):
            payload = _rows([], [])
        elif "foreign_keys" in sql:
            payload = _rows(["foreign_keys"], [[0]])
        else:
            payload = _rows(["1"], [[1]])
        return httpx.Response(
            200, json={"results": [{"type": "ok", "response": {"type": "execute", "result": payload}}]}
        )

    store = TursoHTTPStore("libsql://x.turso.io", "t", transport=httpx.MockTransport(handle))
    report = provision_turso.parity_smoke(store)
    assert report.problems == []
    assert report.foreign_keys_enforced is False
    assert any("foreign key" in warning.lower() for warning in report.warnings)


def test_parity_smoke_fails_when_the_database_cannot_be_reached():
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    store = TursoHTTPStore("libsql://x.turso.io", "t", transport=httpx.MockTransport(refuse))
    report = provision_turso.parity_smoke(store)
    assert report.problems
    assert report.foreign_keys_enforced is None


def test_parity_smoke_fails_when_the_round_trip_returns_the_wrong_value():
    def handle(request: httpx.Request) -> httpx.Response:
        payload = _rows(["1"], [[7]])
        return httpx.Response(
            200, json={"results": [{"type": "ok", "response": {"type": "execute", "result": payload}}]}
        )

    store = TursoHTTPStore("libsql://x.turso.io", "t", transport=httpx.MockTransport(handle))
    report = provision_turso.parity_smoke(store)
    assert any("SELECT 1" in problem for problem in report.problems)


def test_store_error_is_the_only_exception_the_smoke_lets_through_from_the_store():
    """Guards the assumption the smoke rests on: `TursoHTTPStore` wraps transport faults."""
    store = TursoHTTPStore("libsql://x.turso.io", "t", transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(StoreError):
        store.execute("SELECT 1", ())
