"""Smoke test — boots the FastAPI app and round-trips /chat through the stub agent."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Make backend/ importable when run from repo root.
_BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(_BACKEND))

from main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_chat_echoes_when_cuga_unreachable(client):
    r = client.post("/chat", json={"message": "hello"})
    assert r.status_code == 200
    body = r.json()
    # Stub falls back to echo when no cuga is running on CUGA_URL.
    assert "hello" in body["response"]
    assert body["thread_id"] == "default"


def test_tools_endpoint_returns_list(client):
    # With no adapter running, the discovery sync writes no rows. /tools
    # should still respond with an empty list rather than 500.
    r = client.get("/tools")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_health_includes_tool_count(client):
    r = client.get("/health")
    body = r.json()
    assert "tools_registered" in body
    assert isinstance(body["tools_registered"], int)
