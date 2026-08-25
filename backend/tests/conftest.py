from collections.abc import Iterator

import pytest
from app.main import create_app
from app.modules.auth.dependencies import get_auth_provider
from app.modules.auth.fake import FakeAuthProvider
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app() -> FastAPI:
    return create_app()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    # Context manager runs the lifespan (engine/session factory on app.state).
    # The engine connects lazily, so no real database is needed here.
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def fake_auth(app: FastAPI) -> FakeAuthProvider:
    # Replaces FirebaseAuthProvider for the whole app: tests never contact Google.
    provider = FakeAuthProvider()
    app.dependency_overrides[get_auth_provider] = lambda: provider
    return provider
