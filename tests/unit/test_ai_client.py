"""Tests for AIClient: provider selection, model guard, retry logic."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from job_agent.ai.client import (
    AIClient,
    DEFAULT_MODELS,
    PROVIDER_GROQ,
)
from job_agent.config import Settings


def _settings(**overrides) -> Settings:
    defaults = dict(
        anthropic_api_key="test-key",
        gemini_api_key="test-gemini",
        groq_api_key="test-groq",
        database_url="sqlite:///:memory:",
        flask_secret_key="test-secret",
    )
    defaults.update(overrides)
    return Settings(**defaults)


class TestModelMismatch:
    def test_claude_model_with_groq_auto_corrects(self):
        s = _settings(ai_provider="groq")
        s.matching.model = "claude-sonnet-4-20250514"
        with patch("job_agent.ai.client.anthropic", create=True):
            client = AIClient(s)
        assert client.model == DEFAULT_MODELS[PROVIDER_GROQ]

    def test_claude_model_with_anthropic_kept(self):
        s = _settings(ai_provider="anthropic")
        s.matching.model = "claude-sonnet-4-20250514"
        with patch("job_agent.ai.client.anthropic", create=True):
            client = AIClient(s)
        assert client.model == "claude-sonnet-4-20250514"


class TestProviderValidation:
    def test_unknown_provider_raises(self):
        s = _settings(ai_provider="unknown_provider")
        with pytest.raises(ValueError, match="Unknown AI provider"):
            AIClient(s)

    def test_missing_groq_key_raises(self):
        s = _settings(ai_provider="groq", groq_api_key="")
        with pytest.raises(ValueError, match="Groq API key required"):
            AIClient(s)


class TestErrorClassification:
    def test_auth_error_no_retry(self):
        assert AIClient._classify_error("401 unauthorized") == "auth"
        assert AIClient._classify_error("403 forbidden") == "auth"

    def test_rate_limit_error(self):
        assert AIClient._classify_error("429 rate limit exceeded") == "rate_limit"
        assert AIClient._classify_error("rate limited") == "rate_limit"

    def test_server_error(self):
        assert AIClient._classify_error("500 internal server error") == "server"
        assert AIClient._classify_error("502 bad gateway") == "server"

    def test_other_error(self):
        assert AIClient._classify_error("something went wrong") == "other"


class TestRetryBehaviour:
    def test_auth_error_raises_immediately(self):
        s = _settings(ai_provider="groq")
        with patch("job_agent.ai.client.anthropic", create=True):
            client = AIClient(s)

        with patch.object(client, "_complete_openai_compat") as mock_complete:
            mock_complete.side_effect = Exception("401 Unauthorized")
            with pytest.raises(Exception, match="401 Unauthorized"):
                client.complete("hello", retries=3)
            # Should be called only once (no retries on auth error)
            assert mock_complete.call_count == 1
