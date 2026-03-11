"""Tests for application follow-up reminders."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from job_agent.db.models import (
    Application,
    ApplicationStatus,
    Base,
    Job,
    Platform,
)
from job_agent.db.repository import ApplicationRepository
from job_agent.db.session import reset_engine


def _make_session():
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, Session()


def test_list_needing_followup_returns_old_submissions():
    """Applications submitted 7+ days ago are returned."""
    engine, session = _make_session()
    try:
        job = Job(
            external_id="fu-1",
            platform=Platform.LINKEDIN,
            title="Dev",
            company="Co",
        )
        session.add(job)
        session.flush()

        old_app = Application(
            job_id=job.id,
            status=ApplicationStatus.SUBMITTED,
            applied_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        session.add(old_app)
        session.commit()

        repo = ApplicationRepository(session)
        results = repo.list_needing_followup(days=7)
        assert len(results) == 1
        assert results[0].id == old_app.id
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_list_needing_followup_excludes_recent():
    """Applications submitted less than 7 days ago are not returned."""
    engine, session = _make_session()
    try:
        job = Job(
            external_id="fu-2",
            platform=Platform.LINKEDIN,
            title="Dev",
            company="Co",
        )
        session.add(job)
        session.flush()

        recent_app = Application(
            job_id=job.id,
            status=ApplicationStatus.SUBMITTED,
            applied_at=datetime.now(timezone.utc) - timedelta(days=3),
        )
        session.add(recent_app)
        session.commit()

        repo = ApplicationRepository(session)
        results = repo.list_needing_followup(days=7)
        assert len(results) == 0
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_list_needing_followup_excludes_non_submitted():
    """Only SUBMITTED applications are returned, not CONFIRMED or FAILED."""
    engine, session = _make_session()
    try:
        job = Job(
            external_id="fu-3",
            platform=Platform.LINKEDIN,
            title="Dev",
            company="Co",
        )
        session.add(job)
        session.flush()

        confirmed = Application(
            job_id=job.id,
            status=ApplicationStatus.CONFIRMED,
            applied_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        session.add(confirmed)
        session.commit()

        repo = ApplicationRepository(session)
        results = repo.list_needing_followup(days=7)
        assert len(results) == 0
    finally:
        session.close()
        engine.dispose()
        reset_engine()
