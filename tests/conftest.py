import pytest

from session import store


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Every test runs offline (no LLM, mock STT, no auth) with empty sessions."""
    for var in ("LLM_API_KEY", "API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("STT_PROVIDER", "mock")
    store.clear()
    yield
    store.clear()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from main import app
    return TestClient(app)
