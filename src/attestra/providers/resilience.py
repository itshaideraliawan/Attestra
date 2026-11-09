"""Retry and circuit-breaker behavior for model provider requests."""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from typing import TypeVar, cast

import httpx
from tenacity import AsyncRetrying, RetryCallState, retry_if_exception_type, stop_after_attempt
from tenacity.wait import wait_base, wait_random_exponential

from attestra.providers.contracts import (
    CircuitOpenError,
    ProviderRequestError,
    RetryableProviderError,
)

T = TypeVar("T")


class RetryAfterWait(wait_base):
    """Use server Retry-After hints or jittered exponential backoff."""

    def __init__(self, max_retry_after_seconds: float = 120.0) -> None:
        self._max_retry_after_seconds = max_retry_after_seconds
        self._fallback = wait_random_exponential(multiplier=0.1, max=2.0)

    def __call__(self, retry_state: RetryCallState) -> float:
        exception = retry_state.outcome.exception() if retry_state.outcome else None
        if isinstance(exception, RetryableProviderError):
            retry_after = exception.retry_after_seconds
            if retry_after is not None:
                return min(max(retry_after, 0.0), self._max_retry_after_seconds)
        return self._fallback(retry_state)


class ProviderCircuitBreaker:
    """Open after repeated transient failures and recover after a cooldown."""

    def __init__(self, failure_threshold: int = 5, reset_seconds: float = 30.0) -> None:
        if failure_threshold < 1 or reset_seconds <= 0:
            raise ValueError("Circuit breaker threshold and reset duration must be positive")
        self._failure_threshold = failure_threshold
        self._reset_seconds = reset_seconds
        self._failures = 0
        self._opened_at: float | None = None
        self._lock = asyncio.Lock()

    async def before_call(self) -> None:
        async with self._lock:
            if self._opened_at is None:
                return
            if asyncio.get_running_loop().time() - self._opened_at < self._reset_seconds:
                raise CircuitOpenError("Provider circuit is open")
            self._opened_at = None
            self._failures = 0

    async def record_success(self) -> None:
        async with self._lock:
            self._failures = 0
            self._opened_at = None

    async def record_failure(self) -> None:
        async with self._lock:
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._opened_at = asyncio.get_running_loop().time()


class ProviderResilience:
    """Apply bounded retries and a provider-local circuit breaker."""

    def __init__(
        self,
        max_attempts: int = 3,
        failure_threshold: int = 5,
        reset_seconds: float = 30.0,
        circuit_breaker: ProviderCircuitBreaker | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self._max_attempts = max_attempts
        self.circuit_breaker = circuit_breaker or ProviderCircuitBreaker(
            failure_threshold=failure_threshold,
            reset_seconds=reset_seconds,
        )

    async def call(self, operation: Callable[[], Awaitable[T]]) -> T:
        """Run an operation with retries for transient provider failures."""
        await self.circuit_breaker.before_call()
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            retry=retry_if_exception_type(RetryableProviderError),
            wait=RetryAfterWait(),
            reraise=True,
        )
        try:
            result = cast(T, await retrying(operation))
        except RetryableProviderError:
            await self.circuit_breaker.record_failure()
            raise
        await self.circuit_breaker.record_success()
        return result

    async def post_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        """POST JSON while classifying transient and permanent HTTP failures."""

        async def send() -> httpx.Response:
            try:
                response = await client.post(
                    url,
                    headers=headers,
                    json=payload,
                    params=params,
                    timeout=timeout_seconds,
                )
            except httpx.TimeoutException:
                raise RetryableProviderError("The model provider request timed out.") from None
            if response.status_code == 429 or response.status_code >= 500:
                raise RetryableProviderError(
                    "The model provider returned a transient error.",
                    _parse_retry_after(response.headers.get("Retry-After")),
                )
            if response.is_error:
                raise ProviderRequestError("The model provider rejected the request.")
            return response

        return await self.call(send)


def _parse_retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
        return max(seconds, 0.0) if isfinite(seconds) else None
    except ValueError:
        try:
            retry_time = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_time.tzinfo is None:
            retry_time = retry_time.replace(tzinfo=UTC)
        return max((retry_time - datetime.now(UTC)).total_seconds(), 0.0)
