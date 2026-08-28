"""CORS behavior: the browser portals may call the API; unknown origins may not."""

from fastapi.testclient import TestClient

PORTAL_ORIGIN = "http://localhost:5173"


def _preflight(client: TestClient, origin: str) -> dict[str, str | None]:
    response = client.options(
        "/api/v1/patients/me",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    return {
        "allow_origin": response.headers.get("access-control-allow-origin"),
        "allow_headers": response.headers.get("access-control-allow-headers"),
    }


def test_portal_origin_is_allowed(client: TestClient) -> None:
    result = _preflight(client, PORTAL_ORIGIN)
    assert result["allow_origin"] == PORTAL_ORIGIN
    assert "authorization" in (result["allow_headers"] or "").lower()


def test_unknown_origin_is_not_allowed(client: TestClient) -> None:
    assert _preflight(client, "https://evil.example")["allow_origin"] is None


def test_request_id_is_exposed_to_browsers(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": PORTAL_ORIGIN})
    assert "x-request-id" in response.headers.get("access-control-expose-headers", "").lower()
