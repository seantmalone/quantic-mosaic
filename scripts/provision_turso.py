"""Create the Turso database and its scoped token, unattended (spec §14.6, §19.1 item 3).

    TURSO_PLATFORM_TOKEN=… python scripts/provision_turso.py

Render's free tier has no persistent disk and wipes the filesystem on every 15-minute spin-down, so
without Turso every chat session the grader creates is lost (§19.1 item 3, R-4). This script turns
one pasted **platform** token into the two values the deployed instance needs:

1. discover the workspace (`GET /v1/organizations`) unless `--organization` names it;
2. create the database, tolerating the documented `409` so a re-run is idempotent;
3. mint a **non-expiring, full-access** database token — the instance writes audit rows for the
   life of the deployment, so a `2w` token would silently break the audit log after the demo;
4. run the **parity smoke** below against the live database;
5. hand the two values on to `scripts/provision_render.py` through a mode-0600 handoff file under
   the git-ignored `data/runtime/`. That indirection exists because the documented order is
   `provision_turso.py && provision_render.py` — the Render service does not exist yet when this
   script finishes, so there is nothing to set the variables *on*, and writing them into `.env`
   is forbidden.

**The parity smoke is P1's carry-forward.** `TursoHTTPStore` has been exercised only against an
httpx `MockTransport`; nothing in this project has ever spoken to a live Turso database, and in
particular nothing has ever established whether foreign keys are enforced on the Hrana path —
`SqliteStore.__init__` issues `PRAGMA foreign_keys=ON` per connection and the HTTP store has no
connection to issue it on. `parity_smoke()` asks both questions on the first live run: a round trip
that must return 1, and a real orphan-child INSERT that *should* be rejected. An unenforced foreign
key is reported as a **warning, not a failure** — every write in this project goes through
`core/trace.py`, which inserts parents before children by construction (§10.1, §10.3), so the
constraint is a backstop rather than the mechanism.

**No GitHub secret is created here.** §14.6 says "a Render env var and a GitHub secret", but §15.2
enumerates the repository secrets as exactly three — `RENDER_DEPLOY_HOOK_URL`, `DEPLOY_URL`,
`RENDER_API_KEY` — and CI never reaches Turso: the push path is offline and `LLM_PROVIDER=stub`.
Putting a database credential in a secret nothing reads would be leak surface for no gain, so the
two values reach the Render service and nowhere else.

Nothing here prints a token. The platform token is read from `TURSO_PLATFORM_TOKEN` and is never
echoed; the minted database token goes to the mode-0600 handoff file, and the console gets its
length and a SHA-256 fingerprint.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    # `python scripts/provision_turso.py` puts *this file's own directory* on sys.path, not the
    # repository root. `provision_render.py` and `check_render_hours.py` carry these three lines
    # because a sibling `from scripts.… import …` raised `ModuleNotFoundError` without them, and
    # this file is the other half of that pair — `provision_render.py` imports `fingerprint` and
    # `read_handoff` out of it. Every deploy script therefore resolves its imports the same way
    # from a bare shell, rather than one of them being a step behind the moment it grows one.
    sys.path.insert(0, str(REPO_ROOT))

from hrmosaic.core.db import StoreError, TursoHTTPStore  # noqa: E402

TURSO_API_BASE = "https://api.turso.tech"

#: Lowercase letters, numbers and dashes only, per the Platform API's documented name rule.
DEFAULT_DATABASE_NAME = "mosaic-hr"

#: Every Turso workspace is created with a `default` group; the free tier allows exactly one.
DEFAULT_GROUP = "default"

#: The handoff `provision_render.py` reads when the Render service did not exist yet. Under the
#: git-ignored `data/runtime/`, written 0600, and deleted by hand once provisioning is done.
HANDOFF_PATH = Path("data/runtime/provision_turso.json")

#: The two tables the foreign-key probe creates and drops. Prefixed so they can never collide with
#: a real migration's table, and dropped again whatever the outcome.
FK_PARENT = "_mosaic_fk_probe_parent"
FK_CHILD = "_mosaic_fk_probe_child"


class TursoApiError(RuntimeError):
    """The Platform API answered something other than 2xx (and it was not the tolerated 409)."""


@dataclass(frozen=True)
class Provisioned:
    organization: str
    database: str
    hostname: str
    database_url: str
    auth_token: str
    created: bool


@dataclass
class SmokeReport:
    """What the first live round trip against Turso actually observed."""

    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    foreign_keys_enforced: bool | None = None
    pragma_foreign_keys: int | None = None


# --------------------------------------------------------------------------------------
# The Platform API client
# --------------------------------------------------------------------------------------


class TursoClient:
    """The four Platform API calls this script makes, and nothing else."""

    def __init__(
        self,
        platform_token: str,
        *,
        base_url: str = TURSO_API_BASE,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=timeout,
            headers={"Authorization": f"Bearer {platform_token}", "Content-Type": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, *, tolerate: tuple[int, ...] = (), **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:  # pragma: no cover - network faults are not reachable in tests
            raise TursoApiError(f"{method} {path} failed: {exc}") from exc
        if response.status_code >= 400 and response.status_code not in tolerate:
            raise TursoApiError(f"{method} {path} answered {response.status_code}: {response.text[:200]}")
        return response

    def organizations(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/v1/organizations").json())

    def get_database(self, organization: str, name: str) -> dict[str, Any] | None:
        response = self._request("GET", f"/v1/organizations/{organization}/databases/{name}", tolerate=(404,))
        if response.status_code == 404:
            return None
        return response.json()["database"]

    def create_database(self, organization: str, name: str, group: str) -> dict[str, Any] | None:
        """Returns the created database, or `None` on the documented 409 (it already exists)."""
        response = self._request(
            "POST",
            f"/v1/organizations/{organization}/databases",
            json={"name": name, "group": group},
            tolerate=(409,),
        )
        if response.status_code == 409:
            return None
        return response.json()["database"]

    def create_token(self, organization: str, name: str) -> str:
        response = self._request(
            "POST",
            f"/v1/organizations/{organization}/databases/{name}/auth/tokens",
            params={"expiration": "never", "authorization": "full-access"},
        )
        return str(response.json()["jwt"])


# --------------------------------------------------------------------------------------
# Provisioning
# --------------------------------------------------------------------------------------


def provision(
    client: TursoClient,
    *,
    organization: str | None,
    name: str = DEFAULT_DATABASE_NAME,
    group: str = DEFAULT_GROUP,
) -> Provisioned:
    """Create (or adopt) the database and mint a token for it. Safe to run twice."""
    if organization is None:
        candidates = client.organizations()
        if not candidates:
            raise TursoApiError("this platform token can see no organizations")
        organization = str(candidates[0].get("slug") or candidates[0]["name"])

    database = client.create_database(organization, name, group)
    created = database is not None
    if database is None:
        database = client.get_database(organization, name)
        if database is None:  # pragma: no cover - a 409 followed by a 404 is not a reachable state
            raise TursoApiError(f"database {name!r} reported as existing but could not be read back")

    hostname = str(database["Hostname"])
    return Provisioned(
        organization=organization,
        database=str(database.get("Name") or name),
        hostname=hostname,
        database_url=f"libsql://{hostname}",
        auth_token=client.create_token(organization, name),
        created=created,
    )


# --------------------------------------------------------------------------------------
# The parity smoke (P1 carry-forward)
# --------------------------------------------------------------------------------------


def parity_smoke(store: TursoHTTPStore) -> SmokeReport:
    """Ask the live database the two questions no MockTransport can answer."""
    report = SmokeReport()

    try:
        rows = store.execute("SELECT 1", ())
    except StoreError as exc:
        report.problems.append(f"the database could not be reached: {exc}")
        return report
    observed = rows.rows[0][0] if rows.rows else None
    if observed != 1:
        report.problems.append(f"SELECT 1 returned {observed!r}, not 1")
        return report

    with contextlib.suppress(StoreError):
        pragma = store.execute("PRAGMA foreign_keys", ())
        if pragma.rows:
            report.pragma_foreign_keys = int(pragma.rows[0][0])

    report.foreign_keys_enforced = _foreign_keys_rejected_an_orphan(store, report)
    if report.foreign_keys_enforced is False:
        report.warnings.append(
            "foreign keys are NOT enforced on this Turso connection: an orphan child row was "
            "accepted. Every write in this project goes through core/trace.py, which inserts "
            "parents before children (§10.3), so this is a missing backstop rather than a broken "
            "audit trail — but it is the first live answer to P1's open question and belongs in "
            "deployed.md."
        )
    return report


def _foreign_keys_rejected_an_orphan(store: TursoHTTPStore, report: SmokeReport) -> bool | None:
    """Create a parent/child pair, insert an orphan, and report whether it was refused."""
    try:
        store.execute(f"CREATE TABLE IF NOT EXISTS {FK_PARENT} (id INTEGER PRIMARY KEY)", ())
        store.execute(
            f"CREATE TABLE IF NOT EXISTS {FK_CHILD} "
            f"(id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES {FK_PARENT}(id))",
            (),
        )
    except StoreError as exc:
        report.problems.append(f"the foreign-key probe could not create its tables: {exc}")
        return None

    enforced: bool | None
    try:
        store.execute(f"INSERT INTO {FK_CHILD} (id, parent_id) VALUES (1, 999999)", ())
    except StoreError:
        enforced = True
    else:
        enforced = False
    finally:
        for statement in (
            f"DELETE FROM {FK_CHILD}",
            f"DROP TABLE IF EXISTS {FK_CHILD}",
            f"DROP TABLE IF EXISTS {FK_PARENT}",
        ):
            with contextlib.suppress(StoreError):
                store.execute(statement, ())
    return enforced


# --------------------------------------------------------------------------------------
# Handoff to provision_render.py
# --------------------------------------------------------------------------------------


def fingerprint(secret: str) -> str:
    """A stable, non-reversible label so two runs can be compared in a log without a leak."""
    return f"sha256:{hashlib.sha256(secret.encode('utf-8')).hexdigest()[:12]} ({len(secret)} chars)"


def write_handoff(result: Provisioned, path: Path = HANDOFF_PATH) -> Path:
    """Write the two values `provision_render.py` needs, readable only by this user."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"TURSO_DATABASE_URL": result.database_url, "TURSO_AUTH_TOKEN": result.auth_token}, indent=2),
        encoding="utf-8",
    )
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path


