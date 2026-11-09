import anyio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.requests import Request

from attestra.database import create_session_factory, get_session


def test_session_factory_creates_async_sessions() -> None:
    async def verify_session() -> None:
        engine = create_async_engine("sqlite+aiosqlite://")
        try:
            session_factory = create_session_factory(engine)
            async with session_factory() as session:
                result = await session.execute(text("SELECT 1"))
                assert result.scalar_one() == 1
        finally:
            await engine.dispose()

    anyio.run(verify_session)


def test_session_dependency_yields_a_request_scoped_session() -> None:
    async def verify_dependency() -> None:
        engine = create_async_engine("sqlite+aiosqlite://")
        try:
            app = FastAPI()
            app.state.session_factory = create_session_factory(engine)
            request = Request({"type": "http", "app": app, "headers": []})
            session_generator = get_session(request)
            session = await anext(session_generator)
            assert session.is_active
            await session_generator.aclose()
        finally:
            await engine.dispose()

    anyio.run(verify_dependency)
