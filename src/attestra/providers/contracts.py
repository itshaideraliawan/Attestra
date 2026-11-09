"""Shared model provider request, response, and error types."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel, ValidationError

_UNSUPPORTED_SCHEMA_KEYWORDS = {
    "contains",
    "default",
    "format",
    "maxItems",
    "maxLength",
    "maxProperties",
    "maxContains",
    "maximum",
    "minContains",
    "minItems",
    "minLength",
    "minProperties",
    "minimum",
    "multipleOf",
    "pattern",
    "patternProperties",
    "propertyNames",
    "uniqueItems",
    "unevaluatedItems",
    "unevaluatedProperties",
}


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """Prompt and output requirements for one model call."""

    prompt: str
    tier: str = "fast"
    output_model: type[BaseModel] | None = None


@dataclass(frozen=True, slots=True)
class ModelUsage:
    """Token usage reported by a provider."""

    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("Token counts cannot be negative")


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """Text or parsed structured output with usage and cost metadata."""

    provider: str
    model: str
    text: str
    usage: ModelUsage | None
    cost_usd: Decimal | None
    structured: BaseModel | None = None


class ModelProvider(Protocol):
    """Contract implemented by model providers."""

    name: str
    pii_allowed: bool

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Generate text or strict structured output for a prompt."""


class ProviderError(Exception):
    """Base error for model provider failures."""


class ProviderConfigurationError(ProviderError):
    """Raised when required provider configuration is missing or invalid."""


class ProviderResponseError(ProviderError):
    """Raised when a provider response cannot be safely interpreted."""


class ProviderRefusalError(ProviderError):
    """Raised when a provider refuses the request."""


class ProviderRequestError(ProviderError):
    """Raised for non-retryable request failures without exposing response content."""


class RetryableProviderError(ProviderError):
    """Raised for transient provider failures that may succeed on retry."""

    def __init__(self, message: str, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class CircuitOpenError(ProviderError):
    """Raised while a provider circuit breaker is open."""


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a strict JSON Schema compatible with structured output APIs."""
    schema = model.model_json_schema()

    def normalize(value: Any) -> None:
        if isinstance(value, dict):
            for keyword in _UNSUPPORTED_SCHEMA_KEYWORDS:
                value.pop(keyword, None)
            if value.get("type") == "object":
                properties = value.setdefault("properties", {})
            else:
                properties = value.get("properties")
            if isinstance(properties, dict):
                value["additionalProperties"] = False
                value["required"] = list(properties)
            for nested in value.values():
                normalize(nested)
        elif isinstance(value, list):
            for nested in value:
                normalize(nested)

    normalize(schema)
    return schema


def strict_response_format(model: type[BaseModel]) -> dict[str, object]:
    """Build the structured output format sent to chat completion APIs."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": model.__name__,
            "strict": True,
            "schema": strict_json_schema(model),
        },
    }


def parse_chat_completion(
    payload: Any,
    request: ModelRequest,
    provider: str,
    model_name: str,
    input_cost_per_1k_tokens: Decimal | None,
    output_cost_per_1k_tokens: Decimal | None,
) -> ModelResponse:
    """Validate a chat completion response and capture usage metadata."""
    if not isinstance(payload, dict):
        raise ProviderResponseError("The model provider returned an invalid response.")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProviderResponseError("The model provider returned no completion choice.")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ProviderResponseError("The model provider returned an invalid completion message.")
    if message.get("refusal"):
        raise ProviderRefusalError("The model provider refused the request.")
    text = message.get("content")
    if not isinstance(text, str):
        raise ProviderResponseError("The model provider returned no text content.")

    structured: BaseModel | None = None
    if request.output_model is not None:
        try:
            structured = request.output_model.model_validate_json(text)
        except (ValidationError, ValueError):
            raise ProviderResponseError(
                "The model provider returned output that did not match the requested schema."
            ) from None

    usage_payload = payload.get("usage")
    usage = _parse_usage(usage_payload)
    cost = _calculate_cost(
        usage,
        input_cost_per_1k_tokens,
        output_cost_per_1k_tokens,
    )
    return ModelResponse(
        provider=provider,
        model=model_name,
        text=text,
        usage=usage,
        cost_usd=cost,
        structured=structured,
    )


def _parse_usage(payload: Any) -> ModelUsage | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ProviderResponseError("The model provider returned invalid usage metadata.")
    input_tokens = payload.get("prompt_tokens")
    output_tokens = payload.get("completion_tokens")
    if (
        isinstance(input_tokens, bool)
        or not isinstance(input_tokens, int)
        or isinstance(output_tokens, bool)
        or not isinstance(output_tokens, int)
        or input_tokens < 0
        or output_tokens < 0
    ):
        raise ProviderResponseError("The model provider returned invalid usage metadata.")
    return ModelUsage(input_tokens=input_tokens, output_tokens=output_tokens)


def _calculate_cost(
    usage: ModelUsage | None,
    input_cost_per_1k_tokens: Decimal | None,
    output_cost_per_1k_tokens: Decimal | None,
) -> Decimal | None:
    if usage is None or input_cost_per_1k_tokens is None or output_cost_per_1k_tokens is None:
        return None
    total = (
        Decimal(usage.input_tokens) * input_cost_per_1k_tokens
        + Decimal(usage.output_tokens) * output_cost_per_1k_tokens
    ) / Decimal(1000)
    return total.quantize(Decimal("0.00000001"))
