"""OpenTelemetry setup for HTTP requests."""

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider


def configure_telemetry(app: FastAPI) -> None:
    """Instrument the application with W3C trace context propagation."""
    provider = TracerProvider(resource=Resource.create({"service.name": "attestra"}))
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    app.state.tracer_provider = provider
    app.state.tracer = provider.get_tracer("attestra")
