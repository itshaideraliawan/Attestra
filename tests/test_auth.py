import asyncio
import json
import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI, Request
from pydantic import SecretStr
from starlette.testclient import TestClient

from attestra.app import create_app
from attestra.auth import EntraTokenValidator, get_request_context, get_token_validator
from attestra.context import RequestContext
from attestra.settings import Settings

ISSUER = "https://login.example.com/tenant/v2.0"
AUDIENCE = "api://attestra"
CLIENT_ID = "client-a"
KEY_ID = "test-key"
private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
public_key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
public_key.update({"kid": KEY_ID, "use": "sig", "alg": "RS256"})


def entra_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="production",
        auth_mode="entra",
        entra_issuer=ISSUER,
        entra_audience=AUDIENCE,
        entra_allowed_clients=[CLIENT_ID],
    )


def make_token(
    audience: str = AUDIENCE,
    client_id: str = CLIENT_ID,
    key_id: str = KEY_ID,
) -> str:
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": audience,
            "exp": int(time.time()) + 300,
            "azp": client_id,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": key_id},
    )


def add_context_test_route(app: FastAPI) -> None:
    @app.get("/test/context")
    async def request_context(
        context: Annotated[RequestContext, Depends(get_request_context)],
    ) -> RequestContext:
        return context


def mock_identity_provider(request_count: list[str] | None = None) -> httpx.MockTransport:
    def respond(request: httpx.Request) -> httpx.Response:
        if request_count is not None:
            request_count.append(request.url.path)
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={"jwks_uri": "https://login.example.com/keys"},
            )
        return httpx.Response(200, json={"keys": [public_key]})

    return httpx.MockTransport(respond)


@contextmanager
def entra_client(request_count: list[str] | None = None) -> Iterator[TestClient]:
    app = create_app(entra_settings())
    add_context_test_route(app)

    def override_validator(request: Request) -> EntraTokenValidator:
        if not hasattr(request.app.state, "test_token_validator"):
            request.app.state.test_token_validator = EntraTokenValidator(
                ISSUER,
                AUDIENCE,
                {CLIENT_ID},
                request.app.state.test_http_client,
            )
        return request.app.state.test_token_validator

    app.dependency_overrides[get_token_validator] = override_validator
    client = TestClient(app)
    with client:
        identity_client = httpx.AsyncClient(transport=mock_identity_provider(request_count))
        client.app.state.test_http_client = identity_client
        try:
            yield client
        finally:
            asyncio.run(identity_client.aclose())


def test_missing_token_returns_problem_json() -> None:
    with entra_client() as client:
        response = client.get(
            "/test/context",
            headers={"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a"},
        )

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Unauthorized"


def test_wrong_audience_is_rejected() -> None:
    with entra_client() as client:
        response = client.get(
            "/test/context",
            headers={
                "Authorization": f"Bearer {make_token(audience='api://other')}",
                "X-Tenant-Id": "tenant-a",
                "X-User-Id": "user-a",
            },
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "The access token is invalid."


def test_unknown_client_is_rejected() -> None:
    with entra_client() as client:
        response = client.get(
            "/test/context",
            headers={
                "Authorization": f"Bearer {make_token(client_id='client-b')}",
                "X-Tenant-Id": "tenant-a",
                "X-User-Id": "user-a",
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "The calling client is not allowed."


@pytest.mark.parametrize("missing_header", ["X-Tenant-Id", "X-User-Id"])
def test_missing_context_header_returns_problem_json(missing_header: str) -> None:
    api_key = secrets.token_urlsafe(32)
    app = create_app(Settings(dev_api_key=SecretStr(api_key), _env_file=None))
    add_context_test_route(app)
    client = TestClient(app)
    headers = {"X-API-Key": api_key}
    headers["X-User-Id" if missing_header == "X-Tenant-Id" else "X-Tenant-Id"] = "known-value"

    response = client.get(
        "/test/context",
        headers=headers,
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["detail"] == "X-Tenant-Id and X-User-Id headers are required."


def test_missing_api_key_is_rejected() -> None:
    api_key = secrets.token_urlsafe(32)
    app = create_app(Settings(dev_api_key=SecretStr(api_key), _env_file=None))
    add_context_test_route(app)

    response = TestClient(app).get(
        "/test/context",
        headers={"X-Tenant-Id": "tenant-a", "X-User-Id": "user-a"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "A valid API key is required."


def test_valid_api_key_request_returns_request_context() -> None:
    api_key = secrets.token_urlsafe(32)
    app = create_app(Settings(dev_api_key=SecretStr(api_key), _env_file=None))
    add_context_test_route(app)
    client = TestClient(app)

    response = client.get(
        "/test/context",
        headers={
            "X-API-Key": api_key,
            "X-Tenant-Id": "tenant-a",
            "X-User-Id": "user-a",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "tenant_id": "tenant-a",
        "user_id": "user-a",
        "request_id": response.headers["x-request-id"],
        "client_id": "local-development",
    }


def test_valid_entra_request_returns_verified_client() -> None:
    with entra_client() as client:
        response = client.get(
            "/test/context",
            headers={
                "Authorization": f"Bearer {make_token()}",
                "X-Tenant-Id": "tenant-a",
                "X-User-Id": "user-a",
            },
        )

    assert response.status_code == 200
    assert response.json()["client_id"] == CLIENT_ID


def test_unknown_signing_key_refresh_is_rate_limited() -> None:
    requests: list[str] = []
    with entra_client(requests) as client:
        for key_id in ("unknown-a", "unknown-b"):
            response = client.get(
                "/test/context",
                headers={
                    "Authorization": f"Bearer {make_token(key_id=key_id)}",
                    "X-Tenant-Id": "tenant-a",
                    "X-User-Id": "user-a",
                },
            )
            assert response.status_code == 401

    assert requests == [
        "/tenant/v2.0/.well-known/openid-configuration",
        "/keys",
        "/tenant/v2.0/.well-known/openid-configuration",
        "/keys",
    ]
