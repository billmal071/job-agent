"""Tests for application retry route."""

from __future__ import annotations

from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from job_agent.config import Settings
from job_agent.dashboard.app import create_app
from job_agent.db.models import (
    Application,
    ApplicationStatus,
    Base,
    Job,
    JobStatus,
    Platform,
)
from job_agent.db.session import reset_engine


def _setup_app_with_failed_application():
    """Create Flask app with a failed application in the database."""
    reset_engine()

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()

    job = Job(
        external_id="retry-123",
        platform=Platform.LINKEDIN,
        title="Python Developer",
        company="RetryInc",
        status=JobStatus.APPLY_FAILED,
    )
    session.add(job)
    session.flush()

    application = Application(
        job_id=job.id,
        status=ApplicationStatus.FAILED,
        error_message="Timeout during submission",
    )
    session.add(application)
    session.commit()

    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test-secret",
    )

    return engine, session, job.id, application.id, settings


def test_retry_resets_failed_application():
    """Retry resets application to PENDING and job to APPROVED."""
    engine, session, job_id, app_id, settings = _setup_app_with_failed_application()
    try:
        with patch(
            "job_agent.dashboard.routes.applications.get_session",
            return_value=session,
        ):
            app = create_app(settings)
            app.config["TESTING"] = True
            with app.test_client() as client:
                resp = client.post(f"/applications/retry/{app_id}")
                assert resp.status_code == 200
                assert b"Retrying" in resp.data

                # Verify state changes
                application = session.get(Application, app_id)
                assert application.status == ApplicationStatus.PENDING
                assert application.error_message == ""
                assert application.applied_at is None

                job = session.get(Job, job_id)
                assert job.status == JobStatus.APPROVED
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_retry_rejects_non_failed():
    """Cannot retry an application that isn't failed/withdrawn."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()

    job = Job(
        external_id="ok-456",
        platform=Platform.INDEED,
        title="Data Engineer",
        company="OkCorp",
        status=JobStatus.APPLIED,
    )
    session.add(job)
    session.flush()

    application = Application(
        job_id=job.id,
        status=ApplicationStatus.SUBMITTED,
    )
    session.add(application)
    session.commit()
    app_id = application.id

    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test-secret",
    )

    try:
        with patch(
            "job_agent.dashboard.routes.applications.get_session",
            return_value=session,
        ):
            app = create_app(settings)
            app.config["TESTING"] = True
            with app.test_client() as client:
                resp = client.post(f"/applications/retry/{app_id}")
                assert resp.status_code == 400
                assert b"Cannot retry" in resp.data
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_retry_not_found():
    """Retry returns 404 for non-existent application."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()

    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test-secret",
    )

    try:
        with patch(
            "job_agent.dashboard.routes.applications.get_session",
            return_value=session,
        ):
            app = create_app(settings)
            app.config["TESTING"] = True
            with app.test_client() as client:
                resp = client.post("/applications/retry/9999")
                assert resp.status_code == 404
                assert b"not found" in resp.data
    finally:
        session.close()
        engine.dispose()
        reset_engine()
