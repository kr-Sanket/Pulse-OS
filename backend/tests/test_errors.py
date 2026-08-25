from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_404_is_rfc7807_problem(client: TestClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["type"] == "about:blank"
    assert body["title"] == "Not Found"
    assert body["status"] == 404
    assert body["instance"] == "/nope"


def test_validation_error_is_rfc7807_with_field_errors(app: FastAPI) -> None:
    @app.get("/validated/{item_id}")
    async def validated(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    with TestClient(app) as client:
        response = client.get("/validated/not-an-int")
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["title"] == "Validation Error"
    assert body["status"] == 422
    assert body["errors"], "field-level errors must be present"
    assert body["errors"][0]["field"] == "path.item_id"
    assert body["errors"][0]["message"]


def test_unhandled_exception_is_500_problem_without_internals(app: FastAPI) -> None:
    @app.get("/explode")
    async def explode() -> None:
        raise RuntimeError("secret internal detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/explode")
    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["title"] == "Internal Server Error"
    assert "secret internal detail" not in response.text
    # The request id survives onto the error response (set from request.state).
    assert response.headers.get("x-request-id")
