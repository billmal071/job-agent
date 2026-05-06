"""Tests for extracted pipeline step functions."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from job_agent.config import Settings
from job_agent.db.models import Base, Job, JobStatus, Platform


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def settings():
    return Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
    )


class TestMatchJob:
    def test_returns_match_score(self, db_session, settings):
        from job_agent.orchestrator.pipeline_steps import match_job
        from job_agent.platforms.base import JobPosting
        from job_agent.db.repository import JobRepository, MatchResultRepository

        job_repo = JobRepository(db_session)
        match_repo = MatchResultRepository(db_session)

        posting = JobPosting(
            external_id="ext-1",
            platform=Platform.LINKEDIN,
            title="Software Engineer",
            company="Acme",
            location="Remote",
            description="Python dev needed",
            url="https://example.com/job/1",
        )
        job = job_repo.create(
            external_id=posting.external_id,
            platform=posting.platform,
            title=posting.title,
            company=posting.company,
            location=posting.location,
            description=posting.description,
            url=posting.url,
        )
        db_session.commit()

        mock_matcher = MagicMock()
        mock_score = MagicMock()
        mock_score.score = 85.0
        mock_score.reasoning = "Good fit"
        mock_score.matched_skills = '["Python"]'
        mock_score.missing_skills = '[]'
        mock_score.role_fit = "strong"
        mock_score.red_flags = '[]'
        mock_matcher.match.return_value = mock_score

        profile = {"name": "Backend Engineer"}

        result = match_job(
            job=job,
            posting=posting,
            matcher=mock_matcher,
            match_repo=match_repo,
            profile=profile,
        )

        assert result == mock_score
        assert job.status == JobStatus.MATCHED
        mock_matcher.match.assert_called_once_with(posting, profile)


class TestDecideJob:
    def test_auto_approve_above_threshold(self, settings):
        from job_agent.orchestrator.pipeline_steps import decide_job

        mock_score = MagicMock()
        mock_score.score = 90.0

        job = MagicMock()
        settings.matching.auto_apply_threshold = 80
        settings.matching.review_threshold = 50

        decision = decide_job(job, mock_score, settings)

        assert decision == "auto_apply"
        assert job.status == JobStatus.AUTO_APPROVED

    def test_queue_between_thresholds(self, settings):
        from job_agent.orchestrator.pipeline_steps import decide_job

        mock_score = MagicMock()
        mock_score.score = 60.0

        job = MagicMock()
        settings.matching.auto_apply_threshold = 80
        settings.matching.review_threshold = 50

        decision = decide_job(job, mock_score, settings)

        assert decision == "queue"
        assert job.status == JobStatus.QUEUED

    def test_skip_below_review_threshold(self, settings):
        from job_agent.orchestrator.pipeline_steps import decide_job

        mock_score = MagicMock()
        mock_score.score = 30.0

        job = MagicMock()
        settings.matching.auto_apply_threshold = 80
        settings.matching.review_threshold = 50

        decision = decide_job(job, mock_score, settings)

        assert decision == "skip"
        assert job.status == JobStatus.SKIPPED


class TestApplyToJob:
    def test_success_sets_applied_status(self, db_session, settings):
        from job_agent.orchestrator.pipeline_steps import apply_to_job
        from job_agent.platforms.base import JobPosting
        from job_agent.db.repository import ApplicationRepository, JobRepository

        job_repo = JobRepository(db_session)
        app_repo = ApplicationRepository(db_session)

        posting = JobPosting(
            external_id="ext-1",
            platform=Platform.LINKEDIN,
            title="SWE",
            company="Acme",
            location="Remote",
            description="desc",
            url="https://example.com/job/1",
        )
        job = job_repo.create(
            external_id=posting.external_id,
            platform=posting.platform,
            title=posting.title,
            company=posting.company,
            location=posting.location,
            description=posting.description,
            url=posting.url,
        )
        db_session.commit()

        mock_driver = MagicMock()
        mock_driver.apply.return_value = True
        mock_resume_tailor = MagicMock()
        mock_resume_tailor.tailor_and_save.return_value = "/tmp/resume.pdf"
        mock_cl_gen = MagicMock()
        mock_cl_gen.generate_and_save.return_value = "/tmp/cover.pdf"

        result = apply_to_job(
            job=job,
            posting=posting,
            driver=mock_driver,
            resume_tailor=mock_resume_tailor,
            cover_letter_gen=mock_cl_gen,
            app_repo=app_repo,
            candidate_summary="Python dev",
            matched_skills=["Python"],
        )

        assert result is True
        assert job.status == JobStatus.APPLIED

    def test_failure_sets_apply_failed(self, db_session, settings):
        from job_agent.orchestrator.pipeline_steps import apply_to_job
        from job_agent.platforms.base import JobPosting
        from job_agent.db.repository import ApplicationRepository, JobRepository

        job_repo = JobRepository(db_session)
        app_repo = ApplicationRepository(db_session)

        posting = JobPosting(
            external_id="ext-2",
            platform=Platform.LINKEDIN,
            title="SWE",
            company="Acme",
            location="Remote",
            description="desc",
            url="https://example.com/job/2",
        )
        job = job_repo.create(
            external_id=posting.external_id,
            platform=posting.platform,
            title=posting.title,
            company=posting.company,
            location=posting.location,
            description=posting.description,
            url=posting.url,
        )
        db_session.commit()

        mock_driver = MagicMock()
        mock_driver.apply.return_value = False
        mock_resume_tailor = MagicMock()
        mock_resume_tailor.tailor_and_save.return_value = "/tmp/resume.pdf"
        mock_cl_gen = MagicMock()
        mock_cl_gen.generate_and_save.return_value = "/tmp/cover.pdf"

        result = apply_to_job(
            job=job,
            posting=posting,
            driver=mock_driver,
            resume_tailor=mock_resume_tailor,
            cover_letter_gen=mock_cl_gen,
            app_repo=app_repo,
            candidate_summary="Python dev",
            matched_skills=["Python"],
        )

        assert result is False
        assert job.status == JobStatus.APPLY_FAILED

    def test_cover_letter_failure_continues(self, db_session, settings):
        from job_agent.orchestrator.pipeline_steps import apply_to_job
        from job_agent.platforms.base import JobPosting
        from job_agent.db.repository import ApplicationRepository, JobRepository

        job_repo = JobRepository(db_session)
        app_repo = ApplicationRepository(db_session)

        posting = JobPosting(
            external_id="ext-3",
            platform=Platform.LINKEDIN,
            title="SWE",
            company="Acme",
            location="Remote",
            description="desc",
            url="https://example.com/job/3",
        )
        job = job_repo.create(
            external_id=posting.external_id,
            platform=posting.platform,
            title=posting.title,
            company=posting.company,
            location=posting.location,
            description=posting.description,
            url=posting.url,
        )
        db_session.commit()

        mock_driver = MagicMock()
        mock_driver.apply.return_value = True
        mock_resume_tailor = MagicMock()
        mock_resume_tailor.tailor_and_save.return_value = "/tmp/resume.pdf"
        mock_cl_gen = MagicMock()
        mock_cl_gen.generate_and_save.side_effect = RuntimeError("AI failed")

        result = apply_to_job(
            job=job,
            posting=posting,
            driver=mock_driver,
            resume_tailor=mock_resume_tailor,
            cover_letter_gen=mock_cl_gen,
            app_repo=app_repo,
            candidate_summary="Python dev",
            matched_skills=["Python"],
        )

        assert result is True
        assert job.status == JobStatus.APPLIED
        mock_driver.apply.assert_called_once()


class TestBuildCandidateSummary:
    def test_full_profile(self):
        from job_agent.orchestrator.pipeline_steps import build_candidate_summary

        profile = {
            "name": "Backend Engineer",
            "search": {"experience_level": "senior"},
            "skills": {
                "required": ["Python", "Go"],
                "preferred": ["Rust"],
            },
        }
        result = build_candidate_summary(profile)
        assert "Target Role: Backend Engineer" in result
        assert "Experience Level: senior" in result
        assert "Required Skills: Python, Go" in result
        assert "Preferred Skills: Rust" in result

    def test_empty_profile(self):
        from job_agent.orchestrator.pipeline_steps import build_candidate_summary

        assert build_candidate_summary({}) == ""


class TestGetMatchedSkillsForJob:
    def test_with_skills(self):
        from job_agent.orchestrator.pipeline_steps import get_matched_skills_for_job

        job = MagicMock()
        job.match_result.matched_skills = '["Python", "Go"]'
        assert get_matched_skills_for_job(job) == ["Python", "Go"]

    def test_no_match_result(self):
        from job_agent.orchestrator.pipeline_steps import get_matched_skills_for_job

        job = MagicMock()
        job.match_result = None
        assert get_matched_skills_for_job(job) == []
