"""Tests for configuration loading."""

from job_agent.config import Settings, load_settings


def test_default_settings():
    s = Settings()
    assert s.matching.auto_apply_threshold == 0.80
    assert s.matching.review_threshold == 0.70
    assert s.agent.activity_start_hour == 8
    assert s.agent.activity_end_hour == 23
    assert s.platforms.linkedin.enabled is True


def test_settings_override():
    s = Settings(anthropic_api_key="test-key")
    assert s.anthropic_api_key == "test-key"
