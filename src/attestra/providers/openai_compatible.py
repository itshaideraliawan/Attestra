"""Provider for OpenAI-compatible chat completion endpoints."""

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


class OpenAICompatibleProvider:
    """Call an OpenAI-compatible endpoint using configured tier-to-model mappings."""

    name = "openai_compatible"

    def __init__(
        self,
        settings: Settings,
        http_client: httpx.AsyncClient,
        resilience: ProviderResilience | None = None,
    ) -> None:
        if settings.openai_compatible_base_url is None:
            raise ProviderConfigurationError("An OpenAI-compatible base URL is required.")
        if not settings.openai_compatible_models:
            raise ProviderConfigurationError("At least one compatible model is required.")
        if (
            settings.openai_compatible_api_key is not None
            and settings.openai_compatible_base_url.scheme != "https"
        ):
            raise ProviderConfigurationError("API keys require an HTTPS provider endpoint.")
        self._base_url = str(settings.openai_compatible_base_url).rstrip("/")
        self._api_key = (
            settings.openai_compatible_api_key.get_secret_value()
            if settings.openai_compatible_api_key
            else None
        )
        self._models = settings.openai_compatible_models
        self._input_cost = settings.openai_compatible_input_cost_per_1k_tokens
        self._output_cost = settings.openai_compatible_output_cost_per_1k_tokens
        self._timeout = settings.provider_timeout_seconds
        self._client = http_client
        self._resilience = resilience or ProviderResilience(
            max_attempts=settings.provider_max_attempts,
            failure_threshold=settings.provider_circuit_failure_threshold,
            reset_seconds=settings.provider_circuit_reset_seconds,
        )
        self.pii_allowed = settings.openai_compatible_pii_allowed

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Generate text or strict structured output from a compatible model."""
        model_name = self._models.get(request.tier)
        if model_name is None:
            raise ProviderConfigurationError("No compatible model is configured for this tier.")
        payload: dict[str, object] = {
            "model": model_name,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.output_model is not None:
            payload["response_format"] = strict_response_format(request.output_model)
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        endpoint = (
            f"{self._base_url}/chat/completions"
            if self._base_url.endswith("/v1")
            else f"{self._base_url}/v1/chat/completions"
        )
        response = await self._resilience.post_json(
            self._client,
            endpoint,
            headers,
            payload,
            self._timeout,
        )
        try:
            response_payload = response.json()
        except ValueError:
            raise ProviderResponseError("The model provider returned invalid JSON.") from None
        return parse_chat_completion(
            response_payload,
            request,
            self.name,
            model_name,
            self._input_cost,
            self._output_cost,
        )
