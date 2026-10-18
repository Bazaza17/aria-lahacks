"""Smoke tests for the HTTP surface. No network or API keys needed."""

import os

import dotenv
import pytest
from fastapi.testclient import TestClient

# app.main calls load_dotenv(override=True) on import. Make that a no-op and drop any
# SENTRY_DSN so the tests never read the real apps/api/.env or send events to Sentry.
dotenv.load_dotenv = lambda *args, **kwargs: False
os.environ.pop("SENTRY_DSN", None)

from app.main import app  # noqa: E402

# Not entered as a context manager on purpose: the lifespan (the CREAO runtime and its
# database) never starts, so these tests open no database connection.
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
