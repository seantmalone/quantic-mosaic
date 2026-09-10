"""The four deployment manifests, asserted as contracts (spec §14.1, §14.2, §14.5, §15.1).

`Dockerfile`, `render.yaml`, `.dockerignore` and the `docker`/`deploy` jobs of `ci.yml` are the
only artifacts in this repository that no test can otherwise reach: they are executed by Docker and
by GitHub Actions, not by pytest, and a mistake in any of them shows up as a red deploy or — worse
— as a green one that shipped the wrong thing. So the properties that carry an argument are pinned
here.

The load-bearing ones, and what each would cost if it silently drifted:

* **`CMD` is the `sh -c` form** (§14.2). Render injects `$PORT`; the exec form would pass the
  literal string `${PORT}` to uvicorn and the service would never bind.
* **`--workers 1`** (§2.1). A second worker doubles the ONNX session against a 512 MB cap and
  splits the in-process MCP server and the span buffer across processes.
* **The index and the model are built at *build* time** (§14.2, §14.4). At boot they would cost a
  corpus ingestion and a 16–63 s model download on 0.1 CPU, on every spin-up.
* **`autoDeploy: false` plus `needs: [test, docker]`** (§14.5) — together these are the whole R8.4
  claim that deployment cannot happen unless tests pass. Either one alone is not the claim.
* **The `.dockerignore` negations** (P0). `tests/` and `data/index/*` are excluded wholesale and
  two paths re-included; if a negation stops matching, the default `LLM_STUB_SCRIPT` cannot resolve
  inside the container and `--verify-manifest` has nothing to verify against. The build proves this
  against Docker's own matcher — the `COPY` lines fail outright — and this test proves the
  *intent* is still written down.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
DOCKERIGNORE = (ROOT / ".dockerignore").read_text(encoding="utf-8")
RENDER_YAML_TEXT = (ROOT / "render.yaml").read_text(encoding="utf-8")
CI_TEXT = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
CI = yaml.safe_load(CI_TEXT)
RENDER_SERVICE = yaml.safe_load(RENDER_YAML_TEXT)["services"][0]

#: The five `sync: false` credentials plus the generated access token (§14.1).
SYNC_FALSE_KEYS = {
    "ANTHROPIC_API_KEY",
    "JUDGE_API_KEY",
    "LLM_FALLBACK_API_KEY",
    "TURSO_DATABASE_URL",
    "TURSO_AUTH_TOKEN",
    "APP_ACCESS_TOKEN",
}


def _steps(job: str) -> list[dict]:
    return CI["jobs"][job]["steps"]


def _run_lines(job: str) -> str:
    return "\n".join(str(step.get("run", "")) for step in _steps(job))


# --- Dockerfile ---------------------------------------------------------------------------


def test_the_base_image_is_the_pinned_python_3_12_slim():
    froms = [line for line in DOCKERFILE.splitlines() if line.startswith("FROM ")]
    assert froms == ["FROM python:3.12-slim"]


def test_the_command_expands_port_through_a_shell_and_runs_one_worker():
    """Render injects `$PORT`; the exec form would hand uvicorn the literal string (§14.2)."""
    command = next(line for line in DOCKERFILE.splitlines() if line.startswith("CMD "))
    assert command.startswith('CMD ["sh", "-c",')
    assert "${PORT:-8000}" in command
    assert "--workers 1" in command
    assert "--host 0.0.0.0" in command


def test_the_model_is_baked_and_the_cache_path_is_the_container_one():
    """`/app/models` is not writable on macOS or a GH runner, so it must not be the default (§12.3)."""
    assert "FASTEMBED_CACHE_PATH=/app/models" in DOCKERFILE
    assert "cache_dir='/app/models'" in DOCKERFILE
    assert "BAAI/bge-small-en-v1.5" in DOCKERFILE


def test_the_index_is_built_and_verified_at_build_time_not_at_boot():
    assert "RUN python -m hrmosaic.rag.ingest --verify-manifest" in DOCKERFILE
    assert "python -m hrmosaic.rag.index --selftest" in DOCKERFILE


def test_the_image_exports_python_for_the_two_mcp_shell_entrypoints():
    """`mcp/run_*.sh` default to `.venv/bin/python`, a path that does not exist here (§8.1)."""
    assert re.search(r"^\s*PYTHON=python( |$)", DOCKERFILE, re.MULTILINE)


def test_the_image_ships_the_templates_the_static_assets_and_the_prompts():
    """P9's Jinja templates and vendored assets, and P7's three prompts, all live under `src/`."""
    assert "COPY src/ src/" in DOCKERFILE
    for path in (
        "src/hrmosaic/web/templates/chat.html",
        "src/hrmosaic/web/static/app.css",
        "src/hrmosaic/agent/prompts/act.j2",
    ):
        assert f"test -f {path}" in DOCKERFILE


def test_the_image_ships_the_stub_scripts_and_the_committed_manifest():
    assert "COPY tests/fixtures/llm_scripts/ tests/fixtures/llm_scripts/" in DOCKERFILE
    assert "COPY data/index/chunks.manifest.jsonl data/index/" in DOCKERFILE


def test_requirements_dev_never_enters_the_image():
    assert "requirements-dev.txt" not in DOCKERFILE


def test_the_dockerignore_negations_are_still_written_down():
    lines = [line.strip() for line in DOCKERIGNORE.splitlines()]
    assert lines.index("tests/") < lines.index("!tests/fixtures/llm_scripts/")
    assert lines.index("data/index/*") < lines.index("!data/index/chunks.manifest.jsonl")


# --- render.yaml --------------------------------------------------------------------------


def test_the_blueprint_describes_one_free_docker_web_service():
    assert RENDER_SERVICE["type"] == "web"
    assert RENDER_SERVICE["runtime"] == "docker"
    assert RENDER_SERVICE["plan"] == "free"
    assert RENDER_SERVICE["dockerfilePath"] == "./Dockerfile"


def test_the_health_check_path_is_the_always_200_endpoint():
    """`/health` is 200 while the process is up whatever failed, so Render never restart-loops."""
    assert RENDER_SERVICE["healthCheckPath"] == "/health"


def test_auto_deploy_is_off_so_the_ci_hook_is_the_only_path_to_production():
    assert RENDER_SERVICE["autoDeploy"] is False


def test_every_credential_is_sync_false_and_no_credential_carries_a_value():
    entries = RENDER_SERVICE["envVars"]
    assert {entry["key"] for entry in entries if entry.get("sync") is False} == SYNC_FALSE_KEYS
    assert not [entry for entry in entries if entry.get("sync") is False and "value" in entry]


def test_the_plain_values_pin_the_environment_the_agent_model_and_the_thread_count():
    plain = {entry["key"]: entry["value"] for entry in RENDER_SERVICE["envVars"] if "value" in entry}
    assert plain == {
        "APP_ENV": "render",
        "LLM_PROVIDER": "anthropic",
        "LLM_MODEL": "claude-haiku-4-5",
        "OMP_NUM_THREADS": "1",
    }


# --- ci.yml: the docker job ---------------------------------------------------------------


def test_ci_has_the_four_jobs_of_15_1():
    assert list(CI["jobs"]) == ["lint", "test", "docker", "deploy"]


def test_the_docker_job_builds_the_image_stamped_with_the_commit():
    assert "docker build -t mosaic-hr --build-arg GIT_SHA=${{ github.sha }} ." in _run_lines("docker")


def test_the_docker_job_probes_sqlite_vec_inside_a_bare_debian_python():
    """`enable_load_extension` is compiled out of some builds; the runner's Python is not Debian's."""
    runs = _run_lines("docker")
    assert "python:3.12-slim" in runs
    assert "scripts/probe_sqlite_vec.py" in runs


def test_the_docker_job_runs_the_image_with_the_gate_on_and_a_throwaway_token():
    """§15.2: the access token is never a CI secret; the job passes its own inline."""
    runs = _run_lines("docker")
    assert "-e APP_ACCESS_TOKEN=ci-access-token" in runs
    assert "-e LLM_PROVIDER=stub" in runs


def test_the_docker_job_waits_for_health_and_then_asserts_it():
    runs = _run_lines("docker")
    assert "scripts/wait_for_health.py" in runs
    assert "scripts/assert_health.py" in runs


def test_the_docker_job_proves_the_image_can_render_a_page():
    """P9 carry-forward: templates and static assets must ship, not just import (§14.2).

    `/access` is the §11.8 key page and is **never gated**, so rendering it proves the Jinja
    templates arrived without spending a credential; `/static/*` is open too.
    """
    runs = _run_lines("docker")
    assert "/access" in runs
    assert "/static/app.css" in runs


def test_the_docker_job_makes_no_gated_call():
    """§15.2, verbatim: this job "makes **no** gated call".

    It passes a throwaway `APP_ACCESS_TOKEN` inline so the image boots *with the gate on*, but it
    never presents that token: an earlier revision curled `/` and `/dashboard` with
    `Authorization: Bearer` and `X-Actor: admin`, which contradicted the section. The MCP handshake
    that `/dashboard` was there to prove is asserted, credential-free, by `assert_health.py`.
    """
    runs = _run_lines("docker")
    assert "Authorization:" not in runs
    assert "X-Actor:" not in runs


def test_the_docker_job_always_dumps_the_container_log():
    teardown = [step for step in _steps("docker") if step.get("if") == "always()"]
    assert any("docker logs app" in str(step.get("run", "")) for step in teardown)


# --- ci.yml: the deploy job ---------------------------------------------------------------


def test_deploy_needs_both_test_and_docker():
    """R8.4 in one line: Actions skips a job whose `needs` failed."""
    assert CI["jobs"]["deploy"]["needs"] == ["test", "docker"]


def test_deploy_runs_only_on_a_main_push_or_a_deliberate_dispatch():
    condition = " ".join(CI["jobs"]["deploy"]["if"].split())
    assert "github.event_name == 'push'" in condition
    assert "github.ref == 'refs/heads/main'" in condition
    assert "inputs.deploy_only == 'true'" in condition


def test_the_first_deploy_step_fails_loudly_when_either_deploy_secret_is_unset():
    """Until user gates 2–4 land there is no hook, and the job must say so, not skip quietly.

    `DEPLOY_URL` is guarded in the same step: unset, it expands to `""`, and the two scripts that
    consume it would otherwise be the first place the operator learns anything is wrong.
    """
    first = _steps("deploy")[0]
    assert "RENDER_DEPLOY_HOOK_URL" in str(first.get("env", {}))
    assert "RENDER_DEPLOY_HOOK_URL" in first["run"]
    assert "DEPLOY_URL" in first["run"]
    assert "exit 1" in first["run"]
    assert "NEEDS-FROM-USER.md" in first["run"]


def test_the_deploy_job_curls_the_hook_then_waits_then_smokes():
    runs = [str(step.get("run", "")) for step in _steps("deploy")]
    hook = next(index for index, run in enumerate(runs) if 'curl -fsS -X POST "$RENDER_DEPLOY_HOOK_URL"' in run)
    wait = next(index for index, run in enumerate(runs) if "scripts/wait_for_deploy.py" in run)
    smoke = next(index for index, run in enumerate(runs) if "scripts/smoke_deployed.py" in run)
    assert hook < wait < smoke


def test_the_deploy_job_reads_deploy_url_from_the_repository_secret():
    assert CI["jobs"]["deploy"]["env"]["DEPLOY_URL"] == "${{ secrets.DEPLOY_URL }}"


def test_no_model_key_and_no_access_token_is_a_ci_secret():
    """§15.2: exactly three repository secrets, and none of them is a credential the app answers with."""
    referenced = set(re.findall(r"secrets\.([A-Z_]+)", CI_TEXT))
    assert referenced == {"GITHUB_TOKEN", "RENDER_DEPLOY_HOOK_URL", "DEPLOY_URL"}
