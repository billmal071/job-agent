"""Tests for stats digest generation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from job_agent.config import Settings
from job_agent.db.models import (
    Application,
    ApplicationStatus,
    Base,
    Job,
    Platform,
)
from job_agent.db.session import reset_engine
from job_agent.orchestrator.digest import format_digest_text, generate_digest


def test_generate_digest_with_data():
    """Digest includes correct counts for recent applications."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()

    job1 = Job(
        external_id="dig-1",
        platform=Platform.LINKEDIN,
        title="Dev",
        company="Co",
    )
    job2 = Job(
        external_id="dig-2",
        platform=Platform.LINKEDIN,
        title="Dev2",
        company="Co2",
    )
    session.add_all([job1, job2])
    session.flush()

    # Recent submitted app
    app1 = Application(
        job_id=job1.id,
        status=ApplicationStatus.SUBMITTED,
        applied_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    # Old submitted app (should count in followups)
    app2 = Application(
        job_id=job2.id,
        status=ApplicationStatus.SUBMITTED,
        applied_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    session.add_all([app1, app2])
    session.commit()

    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
    )

    with patch("job_agent.orchestrator.digest.get_session", return_value=session):
        stats = generate_digest(settings, days=7)

    assert stats["total_jobs"] == 2
    assert stats["recent_applications"] == 2
    assert stats["submitted"] == 2
    assert stats["followups_needed"] == 1

    session.close()
    engine.dispose()
    reset_engine()


def test_generate_digest_empty():
    """Digest works with no data."""
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()

    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test",
    )

    with patch("job_agent.orchestrator.digest.get_session", return_value=session):
        stats = generate_digest(settings)

    assert stats["total_jobs"] == 0
    assert stats["recent_applications"] == 0
    assert stats["followups_needed"] == 0

    session.close()
    engine.dispose()
    reset_engine()


def test_format_digest_text():
    """Formatted text includes key sections."""
    stats = {
        "period_days": 7,
        "total_jobs": 42,
        "status_counts": {"discovered": 20, "applied": 15, "queued": 7},
        "recent_applications": 10,
        "submitted": 6,
        "confirmed": 2,
        "failed": 1,
        "pending": 1,
        "followups_needed": 3,
        "generated_at": "2026-03-11T00:00:00+00:00",
    }
    text = format_digest_text(stats)
    assert "Weekly Digest" in text
    assert "Total jobs tracked: 42" in text
    assert "Submitted: 6" in text
    assert "follow-up (7+ days): 3" in text
    assert "discovered: 20" in text
