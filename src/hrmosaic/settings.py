"""Process configuration — the single place the application reads the environment (spec §12.3).

Validation model: **structural** validation happens at import (types, enum membership, path
shapes, numeric ranges) and fails fast, because those are programmer errors. **Credentials are
validated lazily, at the point of use, so boot always succeeds**: a missing key degrades the
surface that needs it and never raises at import.

Credentials are typed `SecretStr`, so a `Settings` instance can be printed, logged or dumped
without disclosing a key: `repr()`, `str()` and `model_dump()` all render `**********`, and the
plaintext is reachable only through `secret_value()` at the point of use. That matters most in
pytest, where a failing assertion whose expression mentions `settings` prints the whole repr.

`.env.example` mirrors this module field for field; `tests/contract/test_env_example_covers_settings.py`
asserts the bijection in both directions.
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path
from typing import Literal

from pydantic import Field, PrivateAttr, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

TARGET_PYTHON = (3, 12)

if sys.version_info[:2] != TARGET_PYTHON:
    # A warning, never an exception: an unexpected interpreter must not stop the app from booting.
    warnings.warn(
        f"Mosaic HR Copilot targets Python {TARGET_PYTHON[0]}.{TARGET_PYTHON[1]}; "
        f"running on {sys.version_info.major}.{sys.version_info.minor}.",
        RuntimeWarning,
        stacklevel=2,
    )

#: Settings fields that carry no `.env.example` entry because nothing reads them from the
#: environment. Empty by construction: every field below is a §12.3 environment variable.
DERIVED_FIELDS: frozenset[str] = frozenset()

Provider = Literal["anthropic", "openai_compat", "stub"]

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


class Settings(BaseSettings):
    """Every environment variable of §12.3, in the order of that table."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True,
    )

    # --- application ---------------------------------------------------------------------
    port: int = Field(default=8000, ge=1, le=65535)
    app_env: Literal["local", "docker", "render"] = "local"
    git_sha: str = "dev"

    # --- agent provider ------------------------------------------------------------------
    llm_provider: Provider = "anthropic"
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "claude-haiku-4-5"
    llm_base_url: str = GEMINI_OPENAI_BASE_URL
    llm_api_key: SecretStr | None = None
    llm_daily_call_cap: int = Field(default=1500, ge=1)
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    llm_stub_script: Path = Path("tests/fixtures/llm_scripts/demo_task_1.json")
    llm_rpm: int = Field(default=10, ge=1)
    llm_burst: int | None = Field(default=None, ge=1)

    # --- failover provider ---------------------------------------------------------------
    llm_fallback_provider: Provider = "openai_compat"
    llm_fallback_base_url: str = GEMINI_OPENAI_BASE_URL
    llm_fallback_model: str = "gemini-3.5-flash-lite"
    llm_fallback_api_key: SecretStr | None = None

    # --- judge provider ------------------------------------------------------------------
    judge_provider: Provider = "openai_compat"
    judge_base_url: str = GEMINI_OPENAI_BASE_URL
    judge_model: str = "gemini-3.5-flash-lite"
    judge_api_key: SecretStr | None = None

    # --- embeddings ----------------------------------------------------------------------
    embed_provider: Literal["fastembed", "fake"] = "fastembed"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_dim: int = Field(default=384, ge=1)
    embed_warmup: bool = True
    fastembed_cache_path: Path = Path("./.cache/fastembed")

    # --- retrieval -----------------------------------------------------------------------
    index_path: Path = Path("data/index/hr_index.sqlite")
    retrieval_k: int = Field(default=5, ge=1, le=10)
    retrieval_strategy: Literal["hybrid_rrf", "dense_only"] = "hybrid_rrf"
    # Calibrated at P10 (2026-09-09) from the observed dense-score distribution over this corpus,
    # not guessed: 26 dataset questions plus 8 extra out-of-corpus probes, retrieval only. The two
    # populations separate cleanly — in-scope `max_dense_score` ∈ [0.622, 0.917], out-of-scope
    # ∈ [0.466, 0.584] — so 0.60 is the midpoint of the gap and 0.45 sits above the observed noise
    # floor (0.29) yet below every in-scope top-5 score (0.574). The shipped 0.32 / 0.26 were below
    # the model's cosine floor over this corpus, which made G1's score clauses unreachable (§21).
    min_evidence_score: float = Field(default=0.60, ge=0.0, le=1.0)
    min_support_score: float = Field(default=0.45, ge=0.0, le=1.0)

    # --- chunking ------------------------------------------------------------------------
    chunk_max_chars: int = Field(default=1400, ge=1)
    chunk_window_chars: int = Field(default=1100, ge=1)
    chunk_overlap_chars: int = Field(default=150, ge=0)
    chunk_min_chars: int = Field(default=120, ge=1)

    # --- agent loop budgets --------------------------------------------------------------
    agent_max_steps: int = Field(default=6, ge=1)
    agent_max_tool_calls: int = Field(default=8, ge=1)
    agent_wall_clock_s: int = Field(default=90, ge=1)

    # --- MCP ------------------------------------------------------------------------------
    mcp_transport: Literal["http", "stdio"] = "http"
    mcp_server_url: str | None = None
    mcp_tools_disabled: str = ""
    mcp_allowed_hosts: str = "127.0.0.1:*,localhost:*"

    # --- persistence -----------------------------------------------------------------------
    turso_database_url: str | None = None
    turso_auth_token: SecretStr | None = None
    persist_backend: Literal["auto", "sqlite", "turso"] = "auto"
    trace_db_path: Path = Path("data/runtime/traces.sqlite")
    trace_retention_sessions: int = Field(default=300, ge=1)

    # --- access ------------------------------------------------------------------------------
    app_access_token: SecretStr | None = None
    access_rate_limit_per_min: int = Field(default=30, ge=1)

    # --- evaluation ---------------------------------------------------------------------------
    eval_target_base_url: str = "http://127.0.0.1:8000"
    eval_cold_idle_s: int = Field(default=1000, ge=0)
    eval_smoke_max_items: int = Field(default=6, ge=1)

    # --- misc ----------------------------------------------------------------------------------
    llm_cache_ttl_s: int = Field(default=0, ge=0)
    ready_warmup_timeout_s: int = Field(default=30, ge=1)

    # --- keep-alive ------------------------------------------------------------------------------
    keep_alive_url: str | None = None
    keep_alive_interval_s: int = Field(default=600, ge=1)

    _mcp_server_url_explicit: bool = PrivateAttr(default=False)

    @field_validator("git_sha", mode="before")
    @classmethod
    def _resolve_git_sha(cls, value: object) -> object:
        """`GIT_SHA` → `RENDER_GIT_COMMIT` → `"dev"` (§12.3)."""
        if value in (None, "", "dev"):
            return os.environ.get("RENDER_GIT_COMMIT") or "dev"
        return value

    @field_validator("llm_stub_script", "fastembed_cache_path", "index_path", "trace_db_path", mode="before")
    @classmethod
    def _reject_empty_path(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("path settings must not be empty")
        return value

    @model_validator(mode="after")
    def _apply_computed_defaults(self) -> Settings:
        """`LLM_BURST` defaults to `LLM_RPM`; `MCP_SERVER_URL` is computed from the resolved `PORT`."""
        if self.llm_burst is None:
            self.llm_burst = self.llm_rpm
        self._mcp_server_url_explicit = bool(self.mcp_server_url)
        if not self.mcp_server_url:
            self.mcp_server_url = self.default_mcp_server_url
        return self

    @property
    def default_mcp_server_url(self) -> str:
        """The in-process loopback mount, resolved against the port Render actually injected."""
        return f"http://127.0.0.1:{self.port}/mcp-server/mcp"

    @property
    def mcp_allowed_hosts_list(self) -> list[str]:
        """`MCP_ALLOWED_HOSTS` as the SDK's `allowed_hosts` wants it — blanks dropped.

        A trailing comma or a stray space would otherwise put `""` on the allowlist, and an empty
        allowed host is a host no request can carry: harmless, but it reads like a hole.
        """
        return [entry.strip() for entry in self.mcp_allowed_hosts.split(",") if entry.strip()]

    @property
    def mcp_transport_effective(self) -> str:
        """What `sessions.mcp_transport` records: `remote` | `stdio` | `http` (§12.3)."""
        if self._mcp_server_url_explicit and self.mcp_server_url != self.default_mcp_server_url:
            return "remote"
        if self.mcp_transport == "stdio":
            return "stdio"
        return "http"


def secret_value(secret: SecretStr | None) -> str | None:
    """The plaintext behind a credential field — the one place a `SecretStr` is opened.

    Callers read it at the point of use, never at import, so the "credential validation is
    deferred to first use" rule of §12.3 is unchanged. An **empty** credential reads exactly like
    an absent one: an untouched `.env.example` line leaves `KEY=` behind, and the empty string is
    not a configured key.
    """
    if secret is None:
        return None
    return secret.get_secret_value() or None


#: Structural validation happens here, at import. Credentials are not touched.
settings = Settings()
