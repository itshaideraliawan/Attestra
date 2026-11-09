"""FastAPI application factory and basic health routes."""

from fastapi import FastAPI

from attestra.logging import configure_logging
from attestra.middleware import RequestIdMiddleware
from attestra.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a configured Attestra application."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    app = FastAPI(title=resolved_settings.app_name)
    app.add_middleware(RequestIdMiddleware)

    @app.get("/healthz", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["health"])
    async def readyz() -> dict[str, str]:
        return {"status": "ok"}

    return app
