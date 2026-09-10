"""`scripts/provision_render.py` against a recorded Render REST API (spec §14.6, §15.2).

This script creates the only deployed thing this project has. It runs against an account this
repository has never held, and a bug in it would either create a second free service (both then
sharing one 750-hour budget) or write a `sync: false` credential to the wrong place. So the whole
of it is pinned here through an `httpx.MockTransport`, and the assertions are about the request it
*sends*: `POST /v1/services` exactly once and never on a re-run, `autoDeploy: "no"` (half of the
R8.4 argument — Render's own auto-deploy must be off so the CI hook is the only path to
production), `plan: free`, and a `PUT /v1/services/{id}/env-vars` carrying every plain value from
the committed `render.yaml` plus every `sync: false` value from the local environment.

`render.yaml` is the single source of truth in both directions: the script reads it rather than
restating it, so the committed Blueprint and the API-created service cannot drift.

The `APP_ACCESS_TOKEN` tests are the §19 "no user step" promise: the token is generated here with
`secrets.token_urlsafe(32)` and set on the service, and a re-run **keeps the token already there**
— regenerating it would silently invalidate the tokenized link in `README.md` that a grader is
expected to click.
"""

from __future__ import annotations

import json

import httpx
import pytest

from scripts import provision_render

API_KEY = "rnd_not-a-real-key"
OWNER_ID = "tea-1234"
SERVICE_ID = "srv-5678"
SERVICE_NAME = "mosaic-hr-copilot"
SERVICE_URL = f"https://{SERVICE_NAME}.onrender.com"

SECRETS = {
    "ANTHROPIC_API_KEY": "sk-ant-not-real",
    "JUDGE_API_KEY": "AIza-not-real",
    "LLM_FALLBACK_API_KEY": "AIza-also-not-real",
    "TURSO_DATABASE_URL": "libsql://mosaic-hr-org.turso.io",
    "TURSO_AUTH_TOKEN": "jwt-not-real",
}


