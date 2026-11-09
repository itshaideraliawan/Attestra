from collections.abc import Iterator

import anyio
import docker
import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.community.postgres import PostgresContainer

from attestra.database import create_session_factory
from attestra.models import AiRun, Base
from attestra.repositories import TenantRepository


@pytest.fixture(scope="module")
def postgres_url() -> Iterator[str]:
    try:
        client = docker.from_env()
        client.ping()
    except docker.errors.DockerException as error:
        pytest.skip(f"Docker is unavailable: {error.__class__.__name__}")
    container = PostgresContainer("postgres:16", driver="asyncpg")
    try:
        container.start()
        yield container.get_connection_url()
    finally:
        container.stop()


def test_postgres_repository_prevents_cross_tenant_reads(postgres_url: str) -> None:
    async def verify_isolation() -> None:
        engine = create_async_engine(postgres_url, pool_pre_ping=True)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            session_factory = create_session_factory(engine)
            async with session_factory() as session:
                repository = TenantRepository(session, AiRun)
                run = await repository.create(
                    "tenant-a", {"status": "completed", "metadata_json": {}}
                )
                await session.commit()
                assert await repository.get("tenant-a", run.id) == run
                assert await repository.get("tenant-b", run.id) is None
        finally:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.drop_all)
            await engine.dispose()

    anyio.run(verify_isolation)
