"""Tests for cross-platform job deduplication."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from job_agent.db.models import Base, JobStatus, Platform
from job_agent.db.repository import JobRepository
from job_agent.db.session import reset_engine


def _make_session():
    reset_engine()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    return engine, Session()


def test_find_cross_platform_duplicate():
    """Finds existing job with same title+company on different platform."""
    engine, session = _make_session()
    try:
        repo = JobRepository(session)
        original = repo.create(
            external_id="orig-1",
            platform=Platform.LINKEDIN,
            title="Python Developer",
            company="Acme Corp",
        )
        session.flush()

        dup = repo.find_cross_platform_duplicate(
            "Python Developer", "Acme Corp", Platform.INDEED
        )
        assert dup is not None
        assert dup.id == original.id
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_no_duplicate_same_platform():
    """Does not flag same-platform job as duplicate."""
    engine, session = _make_session()
    try:
        repo = JobRepository(session)
        repo.create(
            external_id="orig-2",
            platform=Platform.LINKEDIN,
            title="Python Developer",
            company="Acme Corp",
        )
        session.flush()

        dup = repo.find_cross_platform_duplicate(
            "Python Developer", "Acme Corp", Platform.LINKEDIN
        )
        assert dup is None
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_case_insensitive_matching():
    """Matches title and company case-insensitively."""
    engine, session = _make_session()
    try:
        repo = JobRepository(session)
        original = repo.create(
            external_id="orig-3",
            platform=Platform.LINKEDIN,
            title="Senior Python Developer",
            company="ACME CORP",
        )
        session.flush()

        dup = repo.find_cross_platform_duplicate(
            "senior python developer", "acme corp", Platform.INDEED
        )
        assert dup is not None
        assert dup.id == original.id
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_no_false_positive():
    """Different title or company is not flagged."""
    engine, session = _make_session()
    try:
        repo = JobRepository(session)
        repo.create(
            external_id="orig-4",
            platform=Platform.LINKEDIN,
            title="Python Developer",
            company="Acme Corp",
        )
        session.flush()

        dup = repo.find_cross_platform_duplicate(
            "Java Developer", "Acme Corp", Platform.INDEED
        )
        assert dup is None
    finally:
        session.close()
        engine.dispose()
        reset_engine()


def test_duplicate_of_id_stored_on_job():
    """Job created with duplicate_of_id references original."""
    engine, session = _make_session()
    try:
        repo = JobRepository(session)
        original = repo.create(
            external_id="orig-5",
            platform=Platform.LINKEDIN,
            title="Python Dev",
            company="TestCo",
        )
        session.flush()

        dup_job = repo.create(
            external_id="dup-5",
            platform=Platform.INDEED,
            title="Python Dev",
            company="TestCo",
            duplicate_of_id=original.id,
        )
        dup_job.status = JobStatus.REJECTED
        session.commit()

        fetched = repo.get_by_external_id("dup-5", Platform.INDEED)
        assert fetched is not None
        assert fetched.duplicate_of_id == original.id
        assert fetched.status == JobStatus.REJECTED
    finally:
        session.close()
        engine.dispose()
        reset_engine()
