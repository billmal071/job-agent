"""Tests for CoverLetterGenerator."""

from __future__ import annotations

from unittest.mock import MagicMock
from pathlib import Path


from job_agent.ai.cover_letter import CoverLetterGenerator
from job_agent.db.models import Platform
from job_agent.platforms.base import JobPosting


def _make_job() -> JobPosting:
    return JobPosting(
        external_id="j1",
        platform=Platform.LINKEDIN,
        title="Engineer",
        company="Acme",
        description="Build stuff",
        url="https://example.com/job/1",
    )


class TestGenerate:
    def test_calls_ai_with_correct_prompt(self, settings):
        ai = MagicMock()
        ai.complete.return_value = "Dear Hiring Manager..."
        gen = CoverLetterGenerator(ai, settings)

        result = gen.generate(
            _make_job(),
            candidate_summary="10 years Python",
            matched_skills=["Python", "Django"],
            tone="enthusiastic",
        )

        assert result == "Dear Hiring Manager..."
        ai.complete.assert_called_once()
        call_kwargs = ai.complete.call_args
        assert (
            "enthusiastic" in call_kwargs.kwargs.get("prompt", "")
            or "enthusiastic" in call_kwargs.args[0]
            if call_kwargs.args
            else True
        )

    def test_default_tone_from_settings(self, settings):
        ai = MagicMock()
        ai.complete.return_value = "text"
        gen = CoverLetterGenerator(ai, settings)

        gen.generate(_make_job(), "summary", ["Python"])
        call_kwargs = ai.complete.call_args
        prompt = call_kwargs.kwargs.get(
            "prompt", call_kwargs.args[0] if call_kwargs.args else ""
        )
        assert settings.resume.cover_letter_tone in prompt


class TestGenerateAndSave:
    def test_creates_file(self, settings, tmp_path):
        ai = MagicMock()
        ai.complete.return_value = "Cover letter content"
        gen = CoverLetterGenerator(ai, settings)

        path = gen.generate_and_save(
            _make_job(),
            "summary",
            ["Python"],
            output_dir=str(tmp_path),
        )

        assert Path(path).exists()
        assert Path(path).read_text() == "Cover letter content"
