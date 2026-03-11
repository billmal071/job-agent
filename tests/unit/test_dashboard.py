"""Unit tests for the Flask dashboard app factory and basic routes."""

from __future__ import annotations

import pytest
from flask import Flask

from job_agent.config import Settings
from job_agent.dashboard.app import create_app
from job_agent.db.models import Base, Job, MatchResult, Platform, JobStatus
from job_agent.db.session import get_engine, get_session, reset_engine


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


def test_jobs_page_shows_insights():
    """Jobs list page shows matched skills, missing skills, red flags, and reasoning."""
    reset_engine()
    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
    )
    engine = get_engine(settings)
    Base.metadata.create_all(engine)

    session = get_session(settings)
    job = Job(
        external_id="insight-1",
        platform=Platform.LINKEDIN,
        title="Python Developer",
        company="InsightCo",
        status=JobStatus.MATCHED,
    )
    session.add(job)
    session.flush()

    match = MatchResult(
        job_id=job.id,
        score=0.85,
        reasoning="Strong Python background aligns well",
        matched_skills='["Python", "Flask", "SQL"]',
        missing_skills='["Kubernetes"]',
        red_flags='["Relocation required"]',
    )
    session.add(match)
    session.commit()

    app = create_app(settings)
    app.config["TESTING"] = True

    with app.test_client() as client:
        resp = client.get("/jobs/")
        html = resp.data.decode()
        assert resp.status_code == 200
        assert "Python" in html
        assert "Flask" in html
        assert "Kubernetes" in html
        assert "Relocation required" in html
        assert "Strong Python background" in html

    session.close()
    reset_engine()


def test_bulk_approve_selected_jobs():
    """Bulk approve endpoint approves multiple jobs."""
    reset_engine()
    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
    )
    engine = get_engine(settings)
    Base.metadata.create_all(engine)

    session = get_session(settings)
    jobs = []
    for i in range(3):
        job = Job(
            external_id=f"bulk-{i}",
            platform=Platform.LINKEDIN,
            title=f"Job {i}",
            company="BulkCo",
            status=JobStatus.QUEUED,
        )
        session.add(job)
        jobs.append(job)
    session.commit()
    job_ids = [j.id for j in jobs]

    app = create_app(settings)
    app.config["TESTING"] = True

    with app.test_client() as client:
        resp = client.post(
            "/queue/bulk-action",
            json={"action": "approve", "job_ids": job_ids[:2]},
        )
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert "2 jobs" in data["message"]

    # Verify statuses changed
    session2 = get_session(settings)
    approved = session2.get(Job, job_ids[0])
    still_queued = session2.get(Job, job_ids[2])
    assert approved.status == JobStatus.APPROVED
    assert still_queued.status == JobStatus.QUEUED
    session2.close()
    reset_engine()


def test_bulk_reject_selected_jobs():
    """Bulk reject endpoint rejects multiple jobs."""
    reset_engine()
    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
    )
    engine = get_engine(settings)
    Base.metadata.create_all(engine)

    session = get_session(settings)
    job = Job(
        external_id="bulk-rej",
        platform=Platform.LINKEDIN,
        title="Reject Me",
        company="RejCo",
        status=JobStatus.QUEUED,
    )
    session.add(job)
    session.commit()

    app = create_app(settings)
    app.config["TESTING"] = True

    with app.test_client() as client:
        resp = client.post(
            "/queue/bulk-action",
            json={"action": "reject", "job_ids": [job.id]},
        )
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["ok"] is True
        assert "Rejected 1 job" in data["message"]

    session.close()
    reset_engine()


def test_bulk_action_invalid_action():
    """Bulk action with invalid action returns 400."""
    reset_engine()
    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
    )
    engine = get_engine(settings)
    Base.metadata.create_all(engine)

    app = create_app(settings)
    app.config["TESTING"] = True

    with app.test_client() as client:
        resp = client.post(
            "/queue/bulk-action",
            json={"action": "delete", "job_ids": [1]},
        )
        assert resp.status_code == 400

    reset_engine()
