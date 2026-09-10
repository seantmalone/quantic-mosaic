"""Create the Render service and every secret it needs, unattended (spec §14.6, §15.2, §19.1).

    RENDER_API_KEY=… python scripts/provision_render.py

The only deployed thing this project has. What the script does, in order:

1. read the committed **`render.yaml`** — it is the source of truth for the service name, plan,
   runtime, Dockerfile path, health-check path, `autoDeploy: false` and the split between plain
   values and `sync: false` secrets, so the Blueprint and the API-created service cannot drift;
2. resolve the workspace (`GET /v1/owners`) and adopt an existing service by name, or create one.
   Adopting matters: a second free web service would share the same 750 instance-hours and chain
   its own spin-up onto the first (§14.1);
3. **generate `APP_ACCESS_TOKEN` with `secrets.token_urlsafe(32)`** — §19's "no user step" — and
   keep the one already on the service on a re-run, because regenerating it would silently break
   the tokenized link a grader is expected to click;
4. `PUT` every environment variable: the plain values from `render.yaml` plus the five `sync: false`
   credentials, read through `hrmosaic.settings` (so they are `SecretStr` and come from the
   git-ignored `.env`) with `scripts/provision_turso.py`'s handoff file filling in `TURSO_*`;
5. `gh secret set` for exactly the three repository secrets of §15.2 — `RENDER_DEPLOY_HOOK_URL`,
   `DEPLOY_URL`, `RENDER_API_KEY`. No LLM key and no access token is ever a CI secret: the push
   path never calls a provider and the `docker` job passes its own throwaway token inline;
6. print the tokenized `https://<app>.onrender.com/?access=<token>` link for `README.md`'s
   `Deployed:` line and `deployed.md`'s `## Access`.

**The one value the REST API does not expose is the deploy hook URL.** Render publishes it in the
dashboard (Service → Settings → Deploy Hook), not through `/v1/services`, so the script takes it
from `RENDER_DEPLOY_HOOK_URL` when set and otherwise reports copying it as the single remaining
manual step instead of pretending to have it.

Credentials are read but never printed: the console gets a length and a SHA-256 fingerprint. The
access token *is* printed, deliberately — it is the shared link secret of §11, published in
`README.md` by design, and rotated after grading.
"""

from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from hrmosaic.settings import secret_value
from hrmosaic.settings import settings as app_settings
from scripts.provision_turso import fingerprint, read_handoff

RENDER_API_BASE = "https://api.render.com"

BLUEPRINT_PATH = Path("render.yaml")

#: `secrets.token_urlsafe(32)` — 32 bytes of entropy, ~43 URL-safe characters (§12.3, §19).
ACCESS_TOKEN_BYTES = 32

#: Exactly the three repository secrets of §15.2, in the order they are set.
GITHUB_SECRETS = ("RENDER_DEPLOY_HOOK_URL", "DEPLOY_URL", "RENDER_API_KEY")

#: Where each `sync: false` credential comes from locally. `APP_ACCESS_TOKEN` is absent: it is
#: generated here, not supplied.
SECRET_SOURCES = {
    "ANTHROPIC_API_KEY": lambda: secret_value(app_settings.anthropic_api_key),
    "JUDGE_API_KEY": lambda: secret_value(app_settings.judge_api_key),
    "LLM_FALLBACK_API_KEY": lambda: secret_value(app_settings.llm_fallback_api_key),
    "TURSO_DATABASE_URL": lambda: app_settings.turso_database_url,
    "TURSO_AUTH_TOKEN": lambda: secret_value(app_settings.turso_auth_token),
}


class RenderApiError(RuntimeError):
    """The Render REST API answered something other than 2xx."""


class MissingSecrets(RuntimeError):
    """A `sync: false` variable had no local value; nothing is written when this is raised."""


@dataclass(frozen=True)
class Blueprint:
    """The committed `render.yaml`, parsed."""

    name: str
    runtime: str
    plan: str
    dockerfile_path: str
    health_check_path: str
    auto_deploy: bool
    plain_env: dict[str, str]
    secret_keys: tuple[str, ...]


@dataclass
class Provisioned:
    service_id: str
    url: str
    created: bool
    access_token: str
    access_token_generated: bool
    github_secrets_set: list[str] = field(default_factory=list)
    manual_steps: list[str] = field(default_factory=list)

    @property
    def tokenized_url(self) -> str:
        """The link that goes into `README.md`'s `Deployed:` line and `deployed.md`'s `## Access`."""
        return f"{self.url.rstrip('/')}/?access={self.access_token}"


