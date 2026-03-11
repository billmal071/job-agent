"""Unit tests for ReviewQueueManager."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from job_agent.config import Settings
from job_agent.db.models import (
    Application,
    ApplicationStatus,
    Base,
    Job,
    JobStatus,
    Platform,
)
from job_agent.db.repository import JobRepository
from job_agent.orchestrator.queue import ReviewQueueManager


@pytest.fixture()
def settings():
    """Test settings with in-memory SQLite."""
    return Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
    )


@pytest.fixture()
def db_session():
    """In-memory SQLite session with all tables created.

    expire_on_commit=False keeps object attributes readable after commit even
    when the queue manager calls session.close() in its finally block.
    """
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def manager(settings, db_session):
    """ReviewQueueManager with get_session mocked to return the test session."""
    with patch("job_agent.orchestrator.queue.get_session", return_value=db_session):
        yield ReviewQueueManager(settings)


def _make_job(session, status: JobStatus = JobStatus.QUEUED, suffix: str = "1"):
    """Helper: create and persist a Job with the given status."""
    repo = JobRepository(session)
    job = repo.create(
        external_id=f"ext-{suffix}",
        platform=Platform.LINKEDIN,
        title=f"Job {suffix}",
        company="TestCo",
    )
    job.status = status
    session.commit()
    return job


def test_get_queue_empty(settings, db_session):
    """get_queue() returns an empty list when no QUEUED jobs exist."""
    with patch("job_agent.orchestrator.queue.get_session", return_value=db_session):
        mgr = ReviewQueueManager(settings)
        result = mgr.get_queue()

    assert result == []


def test_approve_queued_job(settings, db_session):
    """approve() changes a QUEUED job's status to APPROVED and returns True."""
    job = _make_job(db_session, status=JobStatus.QUEUED)
    job_id = job.id

    with patch("job_agent.orchestrator.queue.get_session", return_value=db_session):
        mgr = ReviewQueueManager(settings)
        success = mgr.approve(job_id)

    assert success is True
    # Re-query after session.close() was called inside the manager.
    refreshed = db_session.get(Job, job_id)
    assert refreshed is not None
    assert refreshed.status == JobStatus.APPROVED


def test_approve_non_queued_returns_false(settings, db_session):
    """approve() returns False when the job is not in QUEUED status."""
    job = _make_job(db_session, status=JobStatus.REJECTED)
    job_id = job.id

    with patch("job_agent.orchestrator.queue.get_session", return_value=db_session):
        mgr = ReviewQueueManager(settings)
        success = mgr.approve(job_id)

    assert success is False
    # Status must remain REJECTED — re-query after session.close().
    refreshed = db_session.get(Job, job_id)
    assert refreshed is not None
    assert refreshed.status == JobStatus.REJECTED


def test_reject_queued_job(settings, db_session):
    """reject() changes a QUEUED job's status to REJECTED and returns True."""
    job = _make_job(db_session, status=JobStatus.QUEUED)
    job_id = job.id

    with patch("job_agent.orchestrator.queue.get_session", return_value=db_session):
        mgr = ReviewQueueManager(settings)
        success = mgr.reject(job_id)

    assert success is True
    # Re-query after session.close() was called inside the manager.
    refreshed = db_session.get(Job, job_id)
    assert refreshed is not None
    assert refreshed.status == JobStatus.REJECTED


def test_process_approved_creates_applications(settings, db_session):
    """process_approved() creates Application records for each APPROVED job."""
    job1 = _make_job(db_session, status=JobStatus.APPROVED, suffix="a")
    job2 = _make_job(db_session, status=JobStatus.APPROVED, suffix="b")
    # A QUEUED job — should not get an Application.
    _make_job(db_session, status=JobStatus.QUEUED, suffix="c")

    # Capture IDs before the manager calls session.close().
    job1_id = job1.id
    job2_id = job2.id

    with patch("job_agent.orchestrator.queue.get_session", return_value=db_session):
        mgr = ReviewQueueManager(settings)
        count = mgr.process_approved()

    assert count == 2

    apps = list(db_session.scalars(select(Application)).all())
    assert len(apps) == 2
    app_job_ids = {app.job_id for app in apps}
    assert app_job_ids == {job1_id, job2_id}
    for app in apps:
        assert app.status == ApplicationStatus.PENDING
