from app.main import create_app
from fastapi.testclient import TestClient


def test_health_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_unknown_route_is_404() -> None:
    client = TestClient(create_app())
    assert client.get("/nope").status_code == 404
