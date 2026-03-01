"""Tests for ResumeTailor."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from job_agent.ai.resume_tailor import ResumeTailor
from job_agent.db.models import Platform
from job_agent.platforms.base import JobPosting


def _make_job() -> JobPosting:
    return JobPosting(
        external_id="j1",
        platform=Platform.LINKEDIN,
        title="Engineer",
        company="Acme",
        description="Build stuff with Python and Django",
        url="https://example.com/job/1",
    )


class TestTailor:
    def test_calls_ai_complete(self, settings):
        ai = MagicMock()
        ai.complete.return_value = "# Tailored Resume\n..."
        tailor = ResumeTailor(ai, settings)

        result = tailor.tailor(_make_job(), ["Python", "Django"], master_resume="# My Resume")

        assert result == "# Tailored Resume\n..."
        ai.complete.assert_called_once()

    def test_missing_master_resume_raises(self, settings):
        ai = MagicMock()
        tailor = ResumeTailor(ai, settings)
        # Default master_resume path won't exist
        with pytest.raises(FileNotFoundError, match="Master resume not found"):
            tailor.tailor(_make_job(), ["Python"])


class TestTailorAndSave:
    def test_generates_pdf(self, settings, tmp_path):
        ai = MagicMock()
        ai.complete.return_value = "# Resume\n\n- Python expert"
        tailor = ResumeTailor(ai, settings)

        from unittest.mock import patch

        pdf_path = str(tmp_path / "out.pdf")
        with patch.object(tailor, "tailor", return_value="# Tailored") as mock_tailor, \
             patch.object(tailor, "generate_pdf", return_value=pdf_path) as mock_pdf:
            result = tailor.tailor_and_save(
                _make_job(),
                ["Python"],
                output_dir=str(tmp_path),
            )

            mock_tailor.assert_called_once()
            mock_pdf.assert_called_once()
            assert "out.pdf" in result
