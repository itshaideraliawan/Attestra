from fastapi import Body
from pydantic import SecretStr
from starlette.testclient import TestClient

from attestra.app import create_app
from attestra.settings import Settings


def test_validation_problem_does_not_echo_submitted_value() -> None:
    app = create_app(Settings(dev_api_key=SecretStr("x" * 32), _env_file=None))

    @app.post("/invalid")
    async def invalid(value: int = Body(embed=True)) -> dict[str, int]:
        return {"value": value}

    response = TestClient(app).post("/invalid", json={"value": "private-value"})

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "private-value" not in response.text


def test_not_found_uses_problem_json() -> None:
    app = create_app(Settings(dev_api_key=SecretStr("x" * 32), _env_file=None))

    response = TestClient(app).get("/missing")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["title"] == "Not Found"
