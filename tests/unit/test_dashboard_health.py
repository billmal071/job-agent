"""Tests for dashboard health endpoint."""

from __future__ import annotations

from job_agent.config import Settings
from job_agent.dashboard.app import create_app


def test_health_endpoint():
    settings = Settings()
    app = create_app(settings)
    client = app.test_client()
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert "version" in data
