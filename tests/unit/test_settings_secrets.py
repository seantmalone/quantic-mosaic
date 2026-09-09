"""Credential fields are `SecretStr`, so no printed `Settings` can leak a key (spec §12.3, R1.5).

The failure this pins is pytest's own: an assertion whose expression mentions `settings` prints
the object's repr into the report — and a CI log is a public artifact. `SecretStr` makes that
repr, `str()` and `model_dump()` render `**********`, and `secret_value()` is the single place
the plaintext is opened, at the point of use.

The §12.3 rule that credentials are validated **lazily** is unchanged and asserted here too: an
unset key still builds an adapter, which reports `configured is False` rather than raising.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from hrmosaic.core.llm import build_agent_model, build_fallback_model, build_judge_model
from hrmosaic.settings import Settings, secret_value

FAKE_KEY = "sk-ant-fake-000-never-a-real-credential"

#: Every §12.3 field whose name ends `_api_key`, `_token` or `_secret`.
CREDENTIAL_FIELDS = (
    "anthropic_api_key",
    "llm_api_key",
    "llm_fallback_api_key",
    "judge_api_key",
    "turso_auth_token",
    "app_access_token",
)


def _settings(**overrides) -> Settings:
    # `_env_file=None`: a unit test never reads the developer's real `.env`.
    unset = dict.fromkeys(CREDENTIAL_FIELDS)
    return Settings(_env_file=None, **{**unset, **overrides})


def test_every_credential_field_is_a_secret_str():
    """The list above is the whole set — a new `_api_key`/`_token`/`_secret` field must join it."""
    suffixes = ("_api_key", "_token", "_secret")
    named = {name for name in Settings.model_fields if name.endswith(suffixes)}

    assert named == set(CREDENTIAL_FIELDS)
    for name in CREDENTIAL_FIELDS:
        assert isinstance(getattr(_settings(**{name: FAKE_KEY}), name), SecretStr)


@pytest.mark.parametrize("name", CREDENTIAL_FIELDS)
def test_the_repr_of_a_configured_settings_never_contains_the_key(name):
    settings = _settings(**{name: FAKE_KEY})

    assert FAKE_KEY not in repr(settings)
    assert FAKE_KEY not in str(settings)
    assert FAKE_KEY not in str(settings.model_dump())
    assert FAKE_KEY not in str(settings.model_dump(mode="json"))
    assert settings.model_dump(mode="json")[name] == "**********"


def test_the_masked_value_is_what_a_failing_assertion_would_print():
    # The P4 review's actual failure mode: `assert settings.port == 9` prints the whole repr.
    settings = _settings(anthropic_api_key=FAKE_KEY, turso_auth_token=FAKE_KEY)

    assert "anthropic_api_key=SecretStr('**********')" in repr(settings)
    assert "turso_auth_token=SecretStr('**********')" in repr(settings)


def test_get_secret_value_returns_the_key_at_the_point_of_use():
    settings = _settings(anthropic_api_key=FAKE_KEY)

    assert settings.anthropic_api_key.get_secret_value() == FAKE_KEY
    assert secret_value(settings.anthropic_api_key) == FAKE_KEY


def test_an_unset_or_empty_credential_reads_as_not_configured():
    assert secret_value(None) is None
    assert secret_value(SecretStr("")) is None
    assert secret_value(_settings().anthropic_api_key) is None
    # `KEY=` in an untouched `.env` is an absent credential, not a key that is the empty string.
    assert secret_value(_settings(anthropic_api_key="").anthropic_api_key) is None


def test_an_unset_credential_still_builds_an_adapter_that_reports_not_configured():
    """§12.3: boot always succeeds; the missing key surfaces through `configured`, not an import."""
    settings = _settings(llm_provider="anthropic", judge_provider="openai_compat")

    assert build_agent_model(settings).configured is False
    assert build_judge_model(settings).configured is False
    assert build_fallback_model(settings).configured is False


def test_a_configured_credential_reaches_the_adapter_as_plaintext():
    settings = _settings(anthropic_api_key=FAKE_KEY, llm_api_key=FAKE_KEY, llm_fallback_api_key=FAKE_KEY)

    assert build_agent_model(settings).configured is True
    assert build_judge_model(settings).configured is True
    assert build_fallback_model(settings).configured is True
    # The plaintext, not the mask, is what the SDK client is built with.
    assert build_agent_model(settings).client().api_key == FAKE_KEY
