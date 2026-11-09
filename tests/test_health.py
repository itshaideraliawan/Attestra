import secrets

from pydantic import SecretStr
from starlette.testclient import TestClient

from attestra.app import create_app
from attestra.settings import Settings


def test_health_routes_return_ok_and_request_id() -> None:
    client = TestClient(create_app(Settings(dev_api_key=SecretStr(secrets.token_urlsafe(32)))))

    health_response = client.get("/healthz")
    supplied_request_id = "fe67474d-20c1-4caa-a246-c220de3b829b"
    ready_response = client.get("/readyz", headers={"X-Request-Id": supplied_request_id})
    unsafe_request_id_response = client.get(
        "/healthz",
        headers={"X-Request-Id": "unsafe request id"},
    )

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert health_response.headers["x-request-id"]
    assert ready_response.status_code == 200
    assert ready_response.json() == {"status": "ok"}
    assert ready_response.headers["x-request-id"] == supplied_request_id
    assert unsafe_request_id_response.headers["x-request-id"] != "unsafe request id"
