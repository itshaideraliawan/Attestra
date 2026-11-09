"""Azure OpenAI chat completions provider."""

import httpx

from attestra.providers.contracts import (
    ModelRequest,
    ModelResponse,
    ProviderConfigurationError,
    ProviderResponseError,
    parse_chat_completion,
    strict_response_format,
)
from attestra.providers.resilience import ProviderResilience
from attestra.settings import Settings


class AzureOpenAIProvider:
    """Call Azure OpenAI deployments through the versioned chat completions API."""

    name = "azure_openai"

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient,
        resilience: ProviderResilience | None = None,
    ) -> None:
        if settings.azure_openai_endpoint is None or settings.azure_openai_api_key is None:
            raise ProviderConfigurationError("Azure OpenAI endpoint and API key are required.")
        if settings.azure_openai_endpoint.scheme != "https":
            raise ProviderConfigurationError("Azure OpenAI endpoints must use HTTPS.")
        if not settings.azure_openai_deployments:
            raise ProviderConfigurationError("At least one Azure OpenAI deployment is required.")
        endpoint = str(settings.azure_openai_endpoint).rstrip("/")
        self._chat_url = (
            f"{endpoint}/chat/completions"
            if endpoint.endswith("/openai/v1")
            else f"{endpoint}/openai/v1/chat/completions"
        )
        self._api_key = settings.azure_openai_api_key.get_secret_value()
        self._deployments = settings.azure_openai_deployments
        self._api_version = settings.azure_openai_api_version
        self._input_cost = settings.azure_openai_input_cost_per_1k_tokens
        self._output_cost = settings.azure_openai_output_cost_per_1k_tokens
        self._timeout = settings.provider_timeout_seconds
        self._client = http_client
        self._resilience = resilience or ProviderResilience(
            max_attempts=settings.provider_max_attempts,
            failure_threshold=settings.provider_circuit_failure_threshold,
            reset_seconds=settings.provider_circuit_reset_seconds,
        )
        self.pii_allowed = settings.azure_openai_pii_allowed

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Generate text or strict structured output from an Azure deployment."""
        deployment = self._deployments.get(request.tier)
        if deployment is None:
            raise ProviderConfigurationError("No Azure deployment is configured for this tier.")
        payload: dict[str, object] = {
            "model": deployment,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.output_model is not None:
            payload["response_format"] = strict_response_format(request.output_model)

        response = await self._resilience.post_json(
            self._client,
            self._chat_url,
            {"api-key": self._api_key},
            payload,
            self._timeout,
            params={"api-version": self._api_version},
        )
        try:
            response_payload = response.json()
        except ValueError:
            raise ProviderResponseError("The model provider returned invalid JSON.") from None
        return parse_chat_completion(
            response_payload,
            request,
            self.name,
            deployment,
            self._input_cost,
            self._output_cost,
        )
