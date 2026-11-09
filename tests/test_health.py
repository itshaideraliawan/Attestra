from fastapi.testclient import TestClient

from attestra.app import create_app
from attestra.settings import Settings


def test_health_routes_return_ok_and_request_id() -> None:
    client = TestClient(create_app(Settings()))

    health_response = client.get("/healthz")
    ready_response = client.get("/readyz", headers={"X-Request-Id": "test-request"})

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert health_response.headers["x-request-id"]
    assert ready_response.status_code == 200
    assert ready_response.json() == {"status": "ok"}
    assert ready_response.headers["x-request-id"] == "test-request"
