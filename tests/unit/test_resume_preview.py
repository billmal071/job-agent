"""Tests for resume preview dashboard routes."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from job_agent.config import Settings
from job_agent.dashboard.app import create_app
from job_agent.db.models import Base, Job, MatchResult, Platform, JobStatus
from job_agent.db.session import reset_engine


@pytest.fixture
def app_with_job(tmp_path):
    """Create Flask app with a test job in the database."""
    reset_engine()

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()

    # Create a test job with match result
    job = Job(
        external_id="test-123",
        platform=Platform.LINKEDIN,
        title="Senior Python Developer",
        company="Acme Corp",
        location="Remote",
        description="Build amazing Python applications using Django and FastAPI.",
        url="https://example.com/job/123",
        status=JobStatus.MATCHED,
    )
    session.add(job)
    session.flush()

    match = MatchResult(
        job_id=job.id,
        score=0.85,
        reasoning="Strong Python match",
        matched_skills='["Python", "Django"]',
        missing_skills='["FastAPI"]',
    )
    session.add(match)
    session.commit()
    job_id = job.id

    settings = Settings(
        _env_file=None,
        anthropic_api_key="test-key",
        database_url="sqlite:///:memory:",
        flask_secret_key="test-secret",
    )

    with patch("job_agent.dashboard.routes.jobs.get_session", return_value=session):
        app = create_app(settings)
        app.config["TESTING"] = True
        yield app, job_id, session, settings

    session.close()
    engine.dispose()
    reset_engine()


def test_detail_page_shows_resume_section(app_with_job):
    """Job detail page includes the resume preview section."""
    app, job_id, _, _ = app_with_job
    with app.test_client() as client:
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Tailored Resume" in html
        assert "Preview" in html


def test_detail_page_shows_regenerate_when_md_exists(app_with_job, tmp_path):
    """Shows 'Regenerate' when a markdown draft already exists."""
    app, job_id, _, settings = app_with_job

    # Create a fake markdown file
    resume_dir = Path(settings.data_dir / "resumes")
    resume_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "Acme_Corp_test-123"
    md_path = resume_dir / f"{safe_name}.md"
    md_path.write_text("# Test Resume")

    with app.test_client() as client:
        resp = client.get(f"/jobs/{job_id}")
        assert resp.status_code == 200
        html = resp.data.decode()
        assert "Regenerate" in html

    # Clean up
    md_path.unlink(missing_ok=True)


def test_preview_resume_generates_markdown(app_with_job):
    """POST to preview-resume returns an editable textarea with tailored markdown."""
    app, job_id, _, _ = app_with_job

    with (
        patch("job_agent.ai.client.AIClient"),
        patch("job_agent.ai.resume_tailor.ResumeTailor") as MockTailor,
    ):
        mock_tailor_instance = MagicMock()
        mock_tailor_instance.tailor.return_value = (
            "# Tailored Resume\n\n- Python expert"
        )
        MockTailor.return_value = mock_tailor_instance

        with app.test_client() as client:
            resp = client.post(f"/jobs/{job_id}/preview-resume")
            assert resp.status_code == 200
            html = resp.data.decode()
            assert "Tailored Resume" in html
            assert "textarea" in html
            assert "Save &" in html and "Generate PDF" in html


def test_save_resume_generates_pdf(app_with_job):
    """POST to save-resume saves markdown and generates PDF."""
    app, job_id, _, _ = app_with_job

    with (
        patch("job_agent.ai.client.AIClient"),
        patch("job_agent.ai.resume_tailor.ResumeTailor") as MockTailor,
    ):
        mock_tailor_instance = MagicMock()
        mock_tailor_instance.generate_pdf.return_value = "/tmp/test.pdf"
        MockTailor.return_value = mock_tailor_instance

        with app.test_client() as client:
            resp = client.post(
                f"/jobs/{job_id}/save-resume",
                data={"resume_md": "# My Resume\n\n- Skills"},
            )
            assert resp.status_code == 200
            html = resp.data.decode()
            assert "Resume saved" in html
            assert "Download PDF" in html
            mock_tailor_instance.generate_pdf.assert_called_once()


def test_save_resume_rejects_empty(app_with_job):
    """POST to save-resume with empty content returns 400."""
    app, job_id, _, _ = app_with_job

    with app.test_client() as client:
        resp = client.post(
            f"/jobs/{job_id}/save-resume",
            data={"resume_md": ""},
        )
        assert resp.status_code == 400
        assert b"empty" in resp.data


def test_download_resume_not_found(app_with_job):
    """Download returns 404 when no PDF exists."""
    app, job_id, _, _ = app_with_job

    with app.test_client() as client:
        resp = client.get(f"/jobs/{job_id}/download-resume")
        assert resp.status_code == 404
