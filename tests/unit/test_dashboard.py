"""Unit tests for the Flask dashboard app factory and basic routes."""

from __future__ import annotations

import pytest
from flask import Flask

from job_agent.config import Settings
from job_agent.dashboard.app import create_app
from job_agent.db.models import Base
from job_agent.db.session import get_engine, reset_engine


@pytest.fixture
def test_client():
    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
    )
    reset_engine()
    engine = get_engine(settings)
    Base.metadata.create_all(engine)

    app = create_app(settings)
    app.config["TESTING"] = True

    with app.test_client() as client:
        yield client

    reset_engine()


def test_create_app():
    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
    )
    reset_engine()
    get_engine(settings)
    Base.metadata.create_all(get_engine(settings))

    app = create_app(settings)
    assert isinstance(app, Flask)

    reset_engine()


def test_overview_page(test_client):
    response = test_client.get("/")
    assert response.status_code == 200


def test_settings_page(test_client):
    response = test_client.get("/settings/")
    assert response.status_code == 200


def test_jobs_page(test_client):
    response = test_client.get("/jobs/")
    assert response.status_code == 200
