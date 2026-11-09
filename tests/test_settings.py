import secrets

import pytest
from pydantic import SecretStr

from attestra.settings import Settings


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATT_APP_NAME", "Test service")
    monkeypatch.setenv("ATT_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ATT_DEV_API_KEY", secrets.token_urlsafe(32))

    settings = Settings(_env_file=None)

    assert settings.app_name == "Test service"
    assert settings.log_level == "DEBUG"


def test_settings_reject_invalid_log_level() -> None:
    with pytest.raises(ValueError):
        Settings(
            dev_api_key=SecretStr(secrets.token_urlsafe(32)),
            log_level="TRACE",
        )


def test_api_key_mode_is_restricted_to_development() -> None:
    with pytest.raises(ValueError, match="only available in development"):
        Settings(
            environment="production",
            dev_api_key=SecretStr(secrets.token_urlsafe(32)),
        )


def test_entra_mode_requires_issuer_audience_and_clients() -> None:
    with pytest.raises(ValueError, match="issuer, audience, and allowed clients"):
        Settings(auth_mode="entra")
