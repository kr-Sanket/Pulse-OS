import json
import logging

import pytest
from app.core.logging import JsonFormatter, request_id_var
from fastapi.testclient import TestClient


def test_json_formatter_emits_required_fields() -> None:
    record = logging.makeLogRecord(
        {
            "name": "pulseos.access",
            "levelname": "INFO",
            "levelno": logging.INFO,
            "msg": "request completed",
            "method": "GET",
            "path": "/health",
            "status_code": 200,
            "duration_ms": 1.23,
        }
    )
    token = request_id_var.set("rid-test-1")
    try:
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)

    assert payload["timestamp"]
    assert payload["level"] == "INFO"
    assert payload["message"] == "request completed"
    assert payload["request_id"] == "rid-test-1"
    assert payload["method"] == "GET"
    assert payload["path"] == "/health"
    assert payload["status_code"] == 200
    assert payload["duration_ms"] == 1.23


def test_access_log_records_endpoint_status_and_duration(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="pulseos.access"):
        client.get("/health", headers={"X-Request-Id": "rid-access-1"})

    record = next(r for r in caplog.records if r.name == "pulseos.access")
    assert getattr(record, "method", None) == "GET"
    assert getattr(record, "path", None) == "/health"
    assert getattr(record, "status_code", None) == 200
    assert isinstance(getattr(record, "duration_ms", None), float)
