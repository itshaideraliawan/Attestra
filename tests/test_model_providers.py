import json

import anyio
import httpx
import pytest
import respx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from attestra.providers.azure_openai import AzureOpenAIProvider
from attestra.providers.contracts import (
    ModelRequest,
    ModelResponse,
    ModelUsage,
    ProviderConfigurationError,
    ProviderRefusalError,
    ProviderResponseError,
    strict_json_schema,
)
from attestra.providers.fake import FakeProvider
from attestra.providers.openai_compatible import OpenAICompatibleProvider
from attestra.settings import Settings


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    count: int


class ConstrainedExtraction(BaseModel):
    label: str = Field(min_length=2, pattern=r"^[a-z]+$")
    count: int = Field(ge=0)
    note: str | None = None


def test_azure_structured_output_maps_tier_and_captures_cost(
    respx_mock: respx.Router,
) -> None:
    route = respx_mock.post(
        "https://resource.example/openai/v1/chat/completions",
        params={"api-version": "v1"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"label":"approved","count":2}'}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
            },
        )
    )

    async def complete() -> ModelResponse:
        async with httpx.AsyncClient() as client:
            provider = AzureOpenAIProvider(azure_settings(), client)
            return await provider.complete(
                ModelRequest("redacted prompt", tier="strong", output_model=Extraction)
            )

    response = anyio.run(complete)

    sent = route.calls.last.request
    assert sent.headers["api-key"] == "test-azure-key"
    payload = json.loads(sent.read())
    assert payload["model"] == "deployment-strong"
    schema_format = payload["response_format"]["json_schema"]
    assert schema_format["strict"] is True
    assert schema_format["schema"]["required"] == ["label", "count"]
    assert schema_format["schema"]["additionalProperties"] is False
    assert response.structured == Extraction(label="approved", count=2)
    assert response.usage == ModelUsage(input_tokens=100, output_tokens=50)
    assert str(response.cost_usd) == "0.20000000"


def test_azure_text_output_uses_the_fast_deployment(respx_mock: respx.Router) -> None:
    route = respx_mock.post("https://resource.example/openai/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={"choices": [{"message": {"content": "plain answer"}}]},
        )
    )

    async def complete() -> ModelResponse:
        async with httpx.AsyncClient() as client:
            provider = AzureOpenAIProvider(azure_settings(), client)
            return await provider.complete(ModelRequest("prompt"))

    response = anyio.run(complete)
    payload = json.loads(route.calls.last.request.read())
    assert payload["model"] == "deployment-fast"
    assert "response_format" not in payload
    assert response.text == "plain answer"
    assert response.usage is None
    assert response.cost_usd is None


def test_strict_schema_normalizes_optional_and_local_validation_constraints() -> None:
    schema = strict_json_schema(ConstrainedExtraction)

    assert schema["required"] == ["label", "count", "note"]
    assert schema["additionalProperties"] is False
    assert "minLength" not in schema["properties"]["label"]
    assert "pattern" not in schema["properties"]["label"]
    assert "minimum" not in schema["properties"]["count"]
    assert "default" not in schema["properties"]["note"]
    assert schema["properties"]["note"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]


@pytest.mark.parametrize(
    ("body", "error_type"),
    [
        ({"choices": [{"message": {"content": "not json"}}]}, ProviderResponseError),
        (
            {"choices": [{"message": {"refusal": "refused", "content": None}}]},
            ProviderRefusalError,
        ),
        ({"choices": []}, ProviderResponseError),
    ],
)
def test_azure_rejects_invalid_structured_responses(
    respx_mock: respx.Router,
    body: dict[str, object],
    error_type: type[Exception],
) -> None:
    respx_mock.post("https://resource.example/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=body)
    )

    async def complete() -> None:
        async with httpx.AsyncClient() as client:
            provider = AzureOpenAIProvider(azure_settings(), client)
            await provider.complete(ModelRequest("prompt", output_model=Extraction))

    with pytest.raises(error_type):
        anyio.run(complete)


def test_azure_rejects_non_json_http_body(respx_mock: respx.Router) -> None:
    respx_mock.post("https://resource.example/openai/v1/chat/completions").mock(
        return_value=httpx.Response(200, text="not-json")
    )

    async def complete() -> None:
        async with httpx.AsyncClient() as client:
            provider = AzureOpenAIProvider(azure_settings(), client)
            await provider.complete(ModelRequest("prompt"))

    with pytest.raises(ProviderResponseError, match="invalid JSON"):
        anyio.run(complete)


def test_openai_compatible_provider_uses_shared_contract_and_disallows_pii_by_default(
    respx_mock: respx.Router,
) -> None:
    route = respx_mock.post("http://localhost:9000/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"label":"ok","count":1}'}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            },
        )
    )

    async def complete() -> tuple[ModelResponse, bool, str]:
        async with httpx.AsyncClient() as client:
            provider = OpenAICompatibleProvider(compatible_settings(), client)
            response = await provider.complete(
                ModelRequest("prompt", tier="strong", output_model=Extraction)
            )
            return (
                response,
                provider.pii_allowed,
                route.calls.last.request.headers.get("authorization", ""),
            )

    response, pii_allowed, authorization = anyio.run(complete)
    assert response.structured == Extraction(label="ok", count=1)
    assert response.model == "local-model-large"
    assert response.usage == ModelUsage(input_tokens=4, output_tokens=2)
    assert pii_allowed is False
    assert authorization == ""


def test_openai_compatible_provider_sends_optional_bearer_key(
    respx_mock: respx.Router,
) -> None:
    route = respx_mock.post("https://compatible.example/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    )

    async def complete() -> None:
        async with httpx.AsyncClient() as client:
            provider = OpenAICompatibleProvider(compatible_settings(api_key=True), client)
            await provider.complete(ModelRequest("prompt"))

    anyio.run(complete)
    assert route.calls.last.request.headers["authorization"] == "Bearer test-compatible-key"


def test_provider_configuration_requires_deployments() -> None:
    settings = azure_settings(azure_openai_deployments={})

    async def construct() -> None:
        async with httpx.AsyncClient() as client:
            with pytest.raises(ProviderConfigurationError, match="deployment"):
                AzureOpenAIProvider(settings, client)

    anyio.run(construct)


def test_fake_provider_returns_and_validates_fixture() -> None:
    fixture = ModelResponse(
        provider="fixture",
        model="fixture-model",
        text='{"label":"fixture","count":3}',
        usage=ModelUsage(input_tokens=5, output_tokens=3),
        cost_usd=None,
    )

    async def complete() -> ModelResponse:
        return await FakeProvider([fixture]).complete(
            ModelRequest("prompt", output_model=Extraction)
        )

    response = anyio.run(complete)
    assert response.provider == "fake"
    assert response.structured == Extraction(label="fixture", count=3)


def azure_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "dev_api_key": SecretStr("d" * 32),
        "azure_openai_endpoint": "https://resource.example",
        "azure_openai_api_key": SecretStr("test-azure-key"),
        "azure_openai_deployments": {"fast": "deployment-fast", "strong": "deployment-strong"},
        "azure_openai_input_cost_per_1k_tokens": "1.0",
        "azure_openai_output_cost_per_1k_tokens": "2.0",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def compatible_settings(api_key: bool = False) -> Settings:
    return Settings(
        dev_api_key=SecretStr("d" * 32),
        openai_compatible_base_url=(
            "https://compatible.example" if api_key else "http://localhost:9000"
        ),
        openai_compatible_api_key=SecretStr("test-compatible-key") if api_key else None,
        openai_compatible_models={"fast": "local-model", "strong": "local-model-large"},
        _env_file=None,
    )
