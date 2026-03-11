"""Tests for job bookmarking feature."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from job_agent.config import Settings
from job_agent.dashboard.app import create_app
from job_agent.db.models import Base, Job, JobStatus, Platform
from job_agent.db.repository import JobRepository
from job_agent.db.session import reset_engine


def _make_session():
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, Session()


def test_toggle_bookmark_on():
    """Toggle bookmark sets bookmarked=True."""
    engine, session = _make_session()
    try:
        repo = JobRepository(session)
        job = repo.create(
            external_id="bk-1",
            platform=Platform.LINKEDIN,
            title="Dev",
            company="Co",
        )
        session.flush()
        assert job.bookmarked is False

        result = repo.toggle_bookmark(job.id)
        assert result is not None
        assert result.bookmarked is True
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_toggle_bookmark_off():
    """Toggle bookmark twice sets bookmarked back to False."""
    engine, session = _make_session()
    try:
        repo = JobRepository(session)
        job = repo.create(
            external_id="bk-2",
            platform=Platform.LINKEDIN,
            title="Dev",
            company="Co",
        )
        session.flush()

        repo.toggle_bookmark(job.id)
        result = repo.toggle_bookmark(job.id)
        assert result is not None
        assert result.bookmarked is False
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_list_bookmarked_only():
    """list_all with bookmarked=True returns only bookmarked jobs."""
    engine, session = _make_session()
    try:
        repo = JobRepository(session)
        j1 = repo.create(
            external_id="bk-3", platform=Platform.LINKEDIN, title="A", company="Co"
        )
        repo.create(
            external_id="bk-4", platform=Platform.LINKEDIN, title="B", company="Co"
        )
        session.flush()

        repo.toggle_bookmark(j1.id)
        session.flush()

        bookmarked = repo.list_all(bookmarked=True)
        assert len(bookmarked) == 1
        assert bookmarked[0].id == j1.id

        all_jobs = repo.list_all()
        assert len(all_jobs) == 2
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_bookmark_toggle_route():
    """POST /jobs/<id>/bookmark toggles and returns HTMX snippet."""
    engine, session = _make_session()
    try:
        repo = JobRepository(session)
        job = repo.create(
            external_id="bk-5",
            platform=Platform.LINKEDIN,
            title="Dev",
            company="Co",
        )
        session.flush()
        session.commit()

        settings = Settings(
            _env_file=None,
            anthropic_api_key="test-key",
            database_url="sqlite:///:memory:",
            flask_secret_key="test",
        )

        with patch(
            "job_agent.dashboard.routes.jobs.get_session",
            return_value=session,
        ):
            app = create_app(settings)
            app.config["TESTING"] = True
            with app.test_client() as client:
                resp = client.post(f"/jobs/{job.id}/bookmark")
                assert resp.status_code == 200
                html = resp.data.decode()
                assert "bi-bookmark-fill" in html
                assert "btn-warning" in html
    finally:
        session.close()
        engine.dispose()
        reset_engine()
