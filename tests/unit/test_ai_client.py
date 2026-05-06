"""Tests for AIClient: provider selection, model guard, retry logic."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

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


class TestCompletionRouting:
    def test_groq_routes_to_openai_compat(self):
        s = _settings(ai_provider="groq")
        client = AIClient(s)
        with patch.object(client, "_complete_openai_compat", return_value="ok") as m:
            result = client.complete("hello")
        assert result == "ok"
        m.assert_called_once()

    def test_gemini_routes_to_gemini(self):
        s = _settings(ai_provider="gemini")
        client = AIClient(s)
        with patch.object(client, "_complete_gemini", return_value="ok") as m:
            result = client.complete("hello")
        assert result == "ok"
        m.assert_called_once()

    def test_ollama_routes_to_ollama(self):
        s = _settings(ai_provider="ollama")
        client = AIClient(s)
        with patch.object(client, "_complete_ollama", return_value="ok") as m:
            result = client.complete("hello")
        assert result == "ok"
        m.assert_called_once()

    def test_anthropic_routes_to_anthropic(self):
        s = _settings(ai_provider="anthropic")
        with patch("job_agent.ai.client.anthropic", create=True):
            client = AIClient(s)
        with patch.object(client, "_complete_anthropic", return_value="ok") as m:
            result = client.complete("hello")
        assert result == "ok"
        m.assert_called_once()

    def test_openrouter_routes_to_openai_compat(self):
        s = _settings(ai_provider="openrouter", openrouter_api_key="test-or")
        client = AIClient(s)
        with patch.object(client, "_complete_openai_compat", return_value="ok") as m:
            result = client.complete("hello")
        assert result == "ok"
        m.assert_called_once()


class TestGroqRateLimiting:
    def test_groq_has_min_interval(self):
        s = _settings(ai_provider="groq")
        client = AIClient(s)
        assert client._min_call_interval == 3.0

    def test_non_groq_has_no_interval(self):
        s = _settings(ai_provider="gemini")
        client = AIClient(s)
        assert client._min_call_interval == 0.0


class TestRetryBackoff:
    @patch("job_agent.ai.client.time")
    def test_rate_limit_retries_then_succeeds(self, mock_time):
        mock_time.time.return_value = 100.0
        mock_time.sleep = MagicMock()

        s = _settings(ai_provider="groq")
        client = AIClient(s)
        client._last_call_time = 0

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("429 rate limit exceeded")
            return "success"

        with patch.object(client, "_complete_openai_compat", side_effect=side_effect):
            result = client.complete("hello", retries=3)

        assert result == "success"
        assert call_count == 3

    @patch("job_agent.ai.client.time")
    def test_server_error_retries_then_succeeds(self, mock_time):
        mock_time.time.return_value = 100.0
        mock_time.sleep = MagicMock()

        s = _settings(ai_provider="gemini")
        client = AIClient(s)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("502 bad gateway")
            return "recovered"

        with patch.object(client, "_complete_gemini", side_effect=side_effect):
            result = client.complete("hello", retries=3)

        assert result == "recovered"
        assert call_count == 2

    @patch("job_agent.ai.client.time")
    def test_other_error_exhausts_retries(self, mock_time):
        mock_time.time.return_value = 100.0
        mock_time.sleep = MagicMock()

        s = _settings(ai_provider="gemini")
        client = AIClient(s)

        with patch.object(
            client, "_complete_gemini", side_effect=Exception("weird error")
        ):
            with pytest.raises(Exception, match="weird error"):
                client.complete("hello", retries=2)


class TestGeminiCompletion:
    def test_parses_valid_response(self):
        s = _settings(ai_provider="gemini")
        client = AIClient(s)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "Hello world"}]}}],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "post", return_value=mock_response):
            result = client._complete_gemini("prompt", "system", 100, 0.3)

        assert result == "Hello world"

    def test_raises_on_no_candidates(self):
        s = _settings(ai_provider="gemini")
        client = AIClient(s)

        mock_response = MagicMock()
        mock_response.json.return_value = {"candidates": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="no candidates"):
                client._complete_gemini("prompt", "", 100, 0.3)


class TestOpenAICompatCompletion:
    def test_parses_valid_response(self):
        s = _settings(ai_provider="groq")
        client = AIClient(s)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "AI response"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "post", return_value=mock_response):
            result = client._complete_openai_compat(
                "https://api.groq.com/openai/v1",
                "test-key",
                "prompt",
                "system",
                100,
                0.3,
            )

        assert result == "AI response"

    def test_raises_on_no_choices(self):
        s = _settings(ai_provider="groq")
        client = AIClient(s)

        mock_response = MagicMock()
        mock_response.json.return_value = {"choices": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="no choices"):
                client._complete_openai_compat(
                    "https://api.groq.com/openai/v1",
                    "test-key",
                    "prompt",
                    "",
                    100,
                    0.3,
                )


class TestOllamaCompletion:
    def test_parses_valid_response(self):
        s = _settings(ai_provider="ollama")
        client = AIClient(s)

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": "Local LLM response"}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "post", return_value=mock_response):
            result = client._complete_ollama("prompt", "system", 100, 0.3)

        assert result == "Local LLM response"

    def test_raises_on_empty_response(self):
        s = _settings(ai_provider="ollama")
        client = AIClient(s)

        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": ""}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(client._http, "post", return_value=mock_response):
            with pytest.raises(RuntimeError, match="empty response"):
                client._complete_ollama("prompt", "", 100, 0.3)
