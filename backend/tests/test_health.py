from app.core.health import database_ready, redis_ready
from fastapi import FastAPI
from fastapi.testclient import TestClient


async def _check_passes() -> bool:
    return True


async def _check_fails() -> bool:
    return False


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_unknown_route_is_404(client: TestClient) -> None:
    assert client.get("/nope").status_code == 404


def test_ready_when_all_dependencies_answer(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[database_ready] = _check_passes
    app.dependency_overrides[redis_ready] = _check_passes
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}


def test_ready_is_503_when_database_is_down(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[database_ready] = _check_fails
    app.dependency_overrides[redis_ready] = _check_passes
    response = client.get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unready"
    assert body["checks"] == {"database": "failed", "redis": "ok"}


def test_ready_is_503_when_redis_is_down(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[database_ready] = _check_passes
    app.dependency_overrides[redis_ready] = _check_fails
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["redis"] == "failed"
