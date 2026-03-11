"""Tests for ColdEmailGenerator."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from job_agent.ai.cold_email import ColdEmailGenerator
from job_agent.config import Settings


def _make_settings() -> Settings:
    return Settings(
        _env_file=None,
        anthropic_api_key="test-key",
    )


def _make_generator(ai: MagicMock) -> ColdEmailGenerator:
    return ColdEmailGenerator(ai, _make_settings())


GENERATE_KWARGS = dict(
    job_title="Software Engineer",
    company="Acme Corp",
    recipient_name="Jane Doe",
    recipient_title="Engineering Manager",
    matched_skills=["Python", "FastAPI"],
    candidate_summary="5 years of backend development experience.",
)


class TestGenerate:
    def test_generate_valid_json(self):
        """AI returns valid JSON with subject and body keys."""
        ai = MagicMock()
        ai.complete.return_value = json.dumps(
            {
                "subject": "Excited about the Software Engineer role at Acme Corp",
                "body": "Hi Jane,\n\nI'd love to connect about the role.",
            }
        )
        gen = _make_generator(ai)

        result = gen.generate(**GENERATE_KWARGS)

        assert (
            result["subject"] == "Excited about the Software Engineer role at Acme Corp"
        )
        assert result["body"] == "Hi Jane,\n\nI'd love to connect about the role."

    def test_generate_json_fallback(self):
        """AI returns non-JSON text; falls back to generic subject."""
        ai = MagicMock()
        ai.complete.return_value = (
            "Hi Jane, I wanted to reach out about the role at Acme."
        )
        gen = _make_generator(ai)

        result = gen.generate(**GENERATE_KWARGS)

        assert (
            result["subject"] == "Interest in Software Engineer position at Acme Corp"
        )
        assert (
            result["body"] == "Hi Jane, I wanted to reach out about the role at Acme."
        )

    def test_generate_calls_ai_with_prompt(self):
        """AI complete() is called exactly once."""
        ai = MagicMock()
        ai.complete.return_value = json.dumps({"subject": "Hello", "body": "World"})
        gen = _make_generator(ai)

        gen.generate(**GENERATE_KWARGS)

        ai.complete.assert_called_once()