# --------------------------------------------------------------------------------------
# render.yaml
# --------------------------------------------------------------------------------------


def load_blueprint(path: Path = BLUEPRINT_PATH) -> Blueprint:
    """Parse the committed Blueprint. The `sync: false` entries are keys with no value here."""
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    service = document["services"][0]
    plain: dict[str, str] = {}
    secret_keys: list[str] = []
    for entry in service.get("envVars") or []:
        if entry.get("sync") is False:
            secret_keys.append(entry["key"])
        else:
            plain[entry["key"]] = str(entry["value"])
    return Blueprint(
        name=service["name"],
        runtime=service["runtime"],
        plan=service["plan"],
        dockerfile_path=service["dockerfilePath"],
        health_check_path=service["healthCheckPath"],
        auto_deploy=bool(service.get("autoDeploy", True)),
        plain_env=plain,
        secret_keys=tuple(secret_keys),
    )


# --------------------------------------------------------------------------------------
# The REST client
# --------------------------------------------------------------------------------------


class RenderClient:
    """The five Render endpoints this script uses, and nothing else."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = RENDER_API_BASE,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )

    def close(self) -> None:
        self._client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:  # pragma: no cover - network faults are not reachable in tests
            raise RenderApiError(f"{method} {path} failed: {exc}") from exc
        if response.status_code >= 400:
            raise RenderApiError(f"{method} {path} answered {response.status_code}: {response.text[:200]}")
        return response

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """One authenticated GET, decoded. The read half of the API, for callers outside this file."""
        return self._request("GET", path, params=params or {}).json()

    def owner_id(self) -> str:
        owners = self._request("GET", "/v1/owners").json()
        if not owners:
            raise RenderApiError("this API key can see no workspaces")
        first = owners[0]
        return str((first.get("owner") or first)["id"])

    def find_service(self, name: str) -> dict[str, Any] | None:
        rows = self._request("GET", "/v1/services", params={"name": name, "type": "web_service"}).json()
        for row in rows:
            service = row.get("service") or row
            if service.get("name") == name:
                return service
        return None

    def create_service(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = self._request("POST", "/v1/services", json=payload).json()
        return body["service"]

    def env_vars(self, service_id: str) -> dict[str, str]:
        rows = self._request("GET", f"/v1/services/{service_id}/env-vars").json()
        result: dict[str, str] = {}
        for row in rows:
            entry = row.get("envVar") or row
            result[str(entry["key"])] = str(entry.get("value") or "")
        return result

    def replace_env_vars(self, service_id: str, values: dict[str, str]) -> None:
        payload = [{"key": key, "value": value} for key, value in values.items()]
        self._request("PUT", f"/v1/services/{service_id}/env-vars", json=payload)


# --------------------------------------------------------------------------------------
# gh secret set
# --------------------------------------------------------------------------------------


def gh_secret_set(name: str, value: str) -> bool:
    """`gh secret set <name>` with the value on stdin, so it never reaches the process table."""
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, value passed on stdin
            ["gh", "secret", "set", name],  # noqa: S607 - `gh` is resolved from PATH by design
            input=value,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError:
        return False
    return completed.returncode == 0


# --------------------------------------------------------------------------------------
# Provisioning
# --------------------------------------------------------------------------------------


def collect_secret_values() -> dict[str, str]:
    """The five `sync: false` credentials, from `.env` via `settings` and the Turso handoff."""
    handoff = read_handoff()
    values: dict[str, str] = {}
    for key, source in SECRET_SOURCES.items():
        value = source() or handoff.get(key)
        if value:
            values[key] = str(value)
    return values


def provision(
    client: RenderClient,
    blueprint: Blueprint,
    *,
    repo: str,
    branch: str,
    region: str,
    secret_values: dict[str, str],
    deploy_hook_url: str | None,
    gh=gh_secret_set,
    api_key: str = "",
) -> Provisioned:
    """Create or adopt the service, populate it, and set the three repository secrets."""
    required = [key for key in blueprint.secret_keys if key != "APP_ACCESS_TOKEN"]
    missing = [key for key in required if not secret_values.get(key)]
    if missing:
        raise MissingSecrets(
            f"no local value for {', '.join(missing)} — the service would deploy without them. "
            "The three model keys live in the git-ignored .env; TURSO_DATABASE_URL and "
            "TURSO_AUTH_TOKEN come from `python scripts/provision_turso.py`."
        )

    service = client.find_service(blueprint.name)
    created = service is None
    if service is None:
        service = client.create_service(
            {
                "type": "web_service",
                "name": blueprint.name,
                "ownerId": client.owner_id(),
                "repo": repo,
                "branch": branch,
                "autoDeploy": "yes" if blueprint.auto_deploy else "no",
                "serviceDetails": {
                    "runtime": blueprint.runtime,
                    "plan": blueprint.plan,
                    "region": region,
                    "numInstances": 1,
                    "healthCheckPath": blueprint.health_check_path,
                    "envSpecificDetails": {"dockerfilePath": blueprint.dockerfile_path, "dockerContext": "."},
                },
            }
        )
    service_id = str(service["id"])
    url = str((service.get("serviceDetails") or {}).get("url") or f"https://{blueprint.name}.onrender.com")

    existing = {} if created else client.env_vars(service_id)
    access_token = existing.get("APP_ACCESS_TOKEN") or ""
    access_token_generated = not access_token
    if access_token_generated:
        access_token = secrets.token_urlsafe(ACCESS_TOKEN_BYTES)

    client.replace_env_vars(
        service_id,
        {**blueprint.plain_env, **{key: secret_values[key] for key in required}, "APP_ACCESS_TOKEN": access_token},
    )

    result = Provisioned(
        service_id=service_id,
        url=url,
        created=created,
        access_token=access_token,
        access_token_generated=access_token_generated,
    )

    wanted = {"RENDER_DEPLOY_HOOK_URL": deploy_hook_url, "DEPLOY_URL": url, "RENDER_API_KEY": api_key}
    for name in GITHUB_SECRETS:
        value = wanted[name]
        if not value:
            result.manual_steps.append(
                f"set the {name} repository secret by hand: `gh secret set {name}`"
                + (
                    " — copy it from the Render dashboard (Service → Settings → Deploy Hook); "
                    "the REST API does not expose it (§14.6)"
                    if name == "RENDER_DEPLOY_HOOK_URL"
                    else ""
                )
            )
            continue
        if gh(name, value):
            result.github_secrets_set.append(name)
        else:
            result.manual_steps.append(f"`gh secret set {name}` failed; set it by hand in the repository settings")
    return result


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default="https://github.com/seantmalone/quantic-mosaic", help="repository to deploy")
    parser.add_argument("--branch", default="main", help="branch Render builds")
    parser.add_argument("--region", default="oregon", help="Render region")
    arguments = parser.parse_args(argv)

    api_key = os.environ.get("RENDER_API_KEY")
    if not api_key:
        print(
            "RENDER_API_KEY is unset. Create one at the Render dashboard → Account Settings → API "
            "Keys and export it. This is user gate 4 of NEEDS-FROM-USER.md, and gate 2 (the Render "
            "GitHub App, which no API can install) must be satisfied first or the service cannot "
            "read the repository.",
            file=sys.stderr,
        )
        return 1

    blueprint = load_blueprint()
    client = RenderClient(api_key)
    try:
        result = provision(
            client,
            blueprint,
            repo=arguments.repo,
            branch=arguments.branch,
            region=arguments.region,
            secret_values=collect_secret_values(),
            deploy_hook_url=os.environ.get("RENDER_DEPLOY_HOOK_URL"),
            api_key=api_key,
        )
    except (RenderApiError, MissingSecrets) as exc:
        print(f"FAIL — {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    print(
        f"  service={blueprint.name} ({result.service_id})  {'created' if result.created else 'already existed'}\n"
        f"  url={result.url}  auto_deploy={'on' if blueprint.auto_deploy else 'OFF (R8.4)'}\n"
        f"  APP_ACCESS_TOKEN {'generated' if result.access_token_generated else 'kept'}: "
        f"{fingerprint(result.access_token)}\n"
        f"  github secrets set: {', '.join(result.github_secrets_set) or '(none)'}"
    )
    print(f"\n  Deployed: {result.tokenized_url}")
    print("  ^ paste that into README.md's `Deployed:` line and deployed.md's `## Access`.")
    for step in result.manual_steps:
        print(f"  TODO — {step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
