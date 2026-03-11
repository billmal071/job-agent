"""Tests for creating Application records on failure (retryable failures)."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from job_agent.db.models import (
    Application,
    ApplicationStatus,
    Base,
    Job,
    JobStatus,
    Platform,
)
from job_agent.db.repository import ApplicationRepository
from job_agent.db.session import reset_engine


def _setup():
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    return engine, session


def test_create_failed_application():
    """ApplicationRepository.create accepts failed status and error_message."""
    engine, session = _setup()
    try:
        job = Job(
            external_id="fail-1",
            platform=Platform.LINKEDIN,
            title="Dev",
            company="FailCo",
            status=JobStatus.APPLY_FAILED,
        )
        session.add(job)
        session.flush()

        app_repo = ApplicationRepository(session)
        app = app_repo.create(
            job_id=job.id,
            resume_path="/path/to/resume.pdf",
            cover_letter_path="/path/to/cl.txt",
            status=ApplicationStatus.FAILED,
            error_message="Connection timeout during submit",
        )
        session.commit()

        assert app.status == ApplicationStatus.FAILED
        assert app.error_message == "Connection timeout during submit"
        assert app.resume_path == "/path/to/resume.pdf"
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_failed_application_retryable():
    """A failed application can be reset to PENDING for retry."""
    engine, session = _setup()
    try:
        job = Job(
            external_id="retry-1",
            platform=Platform.LINKEDIN,
            title="Dev",
            company="RetryCo",
            status=JobStatus.APPLY_FAILED,
        )
        session.add(job)
        session.flush()

        app_repo = ApplicationRepository(session)
        app = app_repo.create(
            job_id=job.id,
            resume_path="/resume.pdf",
            status=ApplicationStatus.FAILED,
            error_message="Submit button not found",
        )
        session.commit()

        # Retry: reset application and job status
        app.status = ApplicationStatus.PENDING
        app.error_message = ""
        job.status = JobStatus.APPROVED
        session.commit()

        refreshed_app = session.get(Application, app.id)
        refreshed_job = session.get(Job, job.id)
        assert refreshed_app.status == ApplicationStatus.PENDING
        assert refreshed_app.error_message == ""
        assert refreshed_job.status == JobStatus.APPROVED
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_failed_application_with_empty_paths():
    """Exception failures create Application with empty paths."""
    engine, session = _setup()
    try:
        job = Job(
            external_id="exc-1",
            platform=Platform.INDEED,
            title="QA",
            company="ExcCo",
            status=JobStatus.APPLY_FAILED,
        )
        session.add(job)
        session.flush()

        app_repo = ApplicationRepository(session)
        app = app_repo.create(
            job_id=job.id,
            resume_path="",
            cover_letter_path="",
            status=ApplicationStatus.FAILED,
            error_message="TimeoutError: page load exceeded 30s",
        )
        session.commit()

        assert app.resume_path == ""
        assert app.cover_letter_path == ""
        assert "TimeoutError" in app.error_message
    finally:
        session.close()
        engine.dispose()
        reset_engine()
