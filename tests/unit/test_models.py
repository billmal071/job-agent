"""Tests for database models and repository."""

from job_agent.db.models import JobStatus, Platform
from job_agent.db.repository import JobRepository, MatchResultRepository


def test_create_job(db_session):
    repo = JobRepository(db_session)
    job = repo.create(
        external_id="123",
        platform=Platform.LINKEDIN,
        title="Python Developer",
        company="TestCo",
        location="Remote",
    )
    db_session.commit()

    assert job.id is not None
    assert job.title == "Python Developer"
    assert job.status == JobStatus.DISCOVERED


def test_dedup_check(db_session):
    repo = JobRepository(db_session)
    repo.create(
        external_id="456",
        platform=Platform.LINKEDIN,
        title="Backend Dev",
        company="Corp",
    )
    db_session.commit()

    assert repo.exists("456", Platform.LINKEDIN)
    assert not repo.exists("456", Platform.INDEED)
    assert not repo.exists("789", Platform.LINKEDIN)


def test_match_result(db_session):
    job_repo = JobRepository(db_session)
    match_repo = MatchResultRepository(db_session)

    job = job_repo.create(
        external_id="789",
        platform=Platform.INDEED,
        title="Full Stack",
        company="StartupCo",
    )
    db_session.commit()

    result = match_repo.create(
        job_id=job.id,
        score=0.85,
        reasoning="Good match for skills",
        matched_skills=["Python", "React"],
        missing_skills=["Go"],
        role_fit="Strong",
        red_flags=[],
    )
    db_session.commit()

    assert result.score == 0.85
    fetched = match_repo.get_by_job_id(job.id)
    assert fetched is not None
    assert fetched.score == 0.85


def test_list_by_status(db_session):
    repo = JobRepository(db_session)
    for i in range(3):
        job = repo.create(
            external_id=f"q{i}",
            platform=Platform.LINKEDIN,
            title=f"Job {i}",
            company="Co",
        )
        job.status = JobStatus.QUEUED
    db_session.commit()

    queued = repo.list_queued()
    assert len(queued) == 3