def read_handoff(path: Path = HANDOFF_PATH) -> dict[str, str]:
    """The other half of `write_handoff`; an absent file is simply no handoff."""
    if not path.exists():
        return {}
    return {str(key): str(value) for key, value in json.loads(path.read_text(encoding="utf-8")).items()}


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--organization", default=None, help="Turso workspace slug (default: the first visible)")
    parser.add_argument("--name", default=DEFAULT_DATABASE_NAME, help="database name")
    parser.add_argument("--group", default=DEFAULT_GROUP, help="database group")
    parser.add_argument("--skip-smoke", action="store_true", help="do not open the new database")
    arguments = parser.parse_args(argv)

    platform_token = os.environ.get("TURSO_PLATFORM_TOKEN")
    if not platform_token:
        print(
            "TURSO_PLATFORM_TOKEN is unset. Create a Platform API token at https://turso.tech "
            "(GitHub SSO → Account → API Tokens) and export it. This is user gate 3 of "
            "NEEDS-FROM-USER.md and nothing here can proceed without it.",
            file=sys.stderr,
        )
        return 1

    client = TursoClient(platform_token)
    try:
        result = provision(client, organization=arguments.organization, name=arguments.name, group=arguments.group)
    except TursoApiError as exc:
        print(f"FAIL — {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    print(
        f"  organization={result.organization}  database={result.database}  "
        f"{'created' if result.created else 'already existed'}\n"
        f"  TURSO_DATABASE_URL={result.database_url}\n"
        f"  TURSO_AUTH_TOKEN={fingerprint(result.auth_token)}"
    )

    if not arguments.skip_smoke:
        store = TursoHTTPStore(result.database_url, result.auth_token)
        try:
            report = parity_smoke(store)
        finally:
            store.close()
        # `round trip ok` is a result, not a heading. It used to print before `report.problems`
        # was looked at, so a run whose `SELECT 1` never came back announced a successful round
        # trip one line above `FAIL — the database was created but is not usable`. The failure
        # path is taken first now, and it carries the warnings with it so no diagnostic is lost.
        if report.problems:
            for warning in report.warnings:
                print(f"  WARNING — {warning}", file=sys.stderr)
            for problem in report.problems:
                print(f"  - {problem}", file=sys.stderr)
            print("\nFAIL — the database was created but is not usable.", file=sys.stderr)
            return 1
        print(
            f"  parity smoke: round trip ok · PRAGMA foreign_keys={report.pragma_foreign_keys} · "
            f"orphan INSERT rejected={report.foreign_keys_enforced}"
        )
        for warning in report.warnings:
            print(f"  WARNING — {warning}")

    handoff = write_handoff(result)
    print(
        f"\nOK — Turso is provisioned. The two values were written to {handoff} (mode 0600, "
        "git-ignored); `python scripts/provision_render.py` reads them from there and sets them on "
        "the service. Delete the file once the deploy is green."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
