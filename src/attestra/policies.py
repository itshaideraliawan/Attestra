"""Tenant policy retrieval with a bounded in-memory TTL cache."""

import asyncio
import time
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attestra.models import TenantPolicy
from attestra.repositories import TenantPolicyRepository


@dataclass(frozen=True, slots=True)
class CachedPolicy:
    policy: TenantPolicy | None
    expires_at: float


class TenantPolicyProvider:
    """Load tenant policies and cache results briefly to reduce database reads."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cache_seconds: float = 30.0,
        max_entries: int = 10_000,
    ) -> None:
        if cache_seconds <= 0:
            raise ValueError("cache_seconds must be positive")
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._session_factory = session_factory
        self._cache_seconds = cache_seconds
        self._max_entries = max_entries
        self._cache: dict[str, CachedPolicy] = {}
        self._lock = asyncio.Lock()

    async def get(self, tenant_id: str) -> TenantPolicy | None:
        """Return a tenant policy, loading and caching it on a miss."""
        now = time.monotonic()
        cached = self._cache.get(tenant_id)
        if cached and cached.expires_at > now:
            return cached.policy

        async with self._lock:
            now = time.monotonic()
            cached = self._cache.get(tenant_id)
            if cached and cached.expires_at > now:
                return cached.policy
            async with self._session_factory() as session:
                policy = await TenantPolicyRepository(session).get(tenant_id)
            if len(self._cache) >= self._max_entries:
                expired_key = next(
                    (key for key, entry in self._cache.items() if entry.expires_at <= now), None
                )
                self._cache.pop(expired_key or next(iter(self._cache)), None)
            self._cache[tenant_id] = CachedPolicy(policy, now + self._cache_seconds)
            return policy