class RecordingApi:
    """The Render endpoints the script touches, plus a log of every request it received."""

    def __init__(
        self,
        *,
        service_exists: bool = False,
        existing_env: dict[str, str] | None = None,
        auto_deploy: str = "no",
        ignores_auto_deploy_patch: bool = False,
    ) -> None:
        self.service_exists = service_exists
        self.env: dict[str, str] = dict(existing_env or {})
        self.requests: list[httpx.Request] = []
        #: What the *service* reports, which is not necessarily what `render.yaml` says: a service
        #: created by hand, or by a Blueprint deploy before `autoDeploy: false` landed, has it on.
        self.auto_deploy = auto_deploy
        self.ignores_auto_deploy_patch = ignores_auto_deploy_patch

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _service(self) -> dict:
        return {
            "id": SERVICE_ID,
            "name": SERVICE_NAME,
            "type": "web_service",
            "autoDeploy": self.auto_deploy,
            "serviceDetails": {"runtime": "docker", "plan": "free", "url": SERVICE_URL},
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path, method = request.url.path, request.method
        if request.headers.get("Authorization") != f"Bearer {API_KEY}":
            return httpx.Response(401, json={"message": "unauthorized"})
        if path == "/v1/owners":
            return httpx.Response(200, json=[{"owner": {"id": OWNER_ID, "name": "Sean", "email": "s@example.com"}}])
        if path == "/v1/services" and method == "GET":
            return httpx.Response(200, json=[{"service": self._service()}] if self.service_exists else [])
        if path == "/v1/services" and method == "POST":
            self.service_exists = True
            self.auto_deploy = json.loads(request.content).get("autoDeploy", "yes")
            return httpx.Response(201, json={"service": self._service(), "deployId": "dep-1"})
        if path == f"/v1/services/{SERVICE_ID}" and method == "GET":
            return httpx.Response(200, json=self._service())
        if path == f"/v1/services/{SERVICE_ID}" and method == "PATCH":
            if not self.ignores_auto_deploy_patch:
                self.auto_deploy = json.loads(request.content)["autoDeploy"]
            return httpx.Response(200, json=self._service())
        if path == f"/v1/services/{SERVICE_ID}/env-vars" and method == "GET":
            return httpx.Response(200, json=[{"envVar": {"key": k, "value": v}} for k, v in self.env.items()])
        if path == f"/v1/services/{SERVICE_ID}/env-vars" and method == "PUT":
            self.env = {entry["key"]: entry["value"] for entry in json.loads(request.content)}
            return httpx.Response(200, json=[{"envVar": {"key": k, "value": v}} for k, v in self.env.items()])
        return httpx.Response(404, json={"message": f"unrouted {method} {path}"})


class RecordingGh:
    """Stands in for `gh secret set`; records the names it was asked to set, never the values."""

    def __init__(self, *, fails: bool = False) -> None:
        self.names: list[str] = []
        self.fails = fails

    def __call__(self, name: str, value: str) -> bool:
        self.names.append(name)
        return not self.fails


def _client(api: RecordingApi) -> provision_render.RenderClient:
    return provision_render.RenderClient(API_KEY, transport=api.transport())


def _provision(api: RecordingApi, gh: RecordingGh | None = None, **overrides):
    blueprint = provision_render.load_blueprint()
    kwargs = {
        "repo": "https://github.com/seantmalone/quantic-mosaic",
        "branch": "main",
        "region": "oregon",
        "secret_values": dict(SECRETS),
        "deploy_hook_url": "https://api.render.com/deploy/srv-5678?key=hook",
        "gh": gh or RecordingGh(),
        "api_key": API_KEY,
    }
    kwargs.update(overrides)
    return provision_render.provision(_client(api), blueprint, **kwargs)


def _sent(api: RecordingApi, method: str, path: str) -> httpx.Request:
    return next(r for r in api.requests if r.method == method and r.url.path == path)


# --- the blueprint is the source of truth --------------------------------------------------


def test_the_blueprint_is_read_from_the_committed_render_yaml():
    blueprint = provision_render.load_blueprint()
    assert blueprint.name == SERVICE_NAME
    assert blueprint.plan == "free"
    assert blueprint.runtime == "docker"
    assert blueprint.health_check_path == "/health"
    assert blueprint.auto_deploy is False
    assert blueprint.dockerfile_path == "./Dockerfile"


def test_the_blueprint_separates_plain_values_from_sync_false_secrets():
    blueprint = provision_render.load_blueprint()
    assert blueprint.plain_env == {
        "APP_ENV": "render",
        "LLM_PROVIDER": "anthropic",
        "LLM_MODEL": "claude-haiku-4-5",
        "OMP_NUM_THREADS": "1",
    }
    assert set(blueprint.secret_keys) == set(SECRETS) | {"APP_ACCESS_TOKEN"}


# --- service creation ----------------------------------------------------------------------


def test_provision_creates_the_service_from_the_blueprint():
    api = RecordingApi()
    result = _provision(api)

    body = json.loads(_sent(api, "POST", "/v1/services").content)
    assert body["type"] == "web_service"
    assert body["name"] == SERVICE_NAME
    assert body["ownerId"] == OWNER_ID
    assert body["branch"] == "main"
    assert body["serviceDetails"]["runtime"] == "docker"
    assert body["serviceDetails"]["plan"] == "free"
    assert body["serviceDetails"]["healthCheckPath"] == "/health"
    assert body["serviceDetails"]["envSpecificDetails"]["dockerfilePath"] == "./Dockerfile"
    assert result.created is True
    assert result.service_id == SERVICE_ID
    assert result.url == SERVICE_URL


def test_auto_deploy_is_off_because_the_ci_hook_is_the_only_path_to_production():
    """R8.4, belt and braces: `autoDeploy: false` in render.yaml must reach the API as `"no"`."""
    api = RecordingApi()
    _provision(api)
    assert json.loads(_sent(api, "POST", "/v1/services").content)["autoDeploy"] == "no"


def test_provision_adopts_an_existing_service_instead_of_creating_a_second_one():
    """Two free web services would share one 750-hour budget and chain their spin-ups (§14.1)."""
    api = RecordingApi(service_exists=True)
    result = _provision(api)
    assert result.created is False
    assert not any(r.method == "POST" and r.url.path == "/v1/services" for r in api.requests)


# --- autoDeploy on the adopt path ------------------------------------------------------------


def test_an_adopted_service_with_auto_deploy_on_is_patched_off():
    """Adoption is the documented re-run path, and only `create_service` used to set autoDeploy.

    A service created by hand — or by a Blueprint deploy from before `autoDeploy: false` landed —
    keeps Render's own auto-deploy **on**, which defeats half of the R8.4 argument: a push to
    `main` would reach production without passing `needs: [test, docker]`.
    """
    api = RecordingApi(service_exists=True, auto_deploy="yes")
    result = _provision(api)
    patch = _sent(api, "PATCH", f"/v1/services/{SERVICE_ID}")
    assert json.loads(patch.content) == {"autoDeploy": "no"}
    assert result.auto_deploy_observed is False
    assert result.auto_deploy_patched is True


def test_an_adopted_service_already_matching_the_blueprint_is_not_patched():
    api = RecordingApi(service_exists=True, auto_deploy="no")
    result = _provision(api)
    assert not any(r.method == "PATCH" for r in api.requests)
    assert result.auto_deploy_observed is False
    assert result.auto_deploy_patched is False


def test_the_reported_auto_deploy_is_the_services_own_answer_not_the_blueprints():
    """The summary line used to print `render.yaml`'s value whatever the service actually said."""
    api = RecordingApi(service_exists=True, auto_deploy="yes", ignores_auto_deploy_patch=True)
    with pytest.raises(provision_render.RenderApiError) as raised:
        _provision(api)
    assert "autoDeploy" in str(raised.value)
    assert "R8.4" in str(raised.value)


def test_a_created_service_reports_auto_deploy_off_too():
    api = RecordingApi()
    result = _provision(api)
    assert result.auto_deploy_observed is False
    assert result.auto_deploy_patched is False


# --- environment variables -----------------------------------------------------------------


def test_every_blueprint_value_and_every_secret_reaches_the_service():
    api = RecordingApi()
    _provision(api)
    written = json.loads(_sent(api, "PUT", f"/v1/services/{SERVICE_ID}/env-vars").content)
    sent = {entry["key"]: entry["value"] for entry in written}
    assert sent["APP_ENV"] == "render"
    assert sent["LLM_MODEL"] == "claude-haiku-4-5"
    assert sent["OMP_NUM_THREADS"] == "1"
    for key, value in SECRETS.items():
        assert sent[key] == value
    assert sent["APP_ACCESS_TOKEN"]


def test_a_missing_secret_is_reported_and_nothing_is_written():
    """A service deployed without TURSO_* would lose every grader session at the next spin-down."""
    api = RecordingApi()
    with pytest.raises(provision_render.MissingSecrets) as raised:
        _provision(api, secret_values={"ANTHROPIC_API_KEY": "sk-ant-not-real"})
    assert "TURSO_AUTH_TOKEN" in str(raised.value)
    assert not any(r.method == "PUT" for r in api.requests)


# --- the access token ----------------------------------------------------------------------


def test_the_access_token_is_generated_here_with_no_user_step():
    api = RecordingApi()
    result = _provision(api)
    assert len(result.access_token) >= 40
    assert result.access_token_generated is True


def test_a_re_run_keeps_the_token_already_on_the_service():
    """The tokenized link in README.md must keep working across a re-provision (§14.1)."""
    api = RecordingApi(service_exists=True, existing_env={"APP_ACCESS_TOKEN": "already-issued-token"})
    result = _provision(api)
    assert result.access_token == "already-issued-token"
    assert result.access_token_generated is False


def test_the_tokenized_link_is_the_one_that_goes_into_the_readme():
    api = RecordingApi(service_exists=True, existing_env={"APP_ACCESS_TOKEN": "already-issued-token"})
    result = _provision(api)
    assert result.tokenized_url == f"{SERVICE_URL}/?access=already-issued-token"


# --- GitHub secrets ------------------------------------------------------------------------


def test_exactly_the_three_repository_secrets_of_15_2_are_set():
    api = RecordingApi()
    gh = RecordingGh()
    result = _provision(api, gh=gh)
    assert gh.names == ["RENDER_DEPLOY_HOOK_URL", "DEPLOY_URL", "RENDER_API_KEY"]
    assert result.github_secrets_set == ["RENDER_DEPLOY_HOOK_URL", "DEPLOY_URL", "RENDER_API_KEY"]


def test_without_a_deploy_hook_url_the_other_two_secrets_are_still_set():
    """The hook URL is the one value the Render REST API does not expose (§14.6)."""
    api = RecordingApi()
    gh = RecordingGh()
    result = _provision(api, gh=gh, deploy_hook_url=None)
    assert gh.names == ["DEPLOY_URL", "RENDER_API_KEY"]
    assert "RENDER_DEPLOY_HOOK_URL" in result.manual_steps[0]


def test_a_failing_gh_call_is_reported_as_a_manual_step_not_a_crash():
    api = RecordingApi()
    result = _provision(api, gh=RecordingGh(fails=True))
    assert result.github_secrets_set == []
    assert len(result.manual_steps) == 3


# --- errors --------------------------------------------------------------------------------


def test_a_render_api_error_is_reported_not_swallowed():
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"})

    client = provision_render.RenderClient(API_KEY, transport=httpx.MockTransport(refuse))
    with pytest.raises(provision_render.RenderApiError) as raised:
        provision_render.provision(
            client,
            provision_render.load_blueprint(),
            repo="https://github.com/seantmalone/quantic-mosaic",
            branch="main",
            region="oregon",
            secret_values=dict(SECRETS),
            deploy_hook_url=None,
            gh=RecordingGh(),
        )
    assert "403" in str(raised.value)
