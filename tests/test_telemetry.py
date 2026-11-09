import secrets

from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from pydantic import SecretStr
from starlette.testclient import TestClient

from attestra.app import create_app
from attestra.settings import Settings


def test_traceparent_is_propagated_to_server_span() -> None:
    app = create_app(Settings(dev_api_key=SecretStr(secrets.token_urlsafe(32)), _env_file=None))
    exporter = InMemorySpanExporter()
    app.state.tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))

    response = TestClient(app).get(
        "/healthz",
        headers={"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"},
    )

    spans = [span for span in exporter.get_finished_spans() if span.kind == SpanKind.SERVER]
    assert response.status_code == 200
    assert len(spans) == 1
    assert spans[0].context.trace_id == int("4bf92f3577b34da6a3ce929d0e0e4736", 16)
