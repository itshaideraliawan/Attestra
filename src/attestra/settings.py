"""Validated application settings."""

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-backed settings for the Attestra service."""

    model_config = SettingsConfigDict(env_prefix="ATT_", env_file=".env", extra="ignore")

    app_name: str = "Attestra"
    environment: str = "development"
    log_level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")
    auth_mode: Literal["api_key", "entra"] = "api_key"
    dev_api_key: SecretStr | None = Field(default=None, min_length=32)
    dev_client_id: str = "local-development"
    entra_issuer: AnyHttpUrl | None = None
    entra_audience: str | None = None
    entra_allowed_clients: list[str] = Field(default_factory=list)
    database_url: str = "postgresql+asyncpg://localhost/attestra"
    tenant_policy_cache_seconds: float = Field(default=30.0, gt=0, le=300)
    provider_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    provider_max_attempts: int = Field(default=3, ge=1, le=8)
    provider_circuit_failure_threshold: int = Field(default=5, ge=1, le=20)
    provider_circuit_reset_seconds: float = Field(default=30.0, gt=0, le=300)
    azure_openai_endpoint: AnyHttpUrl | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_api_version: str = "v1"
    azure_openai_deployments: dict[str, str] = Field(default_factory=dict)
    azure_openai_pii_allowed: bool = False
    azure_openai_input_cost_per_1k_tokens: Decimal | None = Field(default=None, ge=0)
    azure_openai_output_cost_per_1k_tokens: Decimal | None = Field(default=None, ge=0)
    openai_compatible_base_url: AnyHttpUrl | None = None
    openai_compatible_api_key: SecretStr | None = None
    openai_compatible_models: dict[str, str] = Field(default_factory=dict)
    openai_compatible_pii_allowed: bool = False
    openai_compatible_input_cost_per_1k_tokens: Decimal | None = Field(default=None, ge=0)
    openai_compatible_output_cost_per_1k_tokens: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_auth_configuration(self) -> "Settings":
        if self.auth_mode == "api_key":
            if self.environment.lower() != "development":
                raise ValueError("API key authentication is only available in development")
            if self.dev_api_key is None:
                raise ValueError("ATT_DEV_API_KEY is required in API key mode")
        elif not self.entra_issuer or not self.entra_audience or not self.entra_allowed_clients:
            raise ValueError(
                "Entra authentication requires an issuer, audience, and allowed clients"
            )
        elif self.entra_issuer.scheme != "https":
            raise ValueError("The Entra issuer must use HTTPS")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Load and cache application settings."""
    return Settings()
