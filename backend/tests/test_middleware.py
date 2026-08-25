import uuid

from fastapi.testclient import TestClient


def test_request_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/health")
    request_id = response.headers.get("x-request-id")
    assert request_id
    uuid.UUID(request_id)  # generated ids are UUIDs


def test_request_id_is_echoed_when_provided(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Request-Id": "req-abc-123"})
    assert response.headers["x-request-id"] == "req-abc-123"


def test_request_id_present_on_error_responses(client: TestClient) -> None:
    response = client.get("/nope", headers={"X-Request-Id": "req-err-1"})
    assert response.status_code == 404
    assert response.headers["x-request-id"] == "req-err-1"
