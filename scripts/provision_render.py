"""Create the Render service and every secret it needs, unattended (spec §14.6, §15.2, §19.1).

    RENDER_API_KEY=… python scripts/provision_render.py

The only deployed thing this project has. What the script does, in order:

1. read the committed **`render.yaml`** — it is the source of truth for the service name, plan,
   runtime, Dockerfile path, health-check path, `autoDeploy: false` and the split between plain
   values and `sync: false` secrets, so the Blueprint and the API-created service cannot drift;
2. resolve the workspace (`GET /v1/owners`) and adopt an existing service by name, or create one.
   Adopting matters: a second free web service would share the same 750 instance-hours and chain
   its own spin-up onto the first (§14.1). An adopted service is then **read back and reconciled**:
   if its `autoDeploy` disagrees with `render.yaml` it is `PATCH`ed into line, and the summary
   prints the value the *service* reported — a service adopted with Auto-Deploy still on would
   otherwise defeat half of R8.4 while the console asserted it was off;
3. **generate `APP_ACCESS_TOKEN` with `secrets.token_urlsafe(32)`** — §19's "no user step" — and
   keep the one already on the service on a re-run, because regenerating it would silently break
   the tokenized link a grader is expected to click;
4. `PUT` every environment variable: the plain values from `render.yaml` plus the five `sync: false`
   credentials, read through `hrmosaic.settings` (so they are `SecretStr` and come from the
   git-ignored `.env`) with `scripts/provision_turso.py`'s handoff file filling in `TURSO_*`;
5. **trigger a deploy** (`POST /v1/services/{id}/deploys`), because the deploy Render starts by
   itself the moment a service is created was built *before* step 4 wrote any of the variables.
   Observed live on 2026-09-10: that first deploy came up green but `deploy_mode=local`,
   `llm.agent.configured=false`, `trace_store.backend=sqlite` and with the access gate off. Suppress
   with `--no-deploy`;
6. `gh secret set` for the repository secrets of §15.2 — `RENDER_DEPLOY_HOOK_URL`, `DEPLOY_URL`,
   `RENDER_API_KEY`, `RENDER_SERVICE_ID`. No LLM key and no access token is ever a CI secret: the
   push path never calls a provider and the `docker` job passes its own throwaway token inline;
7. print the tokenized `https://<app>.onrender.com/?access=<token>` link for `README.md`'s
   `Deployed:` line and `deployed.md`'s `## Access`.

**The one value the REST API does not expose is the deploy hook URL** — re-confirmed against
Render's current API reference on 2026-09-10 (`api-docs.render.com`: no endpoint returns a
`deployHookUrl`, and Render's own community thread "How to Retrieve deployHookUrl Programmatically
via API or Terraform Provider?" is still open). Render publishes it in the dashboard only
(Service → Settings → Deploy Hook), so the script takes it from `RENDER_DEPLOY_HOOK_URL` when set
and otherwise reports copying it as the single remaining manual step instead of pretending to have
it. Recorded as a ratified amendment to §14.6; `POST /v1/services/{id}/deploys` with
`RENDER_API_KEY` exists as an alternative CI trigger, but swapping CI onto it would be a change to
§15.2's three-secret contract, not a fix, so it is not done here.

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

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    # `python scripts/<name>.py` puts this file's own directory on sys.path, not the repository
    # root, so the sibling `scripts.provision_turso` import below would not resolve.
    sys.path.insert(0, str(REPO_ROOT))

from hrmosaic.settings import secret_value  # noqa: E402
from hrmosaic.settings import settings as app_settings  # noqa: E402
from scripts.provision_turso import fingerprint, read_handoff  # noqa: E402

RENDER_API_BASE = "https://api.render.com"

BLUEPRINT_PATH = Path("render.yaml")

#: `secrets.token_urlsafe(32)` — 32 bytes of entropy, ~43 URL-safe characters (§12.3, §19).
ACCESS_TOKEN_BYTES = 32

#: The repository secrets of §15.2, in the order they are set.
#:
#: `RENDER_SERVICE_ID` is the post-gate amendment (2026-09-10, P11b): the deploy hook URL is
#: published in the dashboard and by no REST endpoint, so CI triggers production with
#: `POST /v1/services/$RENDER_SERVICE_ID/deploys` and `RENDER_API_KEY` — two values this script
#: already has — and the hook stays an equivalent alternative that wins when it is set. Every one
#: of these addresses Render's control plane; none is a credential the *application* answers with.
GITHUB_SECRETS = ("RENDER_DEPLOY_HOOK_URL", "DEPLOY_URL", "RENDER_API_KEY", "RENDER_SERVICE_ID")

#: The only plan this project is ever allowed to create or run on (§14.1).
FREE_PLAN = "free"

#: The only instance count the free plan has; more than one is billable and defeats §14.1's
#: single-service, 750-instance-hour budget.
FREE_NUM_INSTANCES = 1

#: Fields `PATCH /v1/services/{id}` must never carry from this script. `autoDeploy` is the one
#: legitimate write (`reconcile_auto_deploy`); everything here either changes what is billed or
#: adds a resource that is.
BILLABLE_PATCH_FIELDS = frozenset({"plan", "numInstances", "disk", "autoscaling", "instanceType", "region"})

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


class BillablePlan(RuntimeError):
    """Something in this run would have created or moved a service off the free plan.

    The account carries a payment method — Render refuses to create *any* service, free ones
    included, until it does (`402 Payment information is required`, observed 2026-09-10) — so a
    plan mistake here is no longer a rejected request, it is a monthly bill. The instruction on
    record is "do not deploy anything that will cost me money", and this exception is how that is
    enforced rather than assumed: `render.yaml`'s plan is checked, the create payload is checked,
    the created service is read *back* from the API and checked, an adopted service is checked, and
    `PATCH /v1/services/{id}` refuses any field that could change the shape being billed.
    """


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
    #: What the **service** reports, read back from the API — never what `render.yaml` says.
    auto_deploy_observed: bool = False
    #: True when the adopted service disagreed with the blueprint and was PATCHed into line.
    auto_deploy_patched: bool = False
    #: The plan the **service** reports after creation, read back from the API. Always `"free"` —
    #: `assert_free_service` raises rather than let anything else through.
    plan_observed: str = FREE_PLAN
    #: The deploy this run asked for *after* writing the environment variables. `None` only when
    #: `--no-deploy` suppressed it.
    deploy_id: str | None = None
    github_secrets_set: list[str] = field(default_factory=list)
    manual_steps: list[str] = field(default_factory=list)

    @property
    def tokenized_url(self) -> str:
        """The link that goes into `README.md`'s `Deployed:` line and `deployed.md`'s `## Access`."""
        return f"{self.url.rstrip('/')}/?access={self.access_token}"


# --------------------------------------------------------------------------------------
# render.yaml
# --------------------------------------------------------------------------------------


def _flat_keys(payload: dict[str, Any]) -> set[str]:
    """Every key in `payload`, including the ones nested one level down under `serviceDetails`."""
    keys = set(payload)
    nested = payload.get("serviceDetails")
    if isinstance(nested, dict):
        keys |= set(nested)
    return keys


def assert_free_payload(payload: dict[str, Any]) -> None:
    """Refuse to send a create request for anything Render would bill for."""
    details = payload.get("serviceDetails") or {}
    plan = details.get("plan")
    if plan != FREE_PLAN:
        raise BillablePlan(
            f"refusing to create a service on plan {plan!r}; only {FREE_PLAN!r} is permitted. "
            "render.yaml is the source of truth for the plan, so fix it there."
        )
    instances = details.get("numInstances", FREE_NUM_INSTANCES)
    if int(instances) != FREE_NUM_INSTANCES:
        raise BillablePlan(f"refusing to create a service with numInstances={instances}; the free plan runs one.")
    for field_name in ("disk", "autoscaling"):
        if details.get(field_name):
            raise BillablePlan(f"refusing to create a service with a {field_name}: it is billable and §14.1 has none.")


def plan_of(service: dict[str, Any]) -> str | None:
    """The plan the *service* reports, read out of whichever envelope the API used."""
    details = service.get("serviceDetails") or {}
    plan = details.get("plan") or service.get("plan")
    return None if plan is None else str(plan).strip().lower()


def assert_free_service(service: dict[str, Any], *, context: str) -> str:
    """Read the plan back off a service and refuse to go on unless it is free.

    Called after the create (Render is asked for `free`; this asserts it *gave* `free`) and on the
    adopt path (a service made by hand, or by an earlier Blueprint deploy, could be on anything).
    Nothing is deleted and nothing is changed when this raises — the plan is never patched.
    """
    plan = plan_of(service)
    if plan != FREE_PLAN:
        raise BillablePlan(
            f"{context}: service {service.get('id')} reports plan {plan!r}, not {FREE_PLAN!r}. "
            "Nothing was deleted and nothing was changed — this script never moves a service "
            "between plans. Sort it out in the Render dashboard before re-running."
        )
    return plan


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
    """The Render endpoints this script uses, and nothing else."""

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
        assert_free_payload(payload)
        body = self._request("POST", "/v1/services", json=payload).json()
        return body["service"]

    def create_deploy(self, service_id: str) -> str:
        """`POST /v1/services/{id}/deploys` — the API-side deploy trigger (§14.5, amended).

        `clearCache: do_not_clear` keeps Render's layer cache, which is the difference between a
        two-minute rebuild and a full one that re-downloads the ONNX model. It creates no resource
        and changes no plan.
        """
        body = self._request("POST", f"/v1/services/{service_id}/deploys", json={"clearCache": "do_not_clear"}).json()
        return str((body.get("deploy") or body)["id"])

    def get_service(self, service_id: str) -> dict[str, Any]:
        body = self._request("GET", f"/v1/services/{service_id}").json()
        return body.get("service") or body

    def update_service(self, service_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """`PATCH /v1/services/{id}` — the only write this script makes to the service itself.

        `autoDeploy` is the only field it is ever legitimately asked to change. Anything in
        `BILLABLE_PATCH_FIELDS` is refused here rather than at the call site, so a future caller
        cannot move the service onto a paid shape by adding one key.
        """
        billable = sorted(BILLABLE_PATCH_FIELDS.intersection(_flat_keys(payload)))
        if billable:
            raise BillablePlan(
                f"refusing to PATCH service {service_id} with {', '.join(billable)}: this script "
                "never changes what the service is billed for."
            )
        body = self._request("PATCH", f"/v1/services/{service_id}", json=payload).json()
        return body.get("service") or body

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


def auto_deploy_of(service: dict[str, Any]) -> bool | None:
    """Render reports `autoDeploy` as the string `"yes"`/`"no"`; `None` means it did not say."""
    raw = service.get("autoDeploy")
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() == "yes"


def reconcile_auto_deploy(client: RenderClient, service: dict[str, Any], wanted: bool) -> tuple[bool, bool]:
    """Make the service's `autoDeploy` match `render.yaml`, and return `(observed, patched)`.

    Only `create_service` used to set `autoDeploy`, so an **adopted** service — the documented
    re-run path — kept whatever it had. A service created by hand, or by a Blueprint deploy from
    before `autoDeploy: false` landed, therefore stayed on while the console printed
    `auto_deploy=OFF (R8.4)`, because that line was read from the committed blueprint rather than
    from the service. Half of the R8.4 argument (Render's own auto-deploy is off, so the CI hook is
    the only path to production) was silently untrue in exactly the state most likely on a retry.

    Raises `RenderApiError` when the service still disagrees after the PATCH: a claim about R8.4
    that the platform contradicts is worse than no claim.
    """
    service_id = str(service["id"])
    observed = auto_deploy_of(service)
    patched = False
    if observed is not wanted:
        service = client.update_service(service_id, {"autoDeploy": "yes" if wanted else "no"})
        observed = auto_deploy_of(service)
        patched = True
    if observed is None:
        observed = auto_deploy_of(client.get_service(service_id))
    if observed is not wanted:
        raise RenderApiError(
            f"service {service_id} reports autoDeploy={observed!r} but render.yaml says "
            f"{wanted!r}, and the PATCH did not change it. Turn Auto-Deploy off in the Render "
            "dashboard (Service → Settings): with it on, a push to main reaches production "
            "without passing `needs: [test, docker]`, which is half of R8.4."
        )
    return observed, patched


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
    trigger_deploy: bool = True,
) -> Provisioned:
    """Create or adopt the service, populate it, deploy it, and set the repository secrets."""
    required = [key for key in blueprint.secret_keys if key != "APP_ACCESS_TOKEN"]
    missing = [key for key in required if not secret_values.get(key)]
    if missing:
        raise MissingSecrets(
            f"no local value for {', '.join(missing)} — the service would deploy without them. "
            "The three model keys live in the git-ignored .env; TURSO_DATABASE_URL and "
            "TURSO_AUTH_TOKEN come from `python scripts/provision_turso.py`."
        )

    if blueprint.plan != FREE_PLAN:
        raise BillablePlan(f"render.yaml declares plan {blueprint.plan!r}; only {FREE_PLAN!r} is permitted here.")

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
    # Read the service back from the API before anything else touches it, and assert the plan off
    # *that* — not off the payload we sent, and not off render.yaml. Asking for `free` and being
    # given something else is exactly the failure this has to catch.
    service = client.get_service(service_id)
    plan_observed = assert_free_service(
        service, context="after creating the service" if created else "adopting the existing service"
    )
    url = str((service.get("serviceDetails") or {}).get("url") or f"https://{blueprint.name}.onrender.com")
    auto_deploy_observed, auto_deploy_patched = reconcile_auto_deploy(client, service, blueprint.auto_deploy)

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
        auto_deploy_observed=auto_deploy_observed,
        auto_deploy_patched=auto_deploy_patched,
        plan_observed=plan_observed,
    )

    # The environment variables are only on the *service* at this point, and the deploy Render
    # starts by itself the instant a service is created was built without them. Observed live on
    # 2026-09-10: that first deploy came up `deploy_mode=local`, `llm.agent.configured=false`,
    # `trace_store.backend=sqlite` and with the access gate off — a green build serving a
    # misconfigured instance, which is the worst of the two failure shapes. So the last thing this
    # function does is ask for a deploy that carries the variables it just wrote.
    if trigger_deploy:
        result.deploy_id = client.create_deploy(service_id)

    wanted = {
        "RENDER_DEPLOY_HOOK_URL": deploy_hook_url,
        "DEPLOY_URL": url,
        "RENDER_API_KEY": api_key,
        "RENDER_SERVICE_ID": service_id,
    }
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
    parser.add_argument(
        "--no-deploy",
        action="store_true",
        help="do not trigger a deploy after writing the environment variables (they will not take effect)",
    )
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
            trigger_deploy=not arguments.no_deploy,
        )
    except (RenderApiError, MissingSecrets, BillablePlan) as exc:
        print(f"FAIL — {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    # `auto_deploy` is the value the *service* reported back, not `render.yaml`'s — a claim about
    # R8.4 is only worth printing if the platform agrees with it.
    observed = "on" if result.auto_deploy_observed else "OFF (R8.4)"
    print(
        f"  service={blueprint.name} ({result.service_id})  {'created' if result.created else 'already existed'}\n"
        f"  plan={result.plan_observed} as reported by the service (asserted, not assumed)\n"
        f"  url={result.url}  auto_deploy={observed} as reported by the service"
        f"{' (patched from on)' if result.auto_deploy_patched and not result.created else ''}\n"
        f"  APP_ACCESS_TOKEN {'generated' if result.access_token_generated else 'kept'}: "
        f"{fingerprint(result.access_token)}\n"
        f"  deploy triggered: {result.deploy_id or '(suppressed with --no-deploy)'}\n"
        f"  github secrets set: {', '.join(result.github_secrets_set) or '(none)'}"
    )
    print(f"\n  Deployed: {result.tokenized_url}")
    print("  ^ paste that into README.md's `Deployed:` line and deployed.md's `## Access`.")
    for step in result.manual_steps:
        print(f"  TODO — {step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
