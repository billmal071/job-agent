"""Tests for configuration loading."""

from job_agent.config import Settings


def test_default_settings():
    """Test Pydantic model defaults (without .env or YAML overrides)."""
    s = Settings(_env_file=None)
    assert s.matching.auto_apply_threshold == 0.80
    assert s.matching.review_threshold == 0.70
    assert s.agent.activity_start_hour == 8
    assert s.agent.activity_end_hour == 23
    assert s.platforms.linkedin.enabled is True


def test_settings_override():
    s = Settings(_env_file=None, anthropic_api_key="test-key")
    assert s.anthropic_api_key == "test-key"
