import anyio
import httpx
import pytest
import respx

from attestra.providers.contracts import (
    CircuitOpenError,
    ProviderRequestError,
    RetryableProviderError,
)
from attestra.providers.resilience import ProviderResilience


@pytest.mark.parametrize("status_code", [429, 503])
def test_transient_status_retries_and_honors_retry_after(
    respx_mock: respx.Router,
    status_code: int,
) -> None:
    route = respx_mock.post("https://provider.example/completions").mock(
        side_effect=[
            httpx.Response(status_code, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    async def send() -> httpx.Response:
        async with httpx.AsyncClient() as client:
            return await ProviderResilience(max_attempts=2).post_json(
                client,
                "https://provider.example/completions",
                {},
                {"prompt": "redacted"},
                2.0,
            )

    response = anyio.run(send)
    assert response.status_code == 200
    assert route.call_count == 2


def test_timeout_retries_before_returning_success(respx_mock: respx.Router) -> None:
    route = respx_mock.post("https://provider.example/completions").mock(
        side_effect=[httpx.ReadTimeout("timeout"), httpx.Response(200)]
    )

    async def send() -> httpx.Response:
        async with httpx.AsyncClient() as client:
            return await ProviderResilience(max_attempts=2).post_json(
                client,
                "https://provider.example/completions",
                {},
                {"prompt": "redacted"},
                2.0,
            )

    response = anyio.run(send)
    assert response.status_code == 200
    assert route.call_count == 2


def test_non_retryable_status_is_not_retried(respx_mock: respx.Router) -> None:
    route = respx_mock.post("https://provider.example/completions").mock(
        return_value=httpx.Response(400)
    )

    async def send() -> None:
        async with httpx.AsyncClient() as client:
            await ProviderResilience(max_attempts=3).post_json(
                client,
                "https://provider.example/completions",
                {},
                {"prompt": "redacted"},
                2.0,
            )

    with pytest.raises(ProviderRequestError):
        anyio.run(send)
    assert route.call_count == 1


def test_circuit_opens_after_retry_exhaustion() -> None:
    resilience = ProviderResilience(max_attempts=1, failure_threshold=1)

    async def fail() -> None:
        raise RetryableProviderError("temporary failure")

    async def verify() -> None:
        with pytest.raises(RetryableProviderError):
            await resilience.call(fail)
        with pytest.raises(CircuitOpenError):
            await resilience.call(fail)

    anyio.run(verify)
