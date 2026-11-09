"""FastAPI application factory and basic health routes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from attestra.database import create_engine, create_session_factory
from attestra.logging import configure_logging
from attestra.middleware import RequestIdMiddleware
from attestra.policies import TenantPolicyProvider
from attestra.problems import ProblemException, problem_response
from attestra.settings import Settings, get_settings
from attestra.telemetry import configure_telemetry

logger = structlog.get_logger(__name__)


def create_app(
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> FastAPI:
    """Create a configured Attestra application."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    if session_factory is None:
        engine = create_engine(resolved_settings)
        resolved_session_factory = create_session_factory(engine)
    else:
        engine = None
        resolved_session_factory = session_factory

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(timeout=5.0) as client:
            app.state.entra_http_client = client
            app.state.session_factory = resolved_session_factory
            app.state.tenant_policy_provider = TenantPolicyProvider(
                resolved_session_factory,
                cache_seconds=resolved_settings.tenant_policy_cache_seconds,
            )
            try:
                yield
            finally:
                if engine is not None:
                    await engine.dispose()

    app = FastAPI(title=resolved_settings.app_name, lifespan=lifespan)
    app.state.settings = resolved_settings
    app.add_middleware(RequestIdMiddleware)

    @app.exception_handler(ProblemException)
    async def handle_problem_exception(
        request: Request, exception: ProblemException
    ) -> JSONResponse:
        return problem_response(
            request,
            status_code=exception.status_code,
            title=exception.title,
            detail=exception.detail,
            headers=exception.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exception: RequestValidationError
    ) -> JSONResponse:
        safe_errors = [
            {
                "location": [str(part) for part in error["loc"]],
                "message": error["msg"],
                "code": error["type"],
            }
            for error in exception.errors()
        ]
        return problem_response(
            request,
            status_code=422,
            title="Invalid request",
            detail="The request did not meet the required format.",
            extensions={"errors": safe_errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, exception: StarletteHTTPException
    ) -> JSONResponse:
        title = {
            401: "Unauthorized",
            403: "Forbidden",
            404: "Not Found",
            405: "Method Not Allowed",
        }.get(exception.status_code, "Request failed")
        return problem_response(
            request,
            status_code=exception.status_code,
            title=title,
            detail="The request could not be completed.",
            headers=exception.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exception: Exception) -> JSONResponse:
        logger.error(
            "Unhandled request error",
            request_id=getattr(request.state, "request_id", None),
            error_type=type(exception).__name__,
        )
        return problem_response(
            request,
            status_code=500,
            title="Internal Server Error",
            detail="An internal error occurred.",
        )

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"], response_model=None)
    async def readyz(request: Request) -> JSONResponse | dict[str, str]:
        session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
        try:
            async with session_factory() as session:
                await session.execute(text("SELECT 1"))
        except (OSError, SQLAlchemyError):
            return problem_response(
                request,
                status_code=503,
                title="Service Unavailable",
                detail="A required dependency is unavailable.",
            )
        return {"status": "ok"}

    configure_telemetry(app)

    return app
