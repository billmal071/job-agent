"""Tests for defensive AI response parsing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from job_agent.ai.client import AIClient
from job_agent.config import Settings


@pytest.fixture
def settings():
    return Settings(ai_provider="groq", groq_api_key="test-key")


@pytest.fixture
def client(settings):
    return AIClient(settings)


class TestGeminiDefensiveParsing:
    def test_empty_candidates_raises(self, settings):
        settings_gemini = Settings(ai_provider="gemini", gemini_api_key="test-key")
        c = AIClient(settings_gemini)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [],
            "promptFeedback": {"blockReason": "SAFETY"},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(c._http, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="no candidates"):
                c._complete_gemini("test", "", 100, 0.3)

    def test_no_candidates_key_raises(self, settings):
        settings_gemini = Settings(ai_provider="gemini", gemini_api_key="test-key")
        c = AIClient(settings_gemini)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": "quota exceeded"}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(c._http, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="no candidates"):
                c._complete_gemini("test", "", 100, 0.3)

    def test_empty_text_raises(self, settings):
        settings_gemini = Settings(ai_provider="gemini", gemini_api_key="test-key")
        c = AIClient(settings_gemini)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": ""}]}}]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(c._http, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="empty response"):
                c._complete_gemini("test", "", 100, 0.3)


class TestOpenAICompatDefensiveParsing:
    def test_empty_choices_raises(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [], "error": "no content"}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._http, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="no choices"):
                client._complete_openai_compat(
                    "https://api.test.com", "key", "test", "", 100, 0.3
                )

    def test_no_choices_key_raises(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": "model not found"}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._http, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="no choices"):
                client._complete_openai_compat(
                    "https://api.test.com", "key", "test", "", 100, 0.3
                )

    def test_empty_content_raises(self, client):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"choices": [{"message": {"content": ""}}]}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client._http, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="empty response"):
                client._complete_openai_compat(
                    "https://api.test.com", "key", "test", "", 100, 0.3
                )


class TestOllamaDefensiveParsing:
    def test_empty_response_raises(self, settings):
        settings_ollama = Settings(ai_provider="ollama")
        c = AIClient(settings_ollama)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message": {"content": ""}}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(c._http, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="empty response"):
                c._complete_ollama("test", "", 100, 0.3)

    def test_missing_message_raises(self, settings):
        settings_ollama = Settings(ai_provider="ollama")
        c = AIClient(settings_ollama)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"done": True}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(c._http, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="empty response"):
                c._complete_ollama("test", "", 100, 0.3)


class TestOllamaConfigurableUrl:
    def test_uses_custom_url(self):
        s = Settings(ai_provider="ollama", ollama_url="http://gpu-server:11434")
        c = AIClient(s)
        assert c._ollama_url == "http://gpu-server:11434"

    def test_uses_default_url(self):
        s = Settings(ai_provider="ollama")
        c = AIClient(s)
        assert c._ollama_url == "http://localhost:11434"
