"""Fixture-driven fake provider for deterministic tests and local wiring."""

from collections.abc import Sequence

from pydantic import ValidationError

from attestra.providers.contracts import (
    ModelRequest,
    ModelResponse,
    ProviderResponseError,
)


class FakeProvider:
    """Return preconfigured responses without making network requests."""

    name = "fake"

    def __init__(
        self,
        responses: Sequence[ModelResponse],
        pii_allowed: bool = False,
    ) -> None:
        self._responses = tuple(responses)
        self._index = 0
        self.pii_allowed = pii_allowed

    async def complete(self, request: ModelRequest) -> ModelResponse:
        """Return the next fixture and validate it against the requested model."""
        if self._index >= len(self._responses):
            raise ProviderResponseError("The fake provider has no response fixture remaining.")
        response = self._responses[self._index]
        self._index += 1

        structured = response.structured
        if request.output_model is not None:
            if structured is not None:
                try:
                    structured = request.output_model.model_validate(structured.model_dump())
                except ValidationError:
                    raise ProviderResponseError(
                        "The fake fixture did not match the requested schema."
                    ) from None
            else:
                try:
                    structured = request.output_model.model_validate_json(response.text)
                except (ValidationError, ValueError):
                    raise ProviderResponseError(
                        "The fake fixture did not match the requested schema."
                    ) from None

        return ModelResponse(
            provider=self.name,
            model=response.model,
            text=response.text,
            usage=response.usage,
            cost_usd=response.cost_usd,
            structured=structured,
        )
