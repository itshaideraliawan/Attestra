import anyio
from sqlalchemy.ext.asyncio import create_async_engine

from attestra.database import create_session_factory
from attestra.models import Base, TenantPolicy
from attestra.policies import TenantPolicyProvider


def test_policy_provider_caches_per_tenant_and_expires() -> None:
    async def verify_cache() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            execution_options={"schema_translate_map": {"attestra": None}},
        )
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            session_factory = create_session_factory(engine)
            async with session_factory() as session:
                session.add(TenantPolicy(tenant_id="tenant-a", settings={"enabled": True}))
                await session.commit()
            provider = TenantPolicyProvider(session_factory, cache_seconds=0.02)
            first = await provider.get("tenant-a")
            async with session_factory() as session:
                policy = await session.get(TenantPolicy, "tenant-a")
                assert policy is not None
                policy.settings = {"enabled": False}
                await session.commit()
            cached = await provider.get("tenant-a")
            assert first is not None and cached is not None
            assert cached.settings == {"enabled": True}
            assert await provider.get("tenant-b") is None
            await anyio.sleep(0.03)
            refreshed = await provider.get("tenant-a")
            assert refreshed is not None
            assert refreshed.settings == {"enabled": False}
        finally:
            await engine.dispose()

    anyio.run(verify_cache)
