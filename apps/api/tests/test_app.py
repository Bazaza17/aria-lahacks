"""Smoke tests for the HTTP surface. No network or API keys needed."""

import json

import pytest
from fastapi.testclient import TestClient

from app.agent import streaming
from app.main import app
from app.tools.executors import execute_tool

client = TestClient(app)


def test_health() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_root_reports_ok() -> None:
    assert client.get("/").json()["status"] == "ok"


@pytest.mark.parametrize(
    ("origin", "allowed"),
    [
        ("http://localhost:3000", True),
        ("https://my-preview.vercel.app", True),
        ("https://evil.example.com", False),
    ],
)
def test_cors_origins(origin: str, allowed: bool) -> None:
    res = client.options(
        "/health",
        headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
    )
    assert (res.headers.get("access-control-allow-origin") == origin) is allowed


def test_replay_without_cache_backend_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    res = client.post("/agent/replay/does-not-exist")
    assert res.status_code == 503


def test_sse_event_format() -> None:
    raw = streaming.reasoning("hello")
    assert raw.endswith("\n\n")
    event_line, data_line, *_ = raw.split("\n")
    assert event_line == "event: reasoning"
    assert json.loads(data_line.removeprefix("data: ")) == {"text": "hello"}


async def test_unknown_tool_is_reported_not_raised() -> None:
    assert await execute_tool("no_such_tool", {}) == "Unknown tool: no_such_tool"
