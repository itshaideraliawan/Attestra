from uuid import UUID

import anyio
from sqlalchemy.ext.asyncio import create_async_engine

from attestra.database import create_session_factory
from attestra.models import AiRun, Base
from attestra.repositories import TenantRepository


def test_ai_run_repository_scopes_reads_and_writes_by_tenant() -> None:
    async def verify_isolation() -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            execution_options={"schema_translate_map": {"attestra": None}},
        )
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            session_factory = create_session_factory(engine)
            async with session_factory() as session:
                repository = TenantRepository(session, AiRun)
                first = await repository.create(
                    "tenant-a", {"status": "completed", "metadata_json": {}}
                )
                second = await repository.create(
                    "tenant-b", {"status": "completed", "metadata_json": {}}
                )
                await session.commit()
                assert await repository.get("tenant-a", first.id) == first
                assert await repository.get("tenant-b", first.id) is None
                assert [run.tenant_id for run in await repository.list("tenant-a")] == ["tenant-a"]
                assert await repository.get("tenant-a", second.id) is None
                assert isinstance(first.id, UUID)
        finally:
            await engine.dispose()

    anyio.run(verify_isolation)
