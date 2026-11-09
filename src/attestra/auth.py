"""Authentication dependencies for development keys and Microsoft Entra ID."""

import asyncio
import hmac
import time
from typing import Annotated, Any, cast
from urllib.parse import urlparse

import httpx
import jwt
from fastapi import Depends, Request
from jwt import PyJWK
from jwt.exceptions import PyJWKError

from attestra.context import RequestContext
from attestra.problems import ProblemException
from attestra.settings import Settings

_jwks_cache_seconds = 3600
_unknown_kid_refresh_interval = 30


class EntraTokenValidator:
    """Validate Entra ID access tokens against configured issuer and clients."""

    def __init__(
        self,
        issuer: str,
        audience: str,
        allowed_clients: set[str],
        http_client: httpx.AsyncClient,
    ) -> None:
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.allowed_clients = allowed_clients
        self.http_client = http_client
        self._keys: list[dict[str, Any]] = []
        self._keys_expire_at = 0.0
        self._next_unknown_kid_refresh = 0.0
        self._keys_lock = asyncio.Lock()

    async def validate(self, token: str) -> str:
        """Validate a bearer token and return its authorized client ID."""
        try:
            unverified_header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as error:
            raise self._invalid_token() from error

        key_id = unverified_header.get("kid")
        if unverified_header.get("alg") != "RS256" or not isinstance(key_id, str):
            raise self._invalid_token()

        keys = await self._get_signing_keys()
        signing_key = next((key for key in keys if key.get("kid") == key_id), None)
        if signing_key is None:
            keys = await self._get_signing_keys(force_refresh=True)
            signing_key = next((key for key in keys if key.get("kid") == key_id), None)
        if signing_key is None:
            raise self._invalid_token()

        try:
            public_key = PyJWK.from_dict(signing_key).key
            claims = jwt.decode(
                token,
                public_key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iss", "aud"]},
            )
        except (jwt.InvalidTokenError, PyJWKError, TypeError, ValueError) as error:
            raise self._invalid_token() from error

        client_id = claims.get("azp") or claims.get("appid")
        if not isinstance(client_id, str) or client_id not in self.allowed_clients:
            raise ProblemException(403, "Forbidden", "The calling client is not allowed.")
        return client_id

    async def _get_signing_keys(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        if not force_refresh and self._keys and time.monotonic() < self._keys_expire_at:
            return self._keys

        async with self._keys_lock:
            if not force_refresh and self._keys and time.monotonic() < self._keys_expire_at:
                return self._keys
            if force_refresh:
                current_time = time.monotonic()
                if current_time < self._next_unknown_kid_refresh:
                    return self._keys
                self._next_unknown_kid_refresh = current_time + _unknown_kid_refresh_interval
            try:
                discovery_response = await self.http_client.get(
                    f"{self.issuer}/.well-known/openid-configuration"
                )
                discovery_response.raise_for_status()
                jwks_uri = discovery_response.json()["jwks_uri"]
                parsed_jwks_uri = urlparse(jwks_uri)
                if (
                    parsed_jwks_uri.scheme != "https"
                    or parsed_jwks_uri.hostname != urlparse(self.issuer).hostname
                ):
                    raise ValueError("Untrusted signing key URL")
                keys_response = await self.http_client.get(jwks_uri)
                keys_response.raise_for_status()
                key_document = keys_response.json()
                keys = key_document["keys"]
                if not isinstance(keys, list) or not keys:
                    raise ValueError("No signing keys were published")
                if not all(
                    isinstance(key, dict) and isinstance(key.get("kid"), str) for key in keys
                ):
                    raise ValueError("Signing keys do not contain key IDs")
                self._keys = keys
                self._keys_expire_at = time.monotonic() + _jwks_cache_seconds
            except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
                raise ProblemException(
                    503,
                    "Authentication unavailable",
                    "The identity provider could not be reached.",
                    headers={"Retry-After": "30"},
                ) from error
        return self._keys

    @staticmethod
    def _invalid_token() -> ProblemException:
        return ProblemException(
            401,
            "Unauthorized",
            "The access token is invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_settings(request: Request) -> Settings:
    """Return the settings bound to the current application."""
    return cast(Settings, request.app.state.settings)


def get_token_validator(request: Request) -> EntraTokenValidator | None:
    """Build and cache the Entra validator for the current application."""
    settings: Settings = request.app.state.settings
    if settings.auth_mode != "entra":
        return None
    if not hasattr(request.app.state, "entra_token_validator"):
        request.app.state.entra_token_validator = EntraTokenValidator(
            issuer=str(settings.entra_issuer),
            audience=settings.entra_audience or "",
            allowed_clients=set(settings.entra_allowed_clients),
            http_client=request.app.state.entra_http_client,
        )
    return cast(EntraTokenValidator, request.app.state.entra_token_validator)


async def get_request_context(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    token_validator: Annotated[EntraTokenValidator | None, Depends(get_token_validator)],
) -> RequestContext:
    """Authenticate the request and require its tenant and user headers."""
    if settings.auth_mode == "api_key":
        provided_key = request.headers.get("x-api-key", "")
        expected_key = settings.dev_api_key.get_secret_value() if settings.dev_api_key else ""
        if not expected_key or not hmac.compare_digest(
            provided_key.encode("utf-8"), expected_key.encode("utf-8")
        ):
            raise ProblemException(401, "Unauthorized", "A valid API key is required.")
        client_id = settings.dev_client_id
    else:
        authorization = request.headers.get("authorization", "")
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            raise EntraTokenValidator._invalid_token()
        if token_validator is None:
            raise ProblemException(
                503,
                "Authentication unavailable",
                "The identity provider is not configured.",
            )
        client_id = await token_validator.validate(token.strip())

    tenant_id = request.headers.get("x-tenant-id", "").strip()
    user_id = request.headers.get("x-user-id", "").strip()
    if not tenant_id or not user_id:
        raise ProblemException(
            400,
            "Invalid request context",
            "X-Tenant-Id and X-User-Id headers are required.",
        )

    return RequestContext(
        tenant_id=tenant_id,
        user_id=user_id,
        request_id=request.state.request_id,
        client_id=client_id,
    )
